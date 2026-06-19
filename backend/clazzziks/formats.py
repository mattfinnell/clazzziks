"""Tolerable audio formats and quality rules.

Spec:
    - WAV
    - MP3 (320kbps or higher, warn if less)
    - FLAC
"""

from __future__ import annotations

from enum import Enum

# Anything below this for MP3 should produce a warning (per spec / CLAUDE.md).
DEFAULT_MP3_BITRATE = 320
MIN_RECOMMENDED_MP3_BITRATE = 320


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"
    FLAC = "flac"

    @property
    def lossless(self) -> bool:
        return self in (AudioFormat.WAV, AudioFormat.FLAC)

    @classmethod
    def parse(cls, value: str) -> "AudioFormat":
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            allowed = ", ".join(f.value for f in cls)
            raise ValueError(
                f"Unsupported format {value!r}. Tolerable formats: {allowed}."
            ) from exc


SUPPORTED_FORMATS = [f.value for f in AudioFormat]

# The lossless format used for batch "lossless-compression bundles".
BUNDLE_FORMAT = AudioFormat.FLAC


def mp3_bitrate_warning(bitrate: int) -> str | None:
    """Return a warning string if an MP3 bitrate is below the recommended floor."""
    if bitrate < MIN_RECOMMENDED_MP3_BITRATE:
        return (
            f"Requested MP3 bitrate {bitrate}kbps is below the recommended "
            f"{MIN_RECOMMENDED_MP3_BITRATE}kbps minimum."
        )
    return None


def source_bitrate_warning(fmt: AudioFormat, source_abr: float | None) -> str | None:
    """Warn when the source's real audio bitrate can't satisfy a 320kbps MP3.

    Re-encoding a low-bitrate source up to 320kbps does not recover quality, so we
    surface the true ceiling reported by the source.
    """
    if fmt is not AudioFormat.MP3 or source_abr is None:
        return None
    if source_abr < MIN_RECOMMENDED_MP3_BITRATE:
        return (
            f"Source audio is only ~{round(source_abr)}kbps; encoding to "
            f"{MIN_RECOMMENDED_MP3_BITRATE}kbps MP3 will not improve real quality."
        )
    return None
