FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Editable install keeps __file__ at /clazzziks/backend/clazzziks/web.py so that
# Path(__file__).parents[2] resolves to /clazzziks/ and tracks/ lands at
# /clazzziks/tracks/ (ephemeral; each download is served immediately then GC'd).
WORKDIR /clazzziks
COPY backend/ ./backend/
RUN pip install --no-cache-dir -e ./backend/
RUN mkdir -p tracks

EXPOSE 8000
CMD ["uvicorn", "clazzziks.web:app", "--host", "0.0.0.0", "--port", "8000"]
