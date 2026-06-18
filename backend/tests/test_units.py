"""Offline unit tests for CLAZZZIKS pure logic (no network/yt-dlp calls)."""

# Test conventions: pytest discovers bare functions, and unit tests legitimately
# exercise non-public helpers and define throwaway classes.
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=protected-access,too-few-public-methods

import csv

import pytest
from yt_dlp.utils import DownloadError as YtdlpDownloadError

from clazzziks.formats import (
    AudioFormat,
    mp3_bitrate_warning,
    source_bitrate_warning,
)
from clazzziks.sources import detect_source, Source, looks_like_url
from clazzziks.inputs import collect_urls, _google_sheet_csv_url
from clazzziks.downloader import (
    Downloader,
    YoutubeDownloader,
    SoundcloudDownloader,
    SpotifyDownloader,
    DownloadUnavailableError,
    downloader_for,
)


# --- formats ---------------------------------------------------------------

def test_format_parse_and_lossless():
    assert AudioFormat.parse("MP3") is AudioFormat.MP3
    assert AudioFormat.parse(" flac ") is AudioFormat.FLAC
    assert AudioFormat.WAV.lossless and AudioFormat.FLAC.lossless
    assert not AudioFormat.MP3.lossless


def test_format_parse_rejects_unknown():
    with pytest.raises(ValueError):
        AudioFormat.parse("ogg")


def test_mp3_bitrate_warning():
    assert mp3_bitrate_warning(320) is None
    assert mp3_bitrate_warning(192) is not None


def test_source_bitrate_warning_only_for_low_mp3():
    assert source_bitrate_warning(AudioFormat.MP3, 128) is not None
    assert source_bitrate_warning(AudioFormat.MP3, 320) is None
    assert source_bitrate_warning(AudioFormat.FLAC, 64) is None
    assert source_bitrate_warning(AudioFormat.MP3, None) is None


# --- source detection ------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=abc", Source.YOUTUBE),
    ("https://youtu.be/abc", Source.YOUTUBE),
    ("https://soundcloud.com/artist/track", Source.SOUNDCLOUD),
    ("https://open.spotify.com/track/xyz", Source.SPOTIFY),
    ("https://example.com/song.mp3", Source.UNKNOWN),
])
def test_detect_source(url, expected):
    assert detect_source(url) is expected


def test_detect_source_not_fooled_by_substring():
    # A host that merely contains "youtube" as a non-domain must not match.
    assert detect_source("https://notyoutube.evil.com/watch") is Source.UNKNOWN


def test_looks_like_url():
    assert looks_like_url("https://x.com/a")
    assert not looks_like_url("just text")
    assert not looks_like_url("ftp://x.com")


# --- input collection ------------------------------------------------------

def test_collect_from_list():
    urls = collect_urls(["https://a.com/1", "not a link", "https://b.com/2"])
    assert urls == ["https://a.com/1", "https://b.com/2"]


def test_collect_dedupes_and_splits_text():
    urls = collect_urls("https://a.com/1, https://a.com/1\nhttps://b.com/2")
    assert urls == ["https://a.com/1", "https://b.com/2"]


def test_collect_from_csv_file(tmp_path):
    p = tmp_path / "links.csv"
    rows = [["title", "url"], ["Song A", "https://a.com/1"], ["Song B", "https://b.com/2"]]
    with p.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    assert collect_urls(str(p)) == ["https://a.com/1", "https://b.com/2"]


def test_collect_from_txt_file(tmp_path):
    p = tmp_path / "links.txt"
    p.write_text("https://a.com/1\nhttps://b.com/2\n# comment\n")
    assert collect_urls(str(p)) == ["https://a.com/1", "https://b.com/2"]


def test_google_sheet_csv_url():
    url = "https://docs.google.com/spreadsheets/d/ABC123/edit#gid=42"
    csv_url = _google_sheet_csv_url(url)
    assert "ABC123/export?format=csv" in csv_url
    assert "gid=42" in csv_url


# --- downloaders -----------------------------------------------------------

@pytest.mark.parametrize("url,cls,source", [
    ("https://www.youtube.com/watch?v=abc", YoutubeDownloader, Source.YOUTUBE),
    ("https://youtu.be/abc", YoutubeDownloader, Source.YOUTUBE),
    ("https://soundcloud.com/artist/track", SoundcloudDownloader, Source.SOUNDCLOUD),
    ("https://open.spotify.com/track/xyz", SpotifyDownloader, Source.SPOTIFY),
])
def test_downloader_for_picks_right_implementation(url, cls, source):
    dl = downloader_for(url)
    assert isinstance(dl, cls)
    assert dl.source is source
    assert cls.handles(url)


def test_downloader_for_rejects_unsupported():
    with pytest.raises(ValueError):
        downloader_for("https://example.com/song.mp3")


def test_downloader_is_abstract():
    # The interface itself cannot be instantiated.
    with pytest.raises(TypeError):
        Downloader()  # pylint: disable=abstract-class-instantiated


def test_subclass_must_declare_source():
    with pytest.raises(TypeError):
        class BadDownloader(Downloader):  # missing `source`  # pylint: disable=unused-variable
            def resolve(self, url):
                return url


def test_direct_sources_resolve_passthrough():
    # YouTube / SoundCloud hand the URL straight to yt-dlp.
    url = "https://soundcloud.com/artist/track"
    assert SoundcloudDownloader().resolve(url) == url
    assert YoutubeDownloader().resolve("https://youtu.be/abc") == "https://youtu.be/abc"


def test_translate_drm_error_is_source_aware():
    dl = SoundcloudDownloader()
    exc = YtdlpDownloadError("ERROR: [soundcloud] 123: This video is DRM protected")
    friendly = dl._translate_error(exc, "https://soundcloud.com/a/b")
    assert isinstance(friendly, DownloadUnavailableError)
    msg = str(friendly)
    assert "SoundCloud" in msg and "DRM" in msg
    assert "video" not in msg  # audio app: never call it a "video"


def test_failure_explanation_is_polymorphic():
    # Each subclass explains its own signature failure mode differently.
    yt = YoutubeDownloader()._explain_failure("Private video. Sign in", "u")
    assert "private" in yt.lower()

    sc = SoundcloudDownloader()._explain_failure("This video is DRM protected", "u")
    assert "DRM" in sc and "encrypted" in sc

    sp = SpotifyDownloader()._explain_failure("Unable to download webpage", "u")
    assert "Spotify" in sp and "YouTube" in sp


def test_spotify_select_result_unwraps_search_playlist():
    dl = SpotifyDownloader()
    info = {"_type": "playlist", "entries": [{"title": "match", "abr": 256}]}
    assert dl._select_result(info, "u")["title"] == "match"
    with pytest.raises(DownloadUnavailableError):
        dl._select_result({"_type": "playlist", "entries": []}, "u")
