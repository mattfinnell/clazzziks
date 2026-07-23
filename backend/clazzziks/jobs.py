"""Background download jobs with live per-track progress.

A ``download`` GraphQL mutation creates a :class:`DownloadJob` (returning its id)
and schedules it; the ``progress(job_id)`` subscription then streams the job's
events. This decouples the (long, blocking) download work from the request that
started it, and lets the frontend render a docker-build-style readout — one line
per track moving through *queued → downloading → transcoding → done/failed*.

Concurrency: a job downloads up to :data:`_WORKERS` tracks in parallel on a
``ThreadPoolExecutor`` (mirroring the CLI). yt-dlp runs blocking in those worker
threads and pushes progress via :meth:`DownloadJob._emit`, which hops back onto the
asyncio loop (``call_soon_threadsafe``) to feed each subscriber's queue.

Reconnect: every emitted event is retained in ``_history`` and replayed to a new
subscriber before live events, so a client that (re)subscribes late — even after the
job finished — still sees the whole story, ending with the terminal
:class:`CompleteEvent` that carries the ``/files/{token}`` handle.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Optional, Union

from .formats import AudioFormat, DEFAULT_MP3_BITRATE
from .downloader import download_audio, DownloadResult, DownloadUnavailableError
from .bundle import write_zip
from .logging_config import log_event
from . import db

logger = logging.getLogger(__name__)

_WORKERS = 4

# Per-track states, mirrored by the frontend readout.
QUEUED = "queued"
DOWNLOADING = "downloading"
TRANSCODING = "transcoding"
DONE = "done"
FAILED = "failed"


# --- token-based file handoff ----------------------------------------------
# GraphQL can't return bytes, so a finished job registers its output under an
# unguessable token; GET /files/{token} (api.py) streams it. Entries live for the
# process lifetime — fine given the ephemeral tracks/ dir is wiped with the container.
_FILE_TOKENS: dict[str, tuple[Path, Optional[str]]] = {}


def register_file(path: Path, media_type: Optional[str] = None) -> str:
    token = uuid.uuid4().hex
    _FILE_TOKENS[token] = (path, media_type)
    return token


def get_file(token: str) -> Optional[tuple[Path, Optional[str]]]:
    return _FILE_TOKENS.get(token)


# --- progress events -------------------------------------------------------

@dataclass(frozen=True)
class TrackEvent:
    """One track's state at a point in time."""
    url: str
    title: Optional[str]
    index: int
    total: int
    state: str
    pct: Optional[float]
    error: Optional[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompleteEvent:
    """Terminal event: the whole job finished (``token`` is None if it produced
    nothing downloadable)."""
    token: Optional[str]
    filename: Optional[str]
    warnings: list[str]
    failures: list[str]


Event = Union[TrackEvent, CompleteEvent]


class DownloadJob:
    def __init__(
        self,
        job_id: str,
        urls: list[str],
        *,
        uid: str,
        email: Optional[str],
        outdir: Path,
        loop: asyncio.AbstractEventLoop,
    ):
        self.id = job_id
        self.urls = urls
        self.uid = uid
        self.email = email
        self.outdir = outdir
        self._loop = loop
        self._lock = threading.Lock()
        self._history: list[Event] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._last_pct: dict[int, float] = {}

    # -- broadcast -----------------------------------------------------------

    def _emit(self, event: Event) -> None:
        """Record an event and fan it out to live subscribers.

        Called from worker threads, so subscriber queues are fed via the loop.
        """
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
        for q in subscribers:
            self._loop.call_soon_threadsafe(q.put_nowait, event)

    async def subscribe(self) -> AsyncGenerator[Event, None]:
        """Yield this job's events: buffered history first, then live ones,
        ending at the terminal :class:`CompleteEvent`."""
        q: asyncio.Queue = asyncio.Queue()
        # Snapshot history and register atomically so no event slips through the
        # gap between the two (an emit either lands in `backlog` or in `q`).
        with self._lock:
            backlog = list(self._history)
            self._subscribers.add(q)
        try:
            for event in backlog:
                yield event
                if isinstance(event, CompleteEvent):
                    return
            while True:
                event = await q.get()
                yield event
                if isinstance(event, CompleteEvent):
                    return
        finally:
            with self._lock:
                self._subscribers.discard(q)

    # -- execution -----------------------------------------------------------

    def start(self) -> None:
        """Kick the job off on a daemon thread.

        A plain thread (not an asyncio task) keeps the work independent of the
        request that started it — robust across uvicorn and the test harness alike.
        Events reach the async subscribers via :meth:`_emit`'s loop hop.
        """
        threading.Thread(target=self._run, name=f"job-{self.id[:8]}", daemon=True).start()

    def _run(self) -> None:
        """Download every URL (up to :data:`_WORKERS` at a time) and emit progress,
        then package the result and emit the terminal event. Never raises —
        failures become events."""
        total = len(self.urls)
        fmt = AudioFormat.MP3
        bitrate = DEFAULT_MP3_BITRATE

        for index, url in enumerate(self.urls):
            self._emit(TrackEvent(url, None, index, total, QUEUED, None, None))

        try:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                futures = {
                    pool.submit(self._download_one, index, url, fmt, bitrate): index
                    for index, url in enumerate(self.urls)
                }
                outcomes = [None] * total
                for future in concurrent.futures.as_completed(futures):
                    outcomes[futures[future]] = future.result()
            self._finish(outcomes)
        except Exception as exc:  # noqa: BLE001 - a job must always terminate cleanly
            log_event(logger, logging.ERROR, "job.failed", job_id=self.id, error=str(exc), exc_info=True)
            self._emit(CompleteEvent(token=None, filename=None, warnings=[], failures=[f"job error: {exc}"]))

    def _download_one(self, index: int, url: str, fmt: AudioFormat, bitrate: int):
        """Blocking: download+transcode one track (runs on a worker thread).

        Returns ``("ok", DownloadResult)`` or ``("fail", (url, error))``.
        """
        total = len(self.urls)
        cached = db.get_cached_track(url, fmt.value)
        if cached:
            db.log_download(self.uid, self.email, url)
            self._emit(TrackEvent(url, cached.title, index, total, DONE, 100.0, None, warnings=list(cached.warnings)))
            return "ok", DownloadResult(
                path=Path(cached.path), title=cached.title or "audio",
                source=cached.source or "", fmt=fmt, url=url, warnings=list(cached.warnings),
            )

        self._emit(TrackEvent(url, None, index, total, DOWNLOADING, 0.0, None))

        def hook(d: dict) -> None:
            self._on_ytdlp(index, url, total, d)

        try:
            result = download_audio(url, fmt=fmt, outdir=self.outdir, bitrate=bitrate, progress_hook=hook)
        except DownloadUnavailableError as exc:
            self._emit(TrackEvent(url, None, index, total, FAILED, None, str(exc)))
            return "fail", (url, str(exc))
        except Exception as exc:  # noqa: BLE001 - record and keep the batch going
            log_event(logger, logging.WARNING, "job.item_failed", job_id=self.id, url=url, error=str(exc))
            self._emit(TrackEvent(url, None, index, total, FAILED, None, str(exc)))
            return "fail", (url, str(exc))

        db.cache_track(
            url, fmt.value, path=str(result.path), title=result.title,
            source=result.source, warnings=result.warnings,
        )
        db.log_download(self.uid, self.email, url)
        self._emit(TrackEvent(url, result.title, index, total, DONE, 100.0, None, warnings=list(result.warnings)))
        return "ok", result

    def _on_ytdlp(self, index: int, url: str, total: int, d: dict) -> None:
        """Translate a raw yt-dlp hook dict into a throttled TrackEvent."""
        status = d.get("status")
        if d.get("postprocessor"):  # a postprocessor_hooks call (ffmpeg transcode)
            if status == "started":
                self._emit(TrackEvent(url, None, index, total, TRANSCODING, None, None))
            return
        if status == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            if not total_bytes:
                return
            pct = round(downloaded / total_bytes * 100, 1)
            # Throttle: only emit on a whole-percent advance (and at 100).
            last = self._last_pct.get(index)
            if last is not None and pct < 100 and pct - last < 1:
                return
            self._last_pct[index] = pct
            self._emit(TrackEvent(url, None, index, total, DOWNLOADING, pct, None))
        elif status == "finished":
            # Download bytes are in; ffmpeg transcode is next.
            self._emit(TrackEvent(url, None, index, total, TRANSCODING, None, None))

    def _finish(self, outcomes: list) -> None:
        """Assemble the successful tracks into a file/bundle and emit the terminal event."""
        items = [payload for status, payload in outcomes if status == "ok"]
        failures = [payload for status, payload in outcomes if status == "fail"]
        fail_notes = [f"failed: {url}" for url, _ in failures]

        if not items:
            self._emit(CompleteEvent(token=None, filename=None, warnings=[], failures=fail_notes))
            return

        if len(self.urls) == 1:
            item = items[0]
            token = register_file(item.path, None)
            self._emit(CompleteEvent(
                token=token, filename=item.path.name,
                warnings=list(item.warnings), failures=fail_notes,
            ))
            return

        self.outdir.mkdir(parents=True, exist_ok=True)
        bundle_path = self.outdir / "clazzziks_bundle.zip"
        write_zip(bundle_path, items)
        warnings = [f"{it.title}: {w}" for it in items for w in it.warnings]
        token = register_file(bundle_path, "application/zip")
        self._emit(CompleteEvent(
            token=token, filename=bundle_path.name, warnings=warnings, failures=fail_notes,
        ))


class JobBroker:
    """Process-wide registry of in-flight/finished download jobs."""

    def __init__(self):
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()

    def create(
        self,
        urls: list[str],
        *,
        uid: str,
        email: Optional[str],
        outdir: Path,
        loop: asyncio.AbstractEventLoop,
    ) -> DownloadJob:
        job = DownloadJob(uuid.uuid4().hex, urls, uid=uid, email=email, outdir=outdir, loop=loop)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[DownloadJob]:
        with self._lock:
            return self._jobs.get(job_id)


broker = JobBroker()
