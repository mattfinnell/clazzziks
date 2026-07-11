# CLAZZZIKS frontend

React + Vite web utility for the CLAZZZIKS audio downloader. Built with
React, TypeScript and SCSS. Talks to the Python backend over **GraphQL** (`/graphql`)
plus the `/files/:token` download stream (via `graphql-request` + `@tanstack/react-query`).

```bash
pnpm install
pnpm dev       # http://localhost:5173 (proxies /graphql + /files -> http://localhost:5000)
pnpm build     # static bundle -> dist/
pnpm preview   # serve the production build locally
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `VITE_API_TARGET` | `http://localhost:5000` | Backend the Vite dev server proxies `/graphql` + `/files` to |
| `VITE_API_BASE` | *(empty)* | API base prefix used by the browser client; empty = same-origin. Set to a full URL to call a backend on a different origin (CORS is enabled server-side) |

```bash
# Point the dev proxy at a remote backend (e.g. the staging Elastic IP)
VITE_API_TARGET=http://<elastic-ip> pnpm dev

# Call a different-origin API in the built app
VITE_API_BASE=http://<elastic-ip> pnpm build
```

## Source files

- `src/api.ts` — GraphQL backend client (`fetchConfig`, `fetchMe`, `listVips`,
  `listUsers`, `syncUsers`, `addVip`, `updateVip`, `removeVip`, `requestDownload`,
  `saveBlob`). `requestDownload` runs the `download` mutation, then streams the file
  from `/files/:token` and triggers a browser file-save.
- `src/pages/Downloader.tsx` — the download UI: link textarea, single-vs-bundle
  detection, backend health indicator, warning display.

## Production build (for AWS deploy)

The Pulumi stack (`infra/`) syncs `frontend/dist/` into S3 during `pulumi up`.
Build the frontend before deploying:

```bash
cd frontend && pnpm install && pnpm build
cd ../infra  && pulumi up -s staging
```

The built app calls `/graphql` and `/files/*` using relative paths, which CloudFront
routes to the EC2 Elastic IP origin — no per-environment API URL configuration is
needed. Environment overrides:

- `VITE_API_TARGET` — backend the dev server proxies `/graphql` + `/files` to (default `http://localhost:5000`).
- `VITE_API_BASE` — API base prefix used by the client (default empty = same-origin);
  set to a full URL to call a backend on another origin directly (CORS is enabled server-side).
- `VITE_FIREBASE_*` — Firebase web config (see `.env.example`). When set, the app
  gates behind Google sign-in and sends the user's ID token as a bearer token on the
  `download` mutation and admin operations. When **unset**, the app runs in open mode
  (no login), mirroring a backend that has no Firebase credentials.

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
├── api.ts                 GraphQL backend client (fetchConfig, requestDownload, saveBlob, …)
├── styles/
│   └── globals.scss       CSS custom properties + reset
├── components/
│   ├── TopNav.tsx         nav bar (Home / Download)
│   └── TopNav.scss
└── pages/
    ├── HelloWorld.tsx     landing page (no API calls)
    ├── HelloWorld.scss
    ├── Downloader.tsx     download UI (config query + download mutation)
    └── Downloader.scss
```

## API contract

The backend and frontend share a single source of truth for the GraphQL API: the
code-first schema in `backend/clazzziks/schema.py`, whose emitted SDL
`backend/clazzziks/schema.graphql` is the committed contract. The operations in
`src/api.ts` build against those exact types/fields (field names are snake_case —
`auto_camel_case` is disabled server-side), and `backend/tests/test_contract.py`
fails if the schema drifts from the committed SDL — so the two sides can't diverge.
