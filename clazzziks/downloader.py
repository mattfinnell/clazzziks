"""Core download + transcode logic built on yt-dlp and ffmpeg."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from .formats import (
    AudioFormat,
    DEFAULT_MP3_BITRATE,
    mp3_bitrate_warning,
    source_bitrate_warning,
)
from .sources import detect_source, resolve


@dataclass
class DownloadResult:
    path: Path
    title: str
    source: str
    fmt: AudioFormat
    warnings: list[str] = field(default_factory=list)


def _ydl_options(fmt: AudioFormat, outdir: Path, bitrate: int) -> dict:
    postprocessor = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": fmt.value,
    }
    if fmt is AudioFormat.MP3:
        # yt-dlp interprets preferredquality as a kbps target for lossy codecs.
        postprocessor["preferredquality"] = str(bitrate)

    return {
        "format": "bestaudio/best",
        "outtmpl": str(outdir / "%(title)s [%(id)s].%(ext)s"),
        "postprocessors": [postprocessor],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "restrictfilenames": False,
    }


def download_audio(
    url: str,
    fmt: AudioFormat | str = AudioFormat.MP3,
    outdir: str | os.PathLike = ".",
    bitrate: int = DEFAULT_MP3_BITRATE,
) -> DownloadResult:
    """Download the audio at ``url`` and transcode it to ``fmt``.

    Returns a :class:`DownloadResult` pointing at the written file plus any
    quality warnings (e.g. sub-320kbps MP3).
    """
    fmt = fmt if isinstance(fmt, AudioFormat) else AudioFormat.parse(fmt)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    if (w := mp3_bitrate_warning(bitrate)) and fmt is AudioFormat.MP3:
        warnings.append(w)

    source = detect_source(url)
    target = resolve(url)

    with yt_dlp.YoutubeDL(_ydl_options(fmt, outdir, bitrate)) as ydl:
        info = ydl.extract_info(target, download=True)

    # A search query (Spotify path) yields a playlist-shaped result; unwrap it.
    if info.get("_type") == "playlist" or "entries" in info:
        entries = [e for e in info.get("entries", []) if e]
        if not entries:
            raise RuntimeError(f"No downloadable audio found for {url!r}.")
        info = entries[0]

    if (w := source_bitrate_warning(fmt, info.get("abr"))):
        warnings.append(w)

    path = _resolve_output_path(ydl, info, fmt, outdir)

    return DownloadResult(
        path=path,
        title=info.get("title", "audio"),
        source=source.value,
        fmt=fmt,
        warnings=warnings,
    )


def _resolve_output_path(
    ydl: "yt_dlp.YoutubeDL", info: dict, fmt: AudioFormat, outdir: Path
) -> Path:
    """Determine the final transcoded file path yt-dlp produced."""
    base = Path(ydl.prepare_filename(info))
    candidate = base.with_suffix(f".{fmt.value}")
    if candidate.exists():
        return candidate

    # Fall back to matching by id if the template/extension diverged.
    stem = base.stem
    matches = sorted(outdir.glob(f"{stem}.*"))
    audio = [m for m in matches if m.suffix.lstrip(".") == fmt.value]
    if audio:
        return audio[0]
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"Download completed but no output file was found for {info.get('title')!r}."
    )
