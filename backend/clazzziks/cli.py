"""CLAZZZIKS command-line interface.

Examples:
    clazzziks https://youtu.be/dQw4w9WgXcQ
    clazzziks https://youtu.be/dQw4w9WgXcQ -f wav -o ./out
    clazzziks --batch links.txt -f flac -o ./out
    clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .formats import (
    AudioFormat,
    SUPPORTED_FORMATS,
    DEFAULT_MP3_BITRATE,
    BUNDLE_FORMAT,
)
from .downloader import download_audio, DownloadResult, DownloadUnavailableError
from .inputs import collect_urls, _GOOGLE_SHEETS_RE
from .logging_config import configure_logging

_console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clazzziks",
        description="Download audio from YouTube and SoundCloud.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="A single link, or (with --batch) a list/file/Google Sheet of links.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Treat input as many links and download each one.",
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
        default="tracks",
        help="Output directory (default: tracks/).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Emit structured logs to stderr (-v: info, -vv: debug).",
    )
    return parser


def _log_level(verbose: int) -> str | None:
    """Pick a log level from -v count, unless CLAZZZIKS_LOG_LEVEL overrides it."""
    if os.getenv("CLAZZZIKS_LOG_LEVEL"):
        return None  # let configure_logging honor the env var
    if verbose >= 2:
        return "DEBUG"
    if verbose == 1:
        return "INFO"
    return "WARNING"  # quiet by default so logs don't clutter normal CLI output


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(level=_log_level(args.verbose))

    if not args.input:
        _console.print("[red]error:[/] no link(s) provided. See --help.")
        return 2

    try:
        urls = collect_urls(args.input)
    except ValueError as exc:
        _console.print(f"[red]error:[/] {exc}")
        return 1

    if not urls:
        _console.print("[red]error:[/] no links found in the supplied input.")
        return 1

    is_sheet = bool(_GOOGLE_SHEETS_RE.match(args.input.strip()))
    if is_sheet:
        _console.print(f"[dim]Fetched {len(urls)} link(s) from spreadsheet.[/]")

    try:
        if args.batch or len(urls) > 1:
            return _run_batch(args, urls)
        return _run_single(args, urls[0])
    except KeyboardInterrupt:
        _console.print("\n[yellow]Aborted.[/]")
        return 130
    except Exception as exc:  # noqa: BLE001
        _console.print(f"[red]error:[/] {exc}")
        return 1


def _run_single(args, url: str) -> int:
    fmt = AudioFormat.parse(args.format) if args.format else AudioFormat.MP3

    started = time.perf_counter()
    try:
        with _console.status("[bold cyan]Downloading…[/]", spinner="dots"):
            result = download_audio(url, fmt=fmt, outdir=args.outdir, bitrate=args.bitrate)
    except DownloadUnavailableError as exc:
        _console.print(f"[red]✗  Unavailable:[/] {exc}")
        return 1
    elapsed = time.perf_counter() - started

    bitrate_tag = f"  {args.bitrate}kbps" if result.fmt is AudioFormat.MP3 else ""
    lines = [
        f"[bold green]✓[/]  [bold]{result.title}[/]",
        f"    [dim]Source[/]  {result.source}",
        f"    [dim]Format[/]  {result.fmt.value.upper()}{bitrate_tag}",
        f"    [dim]Time[/]    {elapsed:.1f}s",
        f"    [dim]Path[/]    {result.path}",
    ]
    for w in result.warnings:
        lines.append(f"    [yellow]⚠  {w}[/]")

    _console.print(Panel("\n".join(lines), title="[bold hot_pink]CLAZZZIKS[/]", expand=False))
    # Plain path to stdout for scripting (e.g. piping to another tool).
    print(str(result.path))
    return 0


_BATCH_WORKERS = 4


def _run_batch(args, urls: list[str]) -> int:
    fmt = AudioFormat.parse(args.format) if args.format else BUNDLE_FORMAT
    max_workers = min(_BATCH_WORKERS, len(urls))

    items: list[DownloadResult] = []
    failures: list[tuple[str, str]] = []
    all_warnings: list[str] = []
    started = time.perf_counter()
    _lock = threading.Lock()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=_console,
    ) as progress:
        overall = progress.add_task(
            f"[cyan]Downloading  [dim](×{max_workers} parallel)[/]",
            total=len(urls),
        )

        def _dl(url: str) -> None:
            short = url if len(url) <= 60 else url[:57] + "…"
            slot = progress.add_task(f"  [dim]↳ {short}[/]", total=None)
            try:
                result = download_audio(url, fmt=fmt, outdir=args.outdir, bitrate=args.bitrate)
                with _lock:
                    items.append(result)
                    all_warnings.extend(f"{result.title}: {w}" for w in result.warnings)
            except DownloadUnavailableError as exc:
                with _lock:
                    failures.append((url, str(exc)))
            except Exception as exc:  # noqa: BLE001
                with _lock:
                    failures.append((url, str(exc)))
            finally:
                progress.remove_task(slot)
                progress.advance(overall)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(_dl, urls))

    elapsed = time.perf_counter() - started

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=False)
    table.add_column("", width=3)
    table.add_column("Title")
    table.add_column("Source", width=12)
    table.add_column("Path / Error")

    for r in items:
        table.add_row("[green]✓[/]", r.title, r.source, str(r.path))
    for url, err in failures:
        short = url if len(url) <= 55 else url[:52] + "…"
        table.add_row("[red]✗[/]", short, "—", f"[red]{err}[/]")

    _console.print(table)

    for w in all_warnings:
        _console.print(f"  [yellow]⚠  {w}[/]")

    _console.print(
        f"\n  [bold]Downloaded[/] {len(items)}/{len(urls)}  "
        f"[bold]Failed[/] {len(failures)}  "
        f"[bold]Format[/] {fmt.value.upper()}  "
        f"[bold]Time[/] {elapsed:.1f}s"
    )

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
