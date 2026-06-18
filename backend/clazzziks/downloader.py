"""Core download + transcode logic built on yt-dlp and ffmpeg.

Each streaming platform is modelled as a :class:`Downloader` subclass
(:class:`YoutubeDownloader`, :class:`SoundcloudDownloader`,
:class:`SpotifyDownloader`). :class:`Downloader` is an abstract base that owns
only the shared *orchestration* (the download -> transcode -> locate-output
pipeline); every platform-specific detail — how to resolve a URL, how to pick
the result, and how to explain a failure — is overridden polymorphically by the
subclass. Adding a new platform means writing one more subclass, nothing else.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import yt_dlp
from yt_dlp.utils import DownloadError as _YtdlpDownloadError

from .formats import (
    AudioFormat,
    DEFAULT_MP3_BITRATE,
    mp3_bitrate_warning,
    source_bitrate_warning,
)
from .sources import Source, detect_source, resolve as _resolve_source_url


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


_SOURCE_LABELS = {
    Source.YOUTUBE: "YouTube",
    Source.SOUNDCLOUD: "SoundCloud",
    Source.SPOTIFY: "Spotify",
}


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
        return _SOURCE_LABELS.get(self.source, "this")

    @abstractmethod
    def resolve(self, url: str) -> str:
        """Turn a page URL into a target yt-dlp can actually download."""

    def download(
        self,
        url: str,
        fmt: AudioFormat | str = AudioFormat.MP3,
        outdir: str | os.PathLike = ".",
        bitrate: int = DEFAULT_MP3_BITRATE,
    ) -> DownloadResult:
        """Download the audio at ``url`` and transcode it to ``fmt``.

        Returns a :class:`DownloadResult` pointing at the written file plus any
        quality warnings (e.g. sub-320kbps MP3).
        """
        fmt = fmt if isinstance(fmt, AudioFormat) else AudioFormat.parse(fmt)
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        if (w := mp3_bitrate_warning(bitrate)) and fmt is AudioFormat.MP3:
            warnings.append(w)

        target = self.resolve(url)

        try:
            with yt_dlp.YoutubeDL(self._ydl_options(fmt, outdir, bitrate)) as ydl:
                info = ydl.extract_info(target, download=True)
        except _YtdlpDownloadError as exc:
            raise self._translate_error(exc, url) from exc

        info = self._select_result(info, url)

        if (w := source_bitrate_warning(fmt, info.get("abr"))):
            warnings.append(w)

        path = self._resolve_output_path(ydl, info, fmt, outdir)

        return DownloadResult(
            path=path,
            title=info.get("title", "audio"),
            source=self.source.value,
            fmt=fmt,
            warnings=warnings,
        )

    # -- shared internals ----------------------------------------------------

    def _ydl_options(self, fmt: AudioFormat, outdir: Path, bitrate: int) -> dict:
        postprocessor = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": fmt.value,
        }
        if fmt is AudioFormat.MP3:
            # yt-dlp interprets preferredquality as a kbps target for lossy codecs.
            postprocessor["preferredquality"] = str(bitrate)

        return {
            "format": "bestaudio/best",
            "outtmpl": str(outdir / "%(title)s [%(id)s].%(ext)s"),
            "postprocessors": [postprocessor],
            "logger": _SilentLogger(),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "ignoreerrors": False,
            "restrictfilenames": False,
            "noplaylist": True,
        }

    def _select_result(self, info: dict, url: str) -> dict:
        """Pick the info dict to actually use from yt-dlp's output.

        Direct sources return a single track, so the default is a passthrough
        (with a defensive unwrap if a stray playlist appears). Search-based
        sources override this — see :class:`SpotifyDownloader`.
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


class YoutubeDownloader(Downloader):
    """YouTube audio: yt-dlp downloads the page URL directly."""

    source = Source.YOUTUBE

    def resolve(self, url: str) -> str:
        return url

    def _explain_failure(self, raw: str, url: str) -> str:
        low = raw.lower()
        if any(k in low for k in ("private", "members-only", "sign in", "login")):
            return f"This YouTube video is private or members-only and can't be downloaded. {url}"
        if any(k in low for k in ("unavailable", "removed", "terminated", "deleted")):
            return f"This YouTube video is unavailable (removed or taken down). {url}"
        if "geo" in low or "not available in your country" in low:
            return f"This YouTube video is geo-restricted and not available here. {url}"
        return super()._explain_failure(raw, url)


class SoundcloudDownloader(Downloader):
    """SoundCloud audio: yt-dlp downloads the page URL directly.

    Many tracks are now served only as AES-encrypted (DRM) streams, which
    yt-dlp cannot decrypt; that's this platform's signature failure mode.
    """

    source = Source.SOUNDCLOUD

    def resolve(self, url: str) -> str:
        return url

    def _explain_failure(self, raw: str, url: str) -> str:
        low = raw.lower()
        if "drm" in low:
            return (
                "This SoundCloud track is DRM-protected: its only streams are "
                f"encrypted and cannot be downloaded. {url}"
            )
        if "geo" in low or "not available in your" in low:
            return f"This SoundCloud track is geo-restricted and not available here. {url}"
        return super()._explain_failure(raw, url)


class SpotifyDownloader(Downloader):
    """Spotify audio.

    Spotify streams are DRM-protected and cannot be downloaded directly, so we
    resolve the track's metadata and hand yt-dlp a YouTube search for the same
    recording (the strategy tools like spotdl use). The search therefore returns
    a playlist-shaped result, and failures are really "no YouTube match".
    """

    source = Source.SPOTIFY

    def resolve(self, url: str) -> str:
        return _resolve_source_url(url)

    def _select_result(self, info: dict, url: str) -> dict:
        # A ``ytsearch`` always yields a playlist; take the top match.
        entries = self._entries(info) or []
        if not entries:
            raise DownloadUnavailableError(
                f"No YouTube match found for this Spotify track. {url}"
            )
        return entries[0]

    def _explain_failure(self, raw: str, url: str) -> str:
        return (
            "Couldn't fetch a downloadable YouTube match for this Spotify track: "
            f"{raw or 'no results'}. {url}"
        )


# Order matters only if hosts overlap (they don't); kept explicit for clarity.
_DOWNLOADERS: list[type[Downloader]] = [
    YoutubeDownloader,
    SoundcloudDownloader,
    SpotifyDownloader,
]


def downloader_for(url: str) -> Downloader:
    """Return the :class:`Downloader` responsible for ``url``.

    Raises :class:`ValueError` for hosts outside the supported platforms
    (YouTube, SoundCloud, Spotify).
    """
    for cls in _DOWNLOADERS:
        if cls.handles(url):
            return cls()
    supported = ", ".join(_SOURCE_LABELS[c.source] for c in _DOWNLOADERS)
    raise ValueError(
        f"Unsupported source for {url!r}. Supported platforms: {supported}."
    )


def download_audio(
    url: str,
    fmt: AudioFormat | str = AudioFormat.MP3,
    outdir: str | os.PathLike = ".",
    bitrate: int = DEFAULT_MP3_BITRATE,
) -> DownloadResult:
    """Download the audio at ``url`` and transcode it to ``fmt``.

    Thin facade that dispatches to the right :class:`Downloader`.
    """
    return downloader_for(url).download(url, fmt=fmt, outdir=outdir, bitrate=bitrate)
