"""Parse collections of links from lists, text/CSV files, and Google Sheets."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

from .sources import looks_like_url

_GOOGLE_SHEETS_RE = re.compile(
    r"https?://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)"
)


def collect_urls(source: str | list[str], *, timeout: float = 30.0) -> list[str]:
    """Normalize many possible inputs into a de-duplicated list of URLs.

    Accepts:
        - a Python list of strings
        - a Google Sheets URL (fetched and parsed as CSV)
        - a path to a .csv or .txt file
        - raw text containing one-or-more URLs (newline / comma / whitespace separated)
    """
    if isinstance(source, list):
        return _dedupe(_extract_from_lines(source))

    text = source.strip()

    if _GOOGLE_SHEETS_RE.match(text):
        return _dedupe(_from_google_sheet(text, timeout=timeout))

    path = Path(text)
    if path.exists() and path.is_file():
        return _dedupe(_from_file(path))

    # Otherwise treat the blob itself as inline text full of links.
    return _dedupe(_extract_from_text(text))


def _from_file(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".csv":
        return _extract_from_csv(raw)
    return _extract_from_text(raw)


def _from_google_sheet(url: str, *, timeout: float) -> list[str]:
    csv_url = _google_sheet_csv_url(url)
    try:
        resp = requests.get(csv_url, timeout=timeout, headers={"User-Agent": "clazzziks/0.1"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(
            f"Could not fetch Google Sheet as CSV ({csv_url!r}). "
            f"Make sure the sheet is shared as 'anyone with the link'. Error: {exc}"
        ) from exc
    return _parse_sheet_rows(resp.text)


# Keywords matched against lowercased header cell text to locate columns.
_URL_HEADER_HINTS = ("link", "url", "soundcloud", "youtube")
_SONG_HEADER_HINTS = ("song", "track", "title", "name")
_ARTIST_HEADER_HINTS = ("artist", "author", "by")


def _parse_sheet_rows(raw_csv: str) -> list[str]:
    """Parse a structured sheet CSV into a mix of URLs and yt-dlp search queries.

    Detects a header row (no cell looks like a URL) and maps columns to URL,
    Song, and Artist roles. Rows that have a URL use it directly. Rows with
    Song + Artist but no URL become a ``ytsearch1:`` query handled by
    YoutubeDownloader. Falls back to plain URL extraction when no header is
    recognised.
    """
    reader = list(csv.reader(io.StringIO(raw_csv)))
    if not reader:
        return []

    header = reader[0]
    if any(looks_like_url(cell.strip()) for cell in header):
        # No recognisable header row — fall back to extracting URLs from all cells.
        return _extract_from_csv(raw_csv)

    url_col = song_col = artist_col = -1
    for i, cell in enumerate(header):
        key = cell.strip().lower()
        if url_col < 0 and any(h in key for h in _URL_HEADER_HINTS):
            url_col = i
        elif song_col < 0 and any(h in key for h in _SONG_HEADER_HINTS):
            song_col = i
        elif artist_col < 0 and any(h in key for h in _ARTIST_HEADER_HINTS):
            artist_col = i

    def _cell(row: list[str], idx: int) -> str:
        return row[idx].strip() if 0 <= idx < len(row) else ""

    results: list[str] = []
    for row in reader[1:]:
        url = _cell(row, url_col)
        if looks_like_url(url):
            results.append(url)
            continue

        song = _cell(row, song_col)
        artist = _cell(row, artist_col)
        if song:
            query = f"{song} {artist}".strip()
            results.append(f"ytsearch1:{query} audio")

    return results


def _google_sheet_csv_url(url: str) -> str:
    match = _GOOGLE_SHEETS_RE.match(url)
    if not match:
        raise ValueError(f"Not a Google Sheets URL: {url!r}")
    doc_id = match.group(1)
    # Preserve a specific tab if a gid is present in the fragment or query.
    gid = None
    frag = urlparse(url).fragment
    if frag.startswith("gid="):
        gid = frag[len("gid="):]
    else:
        gid = (parse_qs(urlparse(url).query).get("gid") or [None])[0]
    base = f"https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv"
    return f"{base}&gid={gid}" if gid else base


def _extract_from_csv(raw: str) -> list[str]:
    urls: list[str] = []
    for row in csv.reader(io.StringIO(raw)):
        for cell in row:
            urls.extend(_extract_from_text(cell))
    return urls


def _extract_from_text(text: str) -> list[str]:
    tokens = re.split(r"[\s,;]+", text.strip())
    return [t for t in tokens if looks_like_url(t)]


def _extract_from_lines(lines: list[str]) -> list[str]:
    urls: list[str] = []
    for line in lines:
        urls.extend(_extract_from_text(str(line)))
    return urls


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
