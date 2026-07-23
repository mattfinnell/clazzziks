"""Batch downloads bundled into a single lossless-compression (ZIP) archive."""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .downloader import download_audio, DownloadResult
from .formats import AudioFormat, BUNDLE_FORMAT, DEFAULT_MP3_BITRATE
from .logging_config import log_event

logger = logging.getLogger(__name__)


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

    Bundles default to MP3 (``BUNDLE_FORMAT``) — lossless formats produced ZIPs
    that were far too large. Individual failures are collected rather than
    aborting the whole batch.
    """
    fmt = fmt if isinstance(fmt, AudioFormat) else AudioFormat.parse(fmt)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bundle_path = outdir / bundle_name

    items: list[DownloadResult] = []
    failures: list[tuple[str, str]] = []
    warnings: list[str] = []

    log_event(
        logger,
        logging.INFO,
        "bundle.start",
        count=len(urls),
        format=fmt.value
    )

    with tempfile.TemporaryDirectory(prefix="clazzziks_") as tmp:
        for url in urls:
            try:
                result = download_audio(url, fmt=fmt, outdir=tmp, bitrate=bitrate)
                items.append(result)
                warnings.extend(f"{result.title}: {w}" for w in result.warnings)

            except Exception as exc:  # noqa: BLE001 - record and continue the batch
                failures.append((url, str(exc)))
                log_event(
                    logger,
                    logging.WARNING,
                    "bundle.item_failed",
                    url=url,
                    error=str(exc),
                )

        if not items:
            log_event(
                logger,
                logging.ERROR,
                "bundle.empty",
                count=len(urls),
                failures=len(failures),
            )

            raise RuntimeError(
                "No audio could be downloaded from the supplied links. "
                + ("; ".join(f"{u}: {e}" for u, e in failures) if failures else "")
            )

        _write_zip(bundle_path, items)

    log_event(
        logger,
        logging.INFO,
        "bundle.complete",
        items=len(items),
        failures=len(failures),
        path=str(bundle_path),
    )

    return BundleResult(
        path=bundle_path, items=items, failures=failures, warnings=warnings
    )


def write_zip(bundle_path: Path, items: list[DownloadResult]) -> None:
    """Pack downloaded tracks into a ZIP, de-duplicating collided filenames.

    Public so the async job runner (:mod:`clazzziks.jobs`) can reuse the exact
    bundling the sequential :func:`download_bundle` uses.
    """
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        used: set[str] = set()
        for item in items:
            arcname = _unique_arcname(item.path.name, used)
            zf.write(item.path, arcname=arcname)


# Backwards-compatible internal alias (the sequential bundler calls this).
_write_zip = write_zip


def _unique_arcname(name: str, used: set[str]) -> str:
    candidate = name
    stem, dot, ext = name.rpartition(".")
    n = 1
    while candidate in used:
        candidate = f"{stem} ({n}){dot}{ext}" if dot else f"{name} ({n})"
        n += 1
    used.add(candidate)

    return candidate
