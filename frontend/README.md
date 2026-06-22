# CLAZZZIKS frontend

React + Vite web utility for the CLAZZZIKS audio downloader. Built with
React, TypeScript and SCSS. Talks to the Python backend exclusively through `/api`.

```bash
pnpm install
pnpm dev       # http://localhost:5173 (proxies /api -> http://localhost:5000)
pnpm build     # static bundle -> dist/
pnpm preview   # serve the production build locally
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `VITE_API_TARGET` | `http://localhost:5000` | Backend the Vite dev server proxies `/api` to |
| `VITE_API_BASE` | `/api` | API base path used by the browser client at runtime; set to a full URL to call a backend on a different origin (CORS is enabled server-side) |

```bash
# Point the dev proxy at a remote backend
VITE_API_TARGET=http://staging-alb.example.com npm run dev

# Call a different-origin API in the built app
VITE_API_BASE=http://staging-alb.example.com/api npm run build
```

## Source files

- `src/api.js` — backend client (`fetchConfig`, `fetchContract`, `requestDownload`,
  `saveBlob`). Parses `X-Clazzziks-Warnings` from response headers and triggers
  a browser file-save on download.
- `src/App.jsx` — the UI: link textarea, format/bitrate selectors,
  single-vs-bundle detection, backend health indicator, warning display.

## Production build (for AWS deploy)

The CDK stack (`infra/`) bundles `frontend/dist/` into S3 during `cdk deploy`.
Build the frontend before deploying:

```bash
cd frontend && npm install && npm run build
cd ../infra  && npx cdk deploy Staging/Clazzziks
```

The built app calls `/api/*` using relative paths, which CloudFront routes to
the ALB — no per-environment API URL configuration is needed.
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