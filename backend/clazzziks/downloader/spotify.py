"""Spotify audio downloader."""

from __future__ import annotations

from ..sources import Source, resolve as _resolve_source_url
from .base import Downloader, DownloadUnavailableError


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
