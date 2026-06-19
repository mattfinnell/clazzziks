"""End-to-end tests that hit real streaming services over the network.

Run with:  pytest -m e2e -v
Skip with: pytest -m "not e2e"   (the default CI run)

Tests cover the full decision tree: functional download, DRM rejection,
Spotify search-based resolution, and spreadsheet input (both the parsing
layer and an actual download from a URL-less sheet row).
"""

import pytest

from clazzziks.downloader import download_audio, DownloadUnavailableError, downloader_for
from clazzziks.inputs import collect_urls

_YT_FUNCTIONAL = "https://www.youtube.com/watch?v=ijo-otbV0Dw&list=RDIxFQ9aUAAJM&index=2"
_SC_FUNCTIONAL = "https://soundcloud.com/mattfinnell/lockyear"
_SC_DRM = "https://soundcloud.com/valante-music/ramo"
_SPOTIFY = "https://open.spotify.com/track/5NP0ZS263MTgqgiyEwe1Ei"
_SPREADSHEET = "https://docs.google.com/spreadsheets/d/1-6gWbrj5YGPcMN4Iah2t6LqyqUDPv3l5Ok-5TrNoHg8/edit?gid=0#gid=0"


# --- audio platform downloads -----------------------------------------------

@pytest.mark.e2e
def test_youtube_functional_downloads(tmp_path):
    result = download_audio(_YT_FUNCTIONAL, fmt="mp3", outdir=tmp_path)
    assert result.path.exists(), "expected output file to exist on disk"
    assert result.path.stat().st_size > 0


@pytest.mark.e2e
def test_soundcloud_functional_downloads(tmp_path):
    result = download_audio(_SC_FUNCTIONAL, fmt="mp3", outdir=tmp_path)
    assert result.path.exists(), "expected output file to exist on disk"
    assert result.path.stat().st_size > 0


@pytest.mark.e2e
def test_soundcloud_drm_raises_unavailable(tmp_path):
    with pytest.raises(DownloadUnavailableError):
        download_audio(_SC_DRM, fmt="mp3", outdir=tmp_path)


@pytest.mark.e2e
def test_spotify_downloads_via_search(tmp_path):
    result = download_audio(_SPOTIFY, fmt="mp3", outdir=tmp_path)
    assert result.path.exists(), "expected output file to exist on disk"
    assert result.path.stat().st_size > 0


# --- spreadsheet input ------------------------------------------------------

@pytest.mark.e2e
def test_spreadsheet_raw_url_unsupported_by_downloader():
    # The sheet URL itself is not an audio source — the Sheets integration lives
    # in collect_urls, not in the downloader dispatch layer.
    with pytest.raises(ValueError, match="Unsupported source"):
        downloader_for(_SPREADSHEET)


@pytest.mark.e2e
def test_spreadsheet_collect_urls_returns_urls_and_searches():
    try:
        results = collect_urls(_SPREADSHEET)
    except ValueError as exc:
        if "401" in str(exc) or "Unauthorized" in str(exc):
            pytest.skip("Sheet is not publicly shared — set sharing to 'anyone with the link' to run this test")
        raise
    assert len(results) > 0, "expected at least one entry from the sheet"
    direct = [r for r in results if r.startswith("http")]
    searches = [r for r in results if r.startswith("ytsearch1:")]
    assert direct, "expected at least one direct URL (rows with a link in col A)"
    assert searches, "expected at least one ytsearch query (rows without a URL)"


@pytest.mark.e2e
def test_spreadsheet_ytsearch_row_downloads(tmp_path):
    # 'Like this (Freaky mix)' by 'Levity x Nitti' is a URL-less row in the sheet.
    query = "ytsearch1:Like this (Freaky mix) Levity x Nitti audio"
    result = download_audio(query, fmt="mp3", outdir=tmp_path)
    assert result.path.exists(), "expected output file to exist on disk"
    assert result.path.stat().st_size > 0
