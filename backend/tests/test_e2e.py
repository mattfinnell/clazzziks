"""End-to-end tests that hit real streaming services over the network.

Run with:  pytest -m e2e -v
Skip with: pytest -m "not e2e"   (the default CI run)

Each test asserts on a specific URL from the project notes. The five cases
cover the full decision tree: functional download, DRM rejection, Spotify
search-based resolution, and an unsupported URL type.
"""

import pytest

from clazzziks.downloader import download_audio, DownloadUnavailableError, downloader_for

_YT_FUNCTIONAL = "https://www.youtube.com/watch?v=ijo-otbV0Dw&list=RDIxFQ9aUAAJM&index=2"
_SC_FUNCTIONAL = "https://soundcloud.com/mattfinnell/lockyear"
_SC_DRM = "https://soundcloud.com/valante-music/ramo"
_SPOTIFY = "https://open.spotify.com/track/5NP0ZS263MTgqgiyEwe1Ei"
_SPREADSHEET = "https://docs.google.com/spreadsheets/d/1-6gWbrj5YGPcMN4Iah2t6LqyqUDPv3l5Ok-5TrNoHg8/edit?gid=0#gid=0"


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


@pytest.mark.e2e
def test_spreadsheet_url_is_unsupported():
    with pytest.raises(ValueError, match="Unsupported source"):
        downloader_for(_SPREADSHEET)
