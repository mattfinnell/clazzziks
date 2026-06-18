"""Batch downloads bundled into a single lossless-compression (ZIP) archive."""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .downloader import download_audio, DownloadResult
from .formats import AudioFormat, BUNDLE_FORMAT, DEFAULT_MP3_BITRATE


@dataclass
class BundleResult:
    path: Path
    items: list[DownloadResult] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)  # (url, error)
    warnings: list[str] = field(default_factory=list)


def download_bundle(
    urls: list[str],
    fmt: AudioFormat | str = BUNDLE_FORMAT,
    outdir: str | os.PathLike = ".",
    bitrate: int = DEFAULT_MP3_BITRATE,
    bundle_name: str = "clazzziks_bundle.zip",
) -> BundleResult:
    """Download every URL, transcode to ``fmt`` and pack them into one ZIP.

    The ZIP itself is lossless compression; using a lossless audio format
    (FLAC/WAV) keeps the whole bundle lossless end to end. Individual failures
    are collected rather than aborting the whole batch.
    """
    fmt = fmt if isinstance(fmt, AudioFormat) else AudioFormat.parse(fmt)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bundle_path = outdir / bundle_name

    items: list[DownloadResult] = []
    failures: list[tuple[str, str]] = []
    warnings: list[str] = []

    if not fmt.lossless:
        warnings.append(
            f"Bundle format {fmt.value!r} is lossy; spec recommends a lossless "
            f"format (FLAC/WAV) for bundles."
        )

    with tempfile.TemporaryDirectory(prefix="clazzziks_") as tmp:
        for url in urls:
            try:
                result = download_audio(url, fmt=fmt, outdir=tmp, bitrate=bitrate)
                items.append(result)
                warnings.extend(f"{result.title}: {w}" for w in result.warnings)
            except Exception as exc:  # noqa: BLE001 - record and continue the batch
                failures.append((url, str(exc)))

        if not items:
            raise RuntimeError(
                "No audio could be downloaded from the supplied links. "
                + ("; ".join(f"{u}: {e}" for u, e in failures) if failures else "")
            )

        _write_zip(bundle_path, items)

    return BundleResult(
        path=bundle_path, items=items, failures=failures, warnings=warnings
    )


def _write_zip(bundle_path: Path, items: list[DownloadResult]) -> None:
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        used: set[str] = set()
        for item in items:
            arcname = _unique_arcname(item.path.name, used)
            zf.write(item.path, arcname=arcname)


def _unique_arcname(name: str, used: set[str]) -> str:
    candidate = name
    stem, dot, ext = name.rpartition(".")
    n = 1
    while candidate in used:
        candidate = f"{stem} ({n}){dot}{ext}" if dot else f"{name} ({n})"
        n += 1
    used.add(candidate)
    return candidate
