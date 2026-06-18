"""YouTube audio downloader."""

from __future__ import annotations

from ..sources import Source
from .base import Downloader


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
