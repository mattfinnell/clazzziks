"""Infer Rekordbox-friendly tag fields (title, artist, genre, album/artwork)
from a yt-dlp ``info`` dict.

Pure functions only — no network, no file I/O. :func:`build_metadata` is the
entry point; :mod:`clazzziks.tagging` writes the resulting :class:`TrackMetadata`
into the actual audio file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NOISE_RE = re.compile(
    r"\s*[\(\[][^)\]]*\b(official|audio|video|lyric|lyrics|hq|hd|visualizer)\b[^)\]]*[\)\]]",
    re.IGNORECASE,
)
# Require whitespace on both sides of the separator so a hyphen inside a
# word/name ("T-Pain", "Anti-Hero", "X-Ray Spex") is never mistaken for the
# artist/title divider.
_SPLIT_RE = re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+?)\s*$")
_REMIX_RE = re.compile(
    r"[\(\[]([^)\]]+?)\s+(remix|edit|bootleg|flip|mashup|rework)[\)\]]", re.IGNORECASE
)
# Generic qualifiers that share the remix/edit shape but aren't an artist name
# ("Radio Edit", "Album Edit", "Clean Edit", ...) — never promote these to artist.
_GENERIC_EDIT_QUALIFIERS = {
    "radio", "album", "clean", "extended", "instrumental", "acoustic",
    "original", "single", "explicit", "dirty", "main", "full",
}
# The lookbehind anchors the keyword to the start of a word (preceded by
# whitespace or the start of the string) so it can't match mid-name
# ("Craft Spells", "Left Boy", "Swift Justice" all contain "ft"/"feat" as a
# substring but aren't a "featuring" credit) — a trailing `\b` doesn't work
# here since "feat." ends on a non-word "." character.
_FEAT_RE = re.compile(
    r"(?:(?<=^)|(?<=\s))[\(\[]?(?:feat\.|feat|ft\.|ft|featuring|w/)(?=\s).*$",
    re.IGNORECASE,
)
_TOPIC_RE = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)
_ALNUM_RE = re.compile(r"[^a-z0-9]+")
# Below this length, a normalized substring match against the uploader is too
# likely to be coincidental (e.g. a single-letter title/artist) to count as
# a confirmed disambiguation.
_MIN_CONFIRM_LENGTH = 3


@dataclass
class TrackMetadata:
    title: str
    artist: str | None
    genre: str | None
    album: str | None
    thumbnail_url: str | None
    warnings: list[str] = field(default_factory=list)


def _normalize(value: str) -> str:
    return _ALNUM_RE.sub("", value.lower())


def _strip_feat(artist: str) -> str:
    return _FEAT_RE.sub("", artist).strip()


def _split_title(raw: str, uploader: str | None) -> tuple[str, str, bool] | None:
    """Split ``raw`` into ``(artist, title, confirmed)``, or ``None`` if there's
    no separator to split on. ``confirmed`` is True when the uploader matched
    one side; False when we fell back to the default artist-first order."""
    cleaned = _NOISE_RE.sub("", raw).strip()
    match = _SPLIT_RE.match(cleaned)
    if not match:
        return None
    left, right = match.group(1), match.group(2)

    uploader_norm = _normalize(_TOPIC_RE.sub("", uploader or ""))
    left_norm, right_norm = _normalize(left), _normalize(right)

    if uploader_norm:
        left_match = len(left_norm) >= _MIN_CONFIRM_LENGTH and (
            left_norm in uploader_norm or uploader_norm in left_norm
        )
        right_match = len(right_norm) >= _MIN_CONFIRM_LENGTH and (
            right_norm in uploader_norm or uploader_norm in right_norm
        )
        if left_match and not right_match:
            return left, right, True
        if right_match and not left_match:
            return right, left, True

    # No confirmed match (or both/neither matched) — assume artist-first.
    return left, right, False


def _apply_remix_override(artist: str | None, title: str) -> str | None:
    remix_match = _REMIX_RE.search(title)
    if remix_match:
        candidate = remix_match.group(1).strip()
        if candidate.lower() not in _GENERIC_EDIT_QUALIFIERS:
            return candidate
    return artist


def _best_thumbnail_url(info: dict) -> tuple[str | None, str | None]:
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        best = max(
            thumbnails,
            key=lambda t: (
                (t.get("width") or 0) * (t.get("height") or 0),
                t.get("preference") or -1,
            ),
        )
        url = best.get("url")
        if url:
            return url, None
    url = info.get("thumbnail")
    if url:
        return url, None
    return None, "No artwork available for this track."


def _extract_genre(info: dict) -> tuple[str | None, str | None]:
    genre = info.get("genre")
    if genre:
        return genre, None
    categories = info.get("categories") or []
    if categories:
        return categories[0], None
    return None, "No genre information available from source."


def build_metadata(info: dict, fallback_title: str) -> TrackMetadata:
    warnings: list[str] = []
    raw_title = info.get("title") or fallback_title
    uploader = info.get("uploader") or info.get("channel")

    # yt-dlp's generic extractors commonly set info["track"] as a plain alias
    # for info["title"] (e.g. SoundCloud's `'track': ('title', {str})` field
    # map) rather than genuine structured music metadata, so a `track` that
    # merely duplicates the raw title can't be trusted as pre-split data.
    track_field, artist_field = info.get("track"), info.get("artist")
    if track_field and artist_field and _normalize(track_field) != _normalize(raw_title):
        title, artist = track_field, artist_field
    else:
        split = _split_title(raw_title, uploader)
        if split is None:
            title, artist = raw_title, None
            warnings.append("Could not determine an artist for this track.")
        else:
            artist, title, confirmed = split
            if not confirmed:
                warnings.append(
                    "Assumed 'artist - track' order; could not confirm against uploader."
                )

    artist = _apply_remix_override(artist, title)
    if artist:
        artist = _strip_feat(artist) or None

    genre, genre_warning = _extract_genre(info)
    if genre_warning:
        warnings.append(genre_warning)

    # Same field-aliasing quirk as `track`/`title`: some extractors set `album`
    # as a plain duplicate of the raw title rather than genuine album data.
    album = info.get("album") or None
    if album and _normalize(album) == _normalize(raw_title):
        album = None
    if not album:
        warnings.append("No album info available; using thumbnail as artwork fallback.")

    thumbnail_url, thumbnail_warning = _best_thumbnail_url(info)
    if thumbnail_warning:
        warnings.append(thumbnail_warning)

    return TrackMetadata(
        title=title,
        artist=artist,
        genre=genre,
        album=album,
        thumbnail_url=thumbnail_url,
        warnings=warnings,
    )
