"""Unit tests for clazzziks.tagging: embed tags into real (tiny) audio files
synthesized locally via ffmpeg, then read them back with mutagen."""

# pylint: disable=missing-function-docstring,redefined-outer-name

import subprocess

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.wave import WAVE

from clazzziks.formats import AudioFormat
from clazzziks.metadata import TrackMetadata
from clazzziks.tagging import embed_tags

_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300010101010101"
    "010101010101010101010101010101010101010101010101010101010101"
    "010101010101010101010101010101010101010101010101010101010101"
    "0101ffc9000b080001000101011100ffcc00060010100005ffda0008010100"
    "003f00d2cfffd9"
)


@pytest.fixture
def tiny_audio(tmp_path):
    def _make(fmt: str):
        path = tmp_path / f"sample.{fmt}"
        subprocess.run(
            [
                "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
                "-y", str(path),
            ],
            check=True, capture_output=True,
        )
        return path

    return _make


def _full_metadata() -> TrackMetadata:
    return TrackMetadata(
        title="Track Title",
        artist="Track Artist",
        genre="House",
        album="Some Album",
        thumbnail_url="http://example.com/art.jpg",
    )


def test_embed_mp3_round_trip(tiny_audio):
    path = tiny_audio("mp3")
    warnings = embed_tags(path, AudioFormat.MP3, _full_metadata(), _TINY_JPEG)
    assert warnings == []

    tags = ID3(path)
    assert tags["TIT2"].text == ["Track Title"]
    assert tags["TPE1"].text == ["Track Artist"]
    assert tags["TALB"].text == ["Some Album"]
    assert tags["TCON"].text == ["House"]
    assert tags.getall("APIC")[0].data == _TINY_JPEG


def test_embed_flac_round_trip(tiny_audio):
    path = tiny_audio("flac")
    warnings = embed_tags(path, AudioFormat.FLAC, _full_metadata(), _TINY_JPEG)
    assert warnings == []

    audio = FLAC(path)
    assert audio["title"] == ["Track Title"]
    assert audio["artist"] == ["Track Artist"]
    assert audio["album"] == ["Some Album"]
    assert audio["genre"] == ["House"]
    assert audio.pictures[0].data == _TINY_JPEG


def test_embed_wav_round_trip(tiny_audio):
    path = tiny_audio("wav")
    warnings = embed_tags(path, AudioFormat.WAV, _full_metadata(), _TINY_JPEG)
    assert warnings == []

    audio = WAVE(path)
    assert audio.tags["TIT2"].text == ["Track Title"]
    assert audio.tags["TPE1"].text == ["Track Artist"]
    assert audio.tags["TALB"].text == ["Some Album"]
    assert audio.tags["TCON"].text == ["House"]
    assert audio.tags.getall("APIC")[0].data == _TINY_JPEG


def test_embed_partial_metadata_writes_only_present_fields(tiny_audio):
    path = tiny_audio("mp3")
    meta = TrackMetadata(
        title="Only Title", artist=None, genre=None, album=None, thumbnail_url=None
    )
    warnings = embed_tags(path, AudioFormat.MP3, meta, artwork=None)
    assert warnings == []

    tags = ID3(path)
    assert tags["TIT2"].text == ["Only Title"]
    assert "TPE1" not in tags
    assert "TALB" not in tags
    assert "TCON" not in tags
    assert "APIC:Cover" not in tags
