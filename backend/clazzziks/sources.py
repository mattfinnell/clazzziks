"""Source detection.

Supported sources: YouTube and SoundCloud, both downloaded directly by yt-dlp.
"""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import urlparse


class Source(str, Enum):
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    UNKNOWN = "unknown"


_HOST_PATTERNS = {
    Source.YOUTUBE: (r"(^|\.)youtube\.com$", r"(^|\.)youtu\.be$", r"(^|\.)youtube-nocookie\.com$"),
    Source.SOUNDCLOUD: (r"(^|\.)soundcloud\.com$", r"(^|\.)snd\.sc$"),
}


def detect_source(url: str) -> Source:
    """Classify a URL by streaming platform.

    yt-dlp search queries (``ytsearch1:...``) are treated as YouTube since
    they are generated from sheet rows that lack a direct URL and are resolved
    via YoutubeDownloader.
    """
    if url.lower().startswith("ytsearch"):
        return Source.YOUTUBE
    host = (urlparse(url).hostname or "").lower()
    for source, patterns in _HOST_PATTERNS.items():
        if any(re.search(p, host) for p in patterns):
            return source
    return Source.UNKNOWN


def looks_like_url(text: str) -> bool:
    parsed = urlparse(text.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
