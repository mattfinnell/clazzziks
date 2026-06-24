# CLAZZZIKS frontend

React + Vite web utility for the CLAZZZIKS audio downloader. Built with
React, TypeScript and SCSS. Talks to the Python backend exclusively through `/api`.

```bash
pnpm install
pnpm dev       # http://localhost:5173 (proxies /api -> http://localhost:5000)
pnpm build     # static bundle -> dist/
pnpm preview   # serve the production build locally
```

Environment overrides:

- `VITE_API_TARGET` — backend the dev server proxies `/api` to (default `http://localhost:5000`).
- `VITE_API_BASE` — API base path used by the client (default `/api`); set to a full
  URL to call a backend on another origin directly (CORS is enabled server-side).
- `VITE_FIREBASE_*` — Firebase web config (see `.env.example`). When set, the app
  gates behind Google sign-in and sends the user's ID token as a bearer token on
  `/api/download`. When **unset**, the app runs in open mode (no login), mirroring
  a backend that has no Firebase credentials.

## Authentication

Sign-in is handled by Firebase Auth. `src/firebase.ts` initialises the SDK from
`VITE_FIREBASE_*` env vars; `src/auth/AuthContext.tsx` exposes the current user and
registers a token getter with `src/api.ts` so requests carry
`Authorization: Bearer <token>`. `App.tsx` shows `components/Login.tsx` until the
user is signed in (only when Firebase is configured). Copy `.env.example` to
`.env.local` and fill in your Firebase web app config to enable it.

## Source layout

```
src/
├── main.tsx               entry point
├── App.tsx                shell — page state + TopNav
├── vite-env.d.ts          Vite/ImportMeta type shims
├── api.ts                 typed backend client (fetchConfig, requestDownload, saveBlob)
├── styles/
│   └── globals.scss       CSS custom properties + reset
├── components/
│   ├── TopNav.tsx         nav bar (Home / Download)
│   └── TopNav.scss
└── pages/
    ├── HelloWorld.tsx     landing page (no API calls)
    ├── HelloWorld.scss
    ├── Downloader.tsx     download UI (calls /api/formats + /api/download)
    └── Downloader.scss
```

## API contract

The backend and frontend share a single source of truth for the `/api` surface:
`backend/clazzziks/openapi.json` (OpenAPI 3.1), served live at
`/api/openapi.json` (`fetchContract()`). The request/response shapes in
`src/api.ts` follow it, and the backend validates its responses against it in
`backend/tests/test_contract.py` — so the two sides can't silently drift.