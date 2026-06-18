# CLAZZZIKS frontend

React + Vite web utility for the CLAZZZIKS audio downloader. It talks to the
Python backend exclusively through `/api`.

```bash
npm install
npm run dev       # http://localhost:5173 (proxies /api -> http://localhost:5000)
npm run build     # static bundle -> dist/
npm run preview   # serve the production build locally
```

Environment overrides:

- `VITE_API_TARGET` — backend the dev server proxies `/api` to (default `http://localhost:5000`).
- `VITE_API_BASE` — API base path used by the client (default `/api`); set to a full
  URL to call a backend on another origin directly (CORS is enabled server-side).

Source:

- `src/api.js` — backend client (`fetchConfig`, `requestDownload`, `saveBlob`).
- `src/App.jsx` — the UI (link input, format/bitrate, single-vs-bundle, warnings).
