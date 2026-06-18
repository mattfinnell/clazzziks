# CLAZZZIKS

Audio downloader for **YouTube**, **SoundCloud**, and **Spotify**. Outputs
**WAV**, **MP3** (320kbps default, warns if lower), or **FLAC** — via a web UI,
a CLI, or a small HTTP API.

## How it works

- **YouTube / SoundCloud** are downloaded directly with [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
  and transcoded with `ffmpeg`.
- **Spotify** streams are DRM-protected and cannot be downloaded. CLAZZZIKS reads
  the track's public metadata and finds the matching recording on YouTube (the
  same approach `spotdl` uses).

## Requirements

- Python 3.10+
- `ffmpeg` on your `PATH`

```bash
pip install -r requirements.txt   # or: pip install -e .
```

## CLI

```bash
# Single link -> one audio file
python -m clazzziks "https://youtu.be/<id>"                 # MP3 320 by default
python -m clazzziks "https://youtu.be/<id>" -f wav -o ./out

# Many links -> one lossless (FLAC) ZIP bundle
python -m clazzziks --batch links.txt -f flac -o ./out
python -m clazzziks --batch "https://docs.google.com/spreadsheets/d/<id>/edit"
```

Batch input accepts a text file (one URL per line), a CSV file, inline text, or
a **public** Google Sheets URL. After `pip install -e .` the `clazzziks` and
`clazzziks-web` commands are available directly.

## Web interface

```bash
python -m clazzziks.web --host 0.0.0.0 --port 5000
# then open http://localhost:5000
```

Paste one link for a single file, or many links for a ZIP bundle. Quality
warnings are returned in the `X-Clazzziks-Warnings` response header.

## HTTP API

```
POST /download    form/JSON: { links, format?, bitrate? }
                  -> audio file (1 link) or application/zip bundle (many)
GET  /health      -> {"status":"ok"}
```

```bash
curl -X POST localhost:5000/download \
  -d 'links=https://youtu.be/<id>' -d 'format=mp3' -OJ
```

## Formats & quality

| Format | Lossless | Notes                              |
|--------|----------|------------------------------------|
| WAV    | yes      | uncompressed                       |
| FLAC   | yes      | default for bundles                |
| MP3    | no       | 320kbps default; warns below 320   |

MP3 requests below 320kbps, and sources whose real bitrate can't reach 320kbps,
produce warnings (CLI stderr / API response header).

## Tests

```bash
python -m pytest        # offline unit tests (formats, source detection, input parsing)
```
