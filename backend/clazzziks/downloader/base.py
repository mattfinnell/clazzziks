"""Shared download + transcode machinery for every platform.

:class:`Downloader` is an abstract base that owns only the shared *orchestration*
(the download -> transcode -> locate-output pipeline). Each concrete platform
lives in its own module (``youtube``, ``soundcloud``) and overrides the
polymorphic hooks here. Adding a new platform means writing one more module,
nothing else.
"""

from __future__ import annotations

import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, ClassVar

import yt_dlp
from yt_dlp.utils import DownloadError as _YtdlpDownloadError

from ..formats import (
    AudioFormat,
    DEFAULT_MP3_BITRATE,
    mp3_bitrate_warning,
    source_bitrate_warning,
)
from ..logging_config import log_event
from ..sources import Source, detect_source

logger = logging.getLogger(__name__)


class DownloadUnavailableError(RuntimeError):
    """A track exists but cannot be downloaded (DRM, geo-block, removed, ...).

    Distinct from unexpected/internal failures so callers (CLI, web API, batch
    bundler) can surface a clear, user-facing reason instead of a raw yt-dlp
    traceback string.
    """


@dataclass
class DownloadResult:
    path: Path
    title: str
    source: str
    fmt: AudioFormat
    warnings: list[str] = field(default_factory=list)
    #: The originating page URL this result came from (used for cache keys).
    url: str = ""


class _SilentLogger:
    """Swallow yt-dlp's own logging; we raise/return our own messages instead.

    Without this yt-dlp prints lines like "ERROR: [soundcloud] ...: This video
    is DRM protected" straight to stderr, duplicating (and contradicting) the
    friendly error we surface to the user.
    """

    def debug(self, msg): ...
    def info(self, msg): ...
    def warning(self, msg): ...
    def error(self, msg): ...


SOURCE_LABELS = {
    Source.YOUTUBE: "YouTube",
    Source.SOUNDCLOUD: "SoundCloud",
}


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


class Downloader(ABC):
    """Abstract base for one streaming platform's audio downloader.

    The :meth:`download` template method drives the shared pipeline and calls
    these polymorphic hooks, which subclasses specialize:

    * :meth:`resolve` (abstract) — turn a page URL into a yt-dlp target.
    * :meth:`_select_result` — choose the info dict to keep from yt-dlp's output.
    * :meth:`_explain_failure` — turn a raw yt-dlp error into a platform-specific,
      user-facing message.

    Subclasses set :attr:`source`; everything else they need is inherited.
    """

    #: The platform this downloader serves. Subclasses must set it.
    source: ClassVar[Source]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if getattr(cls, "source", None) is None:
            raise TypeError(f"{cls.__name__} must define a class-level `source`.")

    @classmethod
    def handles(cls, url: str) -> bool:
        """Whether this downloader is responsible for ``url``."""
        return detect_source(url) is cls.source

    @property
    def label(self) -> str:
        """Human-friendly platform name used in user-facing messages."""
        return SOURCE_LABELS.get(self.source, "this")

    @abstractmethod
    def resolve(self, url: str) -> str:
        """Turn a page URL into a target yt-dlp can actually download."""

    def download(
        self,
        url: str,
        fmt: AudioFormat | str = AudioFormat.MP3,
        outdir: str | os.PathLike = ".",
        bitrate: int = DEFAULT_MP3_BITRATE,
        progress_hook: "Callable[[dict], None] | None" = None,
    ) -> DownloadResult:
        """Download the audio at ``url`` and transcode it to ``fmt``.

        Returns a :class:`DownloadResult` pointing at the written file plus any
        quality warnings (e.g. sub-320kbps MP3).

        ``progress_hook``, if given, is registered as both a yt-dlp
        ``progress_hooks`` (download %) and ``postprocessor_hooks`` (ffmpeg
        transcode) callback, letting callers stream live per-track progress.
        """
        fmt = fmt if isinstance(fmt, AudioFormat) else AudioFormat.parse(fmt)
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        if (w := mp3_bitrate_warning(bitrate)) and fmt is AudioFormat.MP3:
            warnings.append(w)

        started = time.perf_counter()
        log_event(
            logger, logging.INFO, "download.start",
            url=url, source=self.source.value, format=fmt.value, bitrate=bitrate,
        )

        target = self.resolve(url)

        try:
            with yt_dlp.YoutubeDL(self._ydl_options(fmt, outdir, bitrate, progress_hook)) as ydl:
                info = ydl.extract_info(target, download=True)
            info = self._select_result(info, url)
        except _YtdlpDownloadError as exc:
            error = self._translate_error(exc, url)
            log_event(
                logger, logging.WARNING, "download.unavailable",
                url=url, source=self.source.value,
                duration_ms=elapsed_ms(started), reason=str(error),
            )
            raise error from exc
        except DownloadUnavailableError as exc:
            # e.g. a ytsearch query that resolved to zero results.
            log_event(
                logger, logging.WARNING, "download.unavailable",
                url=url, source=self.source.value,
                duration_ms=elapsed_ms(started), reason=str(exc),
            )
            raise

        if (w := source_bitrate_warning(fmt, info.get("abr"))):
            warnings.append(w)

        path = self._resolve_output_path(ydl, info, fmt, outdir)

        result = DownloadResult(
            path=path,
            title=info.get("title", "audio"),
            source=self.source.value,
            fmt=fmt,
            warnings=warnings,
            url=url,
        )
        log_event(
            logger, logging.INFO, "download.complete",
            url=url, source=self.source.value, format=fmt.value,
            title=result.title, path=str(path),
            duration_ms=elapsed_ms(started), warnings=len(warnings),
        )
        return result

    # -- shared internals ----------------------------------------------------

    def _ydl_options(
        self,
        fmt: AudioFormat,
        outdir: Path,
        bitrate: int,
        progress_hook: "Callable[[dict], None] | None" = None,
    ) -> dict:
        postprocessor = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": fmt.value,
        }
        if fmt is AudioFormat.MP3:
            # yt-dlp interprets preferredquality as a kbps target for lossy codecs.
            postprocessor["preferredquality"] = str(bitrate)

        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(outdir / "%(title)s [%(id)s].%(ext)s"),
            "postprocessors": [postprocessor],
            "logger": _SilentLogger(),
            "quiet": True,
            "no_warnings": True,
            # noprogress only silences yt-dlp's console line; our hooks still fire.
            "noprogress": True,
            "ignoreerrors": False,
            "restrictfilenames": False,
            "noplaylist": True,
        }
        if progress_hook is not None:
            opts["progress_hooks"] = [progress_hook]
            opts["postprocessor_hooks"] = [progress_hook]
        return opts

    def _select_result(self, info: dict, url: str) -> dict:
        """Pick the info dict to actually use from yt-dlp's output.

        Direct page URLs return a single track, so the default is a passthrough.
        A ``ytsearch`` query (from a sheet row with no URL) yields a playlist —
        the unwrap below takes its top match. Subclasses may override this.
        """
        entries = self._entries(info)
        if entries is None:
            return info
        if not entries:
            raise DownloadUnavailableError(
                f"No downloadable audio found for this {self.label} link. {url}"
            )
        return entries[0]

    @staticmethod
    def _entries(info: dict) -> list[dict] | None:
        """Non-empty entries of a playlist-shaped result, or ``None`` if single."""
        if info.get("_type") == "playlist" or "entries" in info:
            return [e for e in (info.get("entries") or []) if e]
        return None

    def _translate_error(self, exc: _YtdlpDownloadError, url: str) -> DownloadUnavailableError:
        """Normalize a raw yt-dlp error, then defer wording to the subclass.

        Strips yt-dlp's "ERROR: [extractor] id: " prefix and hands the cleaned
        text to :meth:`_explain_failure`, which each platform overrides.
        """
        raw = re.sub(r"^ERROR:\s*", "", str(exc)).strip()
        raw = re.sub(r"^\[[^\]]+\]\s*\S+:\s*", "", raw)
        return DownloadUnavailableError(self._explain_failure(raw, url))

    def _explain_failure(self, raw: str, url: str) -> str:
        """Default, platform-agnostic explanation. Subclasses refine this."""
        return f"Could not download this {self.label} track: {raw or 'unknown error'}. {url}"

    def _resolve_output_path(
        self, ydl: "yt_dlp.YoutubeDL", info: dict, fmt: AudioFormat, outdir: Path
    ) -> Path:
        """Determine the final transcoded file path yt-dlp produced."""
        base = Path(ydl.prepare_filename(info))
        candidate = base.with_suffix(f".{fmt.value}")
        if candidate.exists():
            return candidate

        # Fall back to matching by id if the template/extension diverged.
        stem = base.stem
        matches = sorted(outdir.glob(f"{stem}.*"))
        audio = [m for m in matches if m.suffix.lstrip(".") == fmt.value]
        if audio:
            return audio[0]
        if matches:
            return matches[0]
        raise FileNotFoundError(
            f"Download completed but no output file was found for {info.get('title')!r}."
        )
