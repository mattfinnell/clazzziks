"""SoundCloud audio downloader."""

from __future__ import annotations

from ..sources import Source
from .base import Downloader


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
