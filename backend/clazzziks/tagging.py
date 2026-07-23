"""Write inferred track metadata (title/artist/genre/album/artwork) into the
downloaded audio file, per format. File I/O only — no network calls; the
caller (:mod:`clazzziks.downloader.base`) fetches artwork bytes and passes
them in.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TCON, TIT2, TPE1
from mutagen.wave import WAVE

from .formats import AudioFormat
from .metadata import TrackMetadata

_COVER_MIME = "image/jpeg"


def embed_tags(
    path: Path, fmt: AudioFormat, meta: TrackMetadata, artwork: bytes | None
) -> list[str]:
    """Write ``meta`` (and ``artwork``, if any) into the file at ``path``.

    Never raises for a single missing/unwritable field — those are collected
    as warning strings instead. Only genuinely unexpected I/O errors escape
    (the caller wraps this in its own try/except).
    """
    if fmt is AudioFormat.FLAC:
        return _embed_flac(path, meta, artwork)
    return _embed_id3(path, meta, artwork, wav=fmt is AudioFormat.WAV)


def _embed_id3(path: Path, meta: TrackMetadata, artwork: bytes | None, *, wav: bool) -> list[str]:
    warnings: list[str] = []

    if wav:
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
    else:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

    def _set(label: str, frame) -> None:
        try:
            tags.setall(frame.FrameID, [frame])
        except Exception as exc:  # noqa: BLE001 - one bad field shouldn't block the rest
            warnings.append(f"Could not embed {label} tag: {exc}")

    _set("title", TIT2(encoding=3, text=[meta.title]))
    if meta.artist:
        _set("artist", TPE1(encoding=3, text=[meta.artist]))
    if meta.album:
        _set("album", TALB(encoding=3, text=[meta.album]))
    if meta.genre:
        _set("genre", TCON(encoding=3, text=[meta.genre]))
    if artwork:
        _set(
            "artwork",
            APIC(encoding=3, mime=_COVER_MIME, type=3, desc="Cover", data=artwork),
        )

    if wav:
        audio.save()
    else:
        tags.save(path, v2_version=3)
    return warnings


def _embed_flac(path: Path, meta: TrackMetadata, artwork: bytes | None) -> list[str]:
    warnings: list[str] = []
    audio = FLAC(path)

    def _set(label: str, key: str, value: str) -> None:
        try:
            audio[key] = [value]
        except Exception as exc:  # noqa: BLE001 - one bad field shouldn't block the rest
            warnings.append(f"Could not embed {label} tag: {exc}")

    _set("title", "title", meta.title)
    if meta.artist:
        _set("artist", "artist", meta.artist)
    if meta.album:
        _set("album", "album", meta.album)
    if meta.genre:
        _set("genre", "genre", meta.genre)
    if artwork:
        try:
            picture = Picture()
            picture.type = 3
            picture.mime = _COVER_MIME
            picture.data = artwork
            audio.add_picture(picture)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Could not embed artwork tag: {exc}")

    audio.save()
    return warnings
