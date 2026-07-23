"""Unit tests for clazzziks.downloader.base's clean-filename helpers."""

# pylint: disable=missing-function-docstring

from clazzziks.downloader.base import _clean_output_name, _dedupe_path, _sanitize_filename
from clazzziks.formats import AudioFormat


def test_sanitize_filename_strips_illegal_characters():
    assert _sanitize_filename('Weird: Name / With * Illegal? Chars"<>|') == "Weird Name With Illegal Chars"


def test_sanitize_filename_collapses_whitespace_and_trims():
    assert _sanitize_filename("  Too    much   space.  ") == "Too much space"


def test_sanitize_filename_empty_falls_back_to_audio():
    assert _sanitize_filename("???") == "audio"


def test_clean_output_name_includes_artist_when_present():
    assert _clean_output_name("Space Glitch", "Baseli, Ale Montoya", AudioFormat.MP3) == (
        "Baseli, Ale Montoya - Space Glitch.mp3"
    )


def test_clean_output_name_title_only_when_no_artist():
    assert _clean_output_name("Space Glitch", None, AudioFormat.FLAC) == "Space Glitch.flac"


def test_dedupe_path_returns_candidate_when_free(tmp_path):
    current = tmp_path / "raw [123].mp3"
    current.touch()
    candidate = tmp_path / "Clean Title.mp3"
    assert _dedupe_path(candidate, current) == candidate


def test_dedupe_path_returns_candidate_when_it_is_the_current_file(tmp_path):
    current = tmp_path / "Clean Title.mp3"
    current.touch()
    assert _dedupe_path(current, current) == current


def test_dedupe_path_appends_counter_on_collision(tmp_path):
    current = tmp_path / "raw [123].mp3"
    current.touch()
    (tmp_path / "Clean Title.mp3").touch()
    candidate = tmp_path / "Clean Title.mp3"
    assert _dedupe_path(candidate, current) == tmp_path / "Clean Title (2).mp3"


def test_dedupe_path_skips_taken_counters(tmp_path):
    current = tmp_path / "raw [123].mp3"
    current.touch()
    (tmp_path / "Clean Title.mp3").touch()
    (tmp_path / "Clean Title (2).mp3").touch()
    candidate = tmp_path / "Clean Title.mp3"
    assert _dedupe_path(candidate, current) == tmp_path / "Clean Title (3).mp3"


def test_sanitize_filename_truncates_by_bytes_not_characters():
    # A 200-character CJK title is ~600 UTF-8 bytes — well past a
    # filesystem's typical 255-byte-per-component limit — so truncation must
    # be byte-aware, not just character-count-aware.
    name = _sanitize_filename("가" * 200)
    assert len(name.encode("utf-8")) <= 255
