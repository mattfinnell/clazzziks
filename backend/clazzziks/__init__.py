"""CLAZZZIKS — audio downloader for YouTube and SoundCloud.

Public API:
    download_audio(url, fmt, outdir, bitrate)  -> DownloadResult
    download_bundle(urls, fmt, outdir)         -> BundleResult
"""

from .formats import AudioFormat, SUPPORTED_FORMATS, DEFAULT_MP3_BITRATE
from .downloader import (
    download_audio,
    downloader_for,
    DownloadResult,
    DownloadUnavailableError,
    Downloader,
    YoutubeDownloader,
    SoundcloudDownloader,
)
from .bundle import download_bundle, BundleResult

__all__ = [
    "AudioFormat",
    "SUPPORTED_FORMATS",
    "DEFAULT_MP3_BITRATE",
    "download_audio",
    "downloader_for",
    "DownloadResult",
    "DownloadUnavailableError",
    "Downloader",
    "YoutubeDownloader",
    "SoundcloudDownloader",
    "download_bundle",
    "BundleResult",
]

__version__ = "0.1.0"
