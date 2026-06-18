FROM mcr.microsoft.com/devcontainers/python:3.12-bullseye

RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    yt-dlp \
    mutagen \
    requests \
    Pillow
