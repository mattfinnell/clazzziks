FROM mcr.microsoft.com/devcontainers/python:3.13-bullseye

RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    yt-dlp \
    mutagen \
    requests \
    Pillow

RUN curl -LsSf https://astral.sh/uv/install.sh | env HOME=/home/vscode sh && \
    ln -s /home/vscode/.local/bin/uv /usr/local/bin/uv && \
    ln -s /home/vscode/.local/bin/uvx /usr/local/bin/uvx && \
    chown -R vscode:vscode /home/vscode/.local
