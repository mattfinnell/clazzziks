"""Source detection and resolution.

Tolerable sources: YouTube, SoundCloud, Spotify.

YouTube and SoundCloud are downloaded directly by yt-dlp. Spotify streams are
DRM-protected and cannot be downloaded; instead we resolve the track's metadata
(title/artist) and hand yt-dlp a YouTube search query for the same recording —
the same strategy tools like spotdl use.
"""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import urlparse

import requests


class Source(str, Enum):
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    SPOTIFY = "spotify"
    UNKNOWN = "unknown"


_HOST_PATTERNS = {
    Source.YOUTUBE: (r"(^|\.)youtube\.com$", r"(^|\.)youtu\.be$", r"(^|\.)youtube-nocookie\.com$"),
    Source.SOUNDCLOUD: (r"(^|\.)soundcloud\.com$", r"(^|\.)snd\.sc$"),
    Source.SPOTIFY: (r"(^|\.)spotify\.com$", r"(^|\.)spotify\.link$"),
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


def resolve(url: str, *, timeout: float = 15.0) -> str:
    """Resolve a URL into something yt-dlp can download.

    Direct sources pass through unchanged. Spotify links are converted into a
    ``ytsearch1:`` query built from the track's title and artist.
    """
    if detect_source(url) is Source.SPOTIFY:
        return _spotify_to_search_query(url, timeout=timeout)
    return url


def _spotify_to_search_query(url: str, *, timeout: float) -> str:
    """Use Spotify's public oEmbed endpoint to recover the track title."""
    try:
        resp = requests.get(
            "https://open.spotify.com/oembed",
            params={"url": url},
            timeout=timeout,
            headers={"User-Agent": "clazzziks/0.1"},
        )
        resp.raise_for_status()
        title = (resp.json().get("title") or "").strip()
    except (requests.RequestException, ValueError) as exc:
        raise ValueError(
            f"Could not resolve Spotify metadata for {url!r}: {exc}"
        ) from exc

    if not title:
        raise ValueError(f"Spotify track at {url!r} returned no title metadata.")

    # ytsearch1: tells yt-dlp to take the single best YouTube match.
    return f"ytsearch1:{title} audio"
