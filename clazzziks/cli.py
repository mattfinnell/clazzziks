"""CLAZZZIKS command-line interface.

Examples:
    clazzziks https://youtu.be/dQw4w9WgXcQ
    clazzziks https://youtu.be/dQw4w9WgXcQ -f wav -o ./out
    clazzziks --batch links.txt -f flac -o ./out
    clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
"""

from __future__ import annotations

import argparse
import sys

from .formats import (
    AudioFormat,
    SUPPORTED_FORMATS,
    DEFAULT_MP3_BITRATE,
    BUNDLE_FORMAT,
)
from .downloader import download_audio
from .bundle import download_bundle
from .inputs import collect_urls


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clazzziks",
        description="Download audio from YouTube, SoundCloud and Spotify.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="A single link, or (with --batch) a list/file/Google Sheet of links.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Treat input as many links and produce a single ZIP bundle.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=SUPPORTED_FORMATS,
        help=f"Audio format (default: mp3 single / {BUNDLE_FORMAT.value} batch).",
    )
    parser.add_argument(
        "-b",
        "--bitrate",
        type=int,
        default=DEFAULT_MP3_BITRATE,
        help=f"MP3 bitrate in kbps (default: {DEFAULT_MP3_BITRATE}).",
    )
    parser.add_argument(
        "-o",
        "--outdir",
        default=".",
        help="Output directory (default: current directory).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input:
        print("error: no link(s) provided. See --help.", file=sys.stderr)
        return 2

    try:
        if args.batch:
            return _run_batch(args)
        return _run_single(args)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level user-facing error
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run_single(args) -> int:
    fmt = AudioFormat.parse(args.format) if args.format else AudioFormat.MP3
    result = download_audio(
        args.input, fmt=fmt, outdir=args.outdir, bitrate=args.bitrate
    )
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"Downloaded [{result.source}] {result.title}")
    print(f"  -> {result.path}")
    return 0


def _run_batch(args) -> int:
    fmt = AudioFormat.parse(args.format) if args.format else BUNDLE_FORMAT
    urls = collect_urls(args.input)
    if not urls:
        print("error: no links found in the supplied input.", file=sys.stderr)
        return 1

    print(f"Found {len(urls)} link(s). Downloading as {fmt.value}...")
    result = download_bundle(urls, fmt=fmt, outdir=args.outdir, bitrate=args.bitrate)

    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for url, err in result.failures:
        print(f"failed: {url}: {err}", file=sys.stderr)

    print(f"Bundled {len(result.items)} file(s) -> {result.path}")
    if result.failures:
        print(f"  ({len(result.failures)} link(s) failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
