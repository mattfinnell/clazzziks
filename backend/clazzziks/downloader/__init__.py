"""Core download + transcode logic built on yt-dlp and ffmpeg.

Each streaming platform is modelled as a :class:`Downloader` subclass in its own
module (:mod:`~clazzziks.downloader.youtube`,
:mod:`~clazzziks.downloader.soundcloud`).
This package re-exports the public API and owns URL -> downloader dispatch.
"""

from __future__ import annotations

import os

from ..formats import AudioFormat, DEFAULT_MP3_BITRATE
from .base import (
    Downloader,
    DownloadResult,
    DownloadUnavailableError,
    SOURCE_LABELS,
)
from .youtube import YoutubeDownloader
from .soundcloud import SoundcloudDownloader

__all__ = [
    "Downloader",
    "DownloadResult",
    "DownloadUnavailableError",
    "YoutubeDownloader",
    "SoundcloudDownloader",
    "downloader_for",
    "download_audio",
]

# Order matters only if hosts overlap (they don't); kept explicit for clarity.
_DOWNLOADERS: list[type[Downloader]] = [
    YoutubeDownloader,
    SoundcloudDownloader,
]


def downloader_for(url: str) -> Downloader:
    """Return the :class:`Downloader` responsible for ``url``.

    Raises :class:`ValueError` for hosts outside the supported platforms
    (YouTube, SoundCloud).
    """
    for cls in _DOWNLOADERS:
        if cls.handles(url):
            return cls()
    supported = ", ".join(SOURCE_LABELS[c.source] for c in _DOWNLOADERS)
    raise ValueError(
        f"Unsupported source for {url!r}. Supported platforms: {supported}."
    )


def download_audio(
    url: str,
    fmt: AudioFormat | str = AudioFormat.MP3,
    outdir: str | os.PathLike = ".",
    bitrate: int = DEFAULT_MP3_BITRATE,
    progress_hook=None,
) -> DownloadResult:
    """Download the audio at ``url`` and transcode it to ``fmt``.

    Thin facade that dispatches to the right :class:`Downloader`. ``progress_hook``
    is forwarded to yt-dlp for live per-track download/transcode progress.
    """
    return downloader_for(url).download(
        url, fmt=fmt, outdir=outdir, bitrate=bitrate, progress_hook=progress_hook
    )
