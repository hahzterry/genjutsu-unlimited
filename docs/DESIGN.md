# Design — higgsfield-genjutsu-unlimited

## Architecture (text diagram)

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  Frontend (Next.js / Vercel) │        │  Backend (FastAPI / Render)   │
│                             │        │                              │
│  UploadZone ─┐              │  POST  │  /generate ──► WORK_QUEUE     │
│  Prompt      │  /api/gen    │ ─────► │                  │           │
│  Generate btn┘              │        │                  ▼           │
│  ProgressBar ◄── SSE ◄─────┼────────┤  worker pool (N) │           │
│  LogPanel    ◄── SSE ◄─────┼────────┤   │              │           │
│  VideoPlayer◄── /video ────┼────────┤   ▼              ▼           │
│  History     │              │        │ HiggsfieldCreator            │
└─────────────────────────────┘        │   ├─ TempMail (1secmail)     │
                                       │   ├─ Playwright (undetected)  │
                                       │   └─ SQLite (accounts.db)   │
                                       └──────────────────────────────┘
                                                  │
                                                  ▼
                                       ┌────────────────────┐
                                       │  higgsfield.ai     │
                                       │  (proxied, headless)│
                                       └────────────────────┘
```

## Component Responsibilities

### Frontend (`frontend/`)
- `app/page.tsx` — main UI, orchestrates upload → POST → SSE → video.
- `app/api/generate/route.ts` — proxies multipart upload to backend.
- `components/*` — presentational: UploadZone, ProgressBar, LogPanel, VideoPlayer, History.
- `lib/utils.ts` — `cn()` (shadcn-style), `ts()`, `humanSize()`.

### Backend (`backend/`)
- `main.py` — FastAPI app, `/generate`, `/jobs/{id}/stream` (SSE), `/jobs/{id}/video`,
  worker pool with `asyncio.Queue`.
- `creator.py` — `HiggsfieldCreator`: full pipeline with 3 retries, proxy rotation,
  human delays, robust multi-fallback selectors, `page.expect_download()`.
- `temp_mail.py` — async 1secmail client with inbox polling + link extraction.
- `database.py` — aiosqlite account store (save / get-with-credits / mark-used).

## Data Flow (per generation, post-bugfix)

1. User drops file + prompt → `POST /api/generate` → backend `POST /generate`.
2. Backend saves reference, creates `Job`, enqueues `WORK_QUEUE`.
3. Worker picks job → `HiggsfieldCreator.run()` (wrapped in 5-min `asyncio.wait_for`):
   a. `get_account_with_credits()` → reuse active account (with its bound proxy) **or** create fresh.
   b. If fresh: `TempMail.create()` → signup → `wait_for_link` (async awaited log) → verify →
      `save_account(email, password, proxy=...)` — proxy bound at creation (Gap G).
   c. `_login()` → fill creds → submit → verify URL left `/login`; if reused account fails →
      `mark_banned()` so it's never retried (Bug B).
   d. `_run_genjutsu()` → goto `/create` (HTTP-status 404 check, Bug C) → scoped settings selectors
      (Bug D) → Model=Genjutsu, Quality=720p, Use free gens=ON → upload → prompt → Generate → wait.
   e. **`mark_used(email, 0)` fires here** — right after generation succeeds, BEFORE download (Bug A).
      No credit leak if the download then fails.
   f. `_download_result()` → `page.expect_download()` or `page.request.get(<video src>)` (cookie jar).
4. Worker emits `progress` + `log` SSE events throughout; final `done` event carries filename.
5. Frontend `EventSource` updates ProgressBar / LogPanel; on `done` sets VideoPlayer src
   to `/jobs/{id}/video` and writes History entry to localStorage.

### Failure-Handling Flow (new)

```
  create account ──► login ──► generate ──► mark_used(credits=0) ──► download ──► done
      │                │           │                                   │
      │                │           │                                   └─ fail → retry (credit already 0, no leak)
      │                │           └─ fail → retry (credit NOT yet consumed)
      │                └─ fail (reused) → mark_banned → retry creates fresh account
      └─ fail → retry (fresh attempt)
```

- **Overall timeout**: 5 minutes via `asyncio.wait_for` on the whole retry loop (Gap F).
- **Proxy binding**: stored in `accounts.proxy` column, reused on every login for that account (Gap G).
- **Account statuses**: `active` → `banned` (login failed) | `exhausted` (credits=0).

## Anti-Detection Strategy
- `undetected-playwright` chromium build (patches CDP leaks).
- Per-attempt proxy rotation from `PROXY_LIST` (residential socks5 recommended).
- Fingerprint spoof via `add_init_script`: `navigator.webdriver=undefined`,
  fixed `languages`, fake `plugins`.
- Random human delays 500–2000ms between actions.
- Realistic viewport (1440×900) + desktop UA.

## Flaw Mitigation

| Risk | Mitigation |
|---|---|
| 1secmail down / rate-limited | `TempMail` interface is swappable; drop in mail.tm by changing `API`/`DOMAINS`. |
| Higgsfield adds captcha | Detect captcha element → emit `error` event with screenshot path; operator solves manually or plugs 2captcha. |
| Selectors change | Every interaction uses 3–5 fallback selectors (text/placeholder/role/css). |
| Download button missing | Fallback to fetching `<video src>` via httpx. |
| Proxy banned mid-run | Retry picks a new proxy from `PROXY_LIST`. New accounts bind their proxy at creation and reuse it on every login (Gap G fix). |
| Job store lost on restart | v1 in-memory; v2 move to Redis. Reference file persists in `uploads/`. |
| Email verification link expired | Fresh account created on next attempt. |
| Concurrent account creation race | Each worker has its own `TempMail` instance; no shared state. |
| Credit leak on download failure (Bug A) | `mark_used()` fires right after generation succeeds, before download. Download failure no longer leaves a stale `credits=1` account. |
| Dead account retried in loop (Bug B) | Login failure on a reused account calls `mark_banned()`; `get_account_with_credits()` only returns `status='active'`. |
| Fragile 404 detection (Bug C) | `/create` fallback now checks HTTP `response.status >= 400` instead of title text. |
| Loose settings selectors (Bug D) | All Model/Quality/Toggle selectors scoped to a `[role="dialog"]` / `.settings-panel` container first. |
| Fire-and-forget logging (Bug E) | `TempMail.wait_for_link` log callback is now `Callable[[str], Awaitable[None]]` and properly awaited. |
| No overall timeout (Gap F) | `run()` wraps the entire retry loop in `asyncio.wait_for(..., timeout=300)`. |

## Security Audit (v2.0)

### Mitigated
| Risk | Mitigation |
|---|---|
| Path traversal in filenames | Backend uses `jid` (UUID hex) as filename prefix, never user-supplied names. `_safe_filename()` available if needed. |
| Malicious file types | `ALLOWED_VIDEO_TYPES` + `ALLOWED_IMAGE_TYPES` whitelist enforced in `main.py`. Frontend `accept` attributes match. |
| Oversized uploads | `MAX_VIDEO_SIZE=100MB`, `MAX_IMAGE_SIZE=20MB`, `MAX_IMAGES=30` enforced server-side. |
| Video duration abuse | ffprobe duration check in `main.py` (4–30s). Frontend also validates via `<video>` element. Defense in depth. |
| Secret leakage | `.env.local` (contains Vercel OIDC token) is gitignored via `frontend/.gitignore` `.env*`. Not in repo. |
| CORS wildcard | Production `CORS_ORIGINS` set to specific Vercel URLs on Railway. Default `*` only for local dev. |
| SSRF via proxy | Proxy is set via `PROXY_LIST` env var, not user input. No user-controlled outbound URLs. |
| Credit leak (Bug A) | `mark_used()` fires before download — fixed in v2.0. |
| Banned account retry (Bug B) | `mark_banned()` + `status='active'` filter — fixed in v2.0. |

### Known gaps (acceptable for self-hosted, fix before public deploy)
1. **No auth on backend** — anyone with the Railway URL can POST `/generate` and start jobs. Fix: add `API_KEY` env var, check `X-API-Key` header in middleware.
2. **No rate limiting** — a single client can spawn unlimited jobs and exhaust Railway hours / create thousands of Higgsfield accounts. Fix: add `slowapi` or a simple per-IP counter.
3. **In-memory `JOBS` dict grows unboundedly** — no eviction of completed jobs. Long-running instance will leak memory. Fix: add TTL cleanup (delete jobs older than 1 hour) or move to Redis.
4. **`desktop/main.py` still uses old single-file upload** — not updated for the new dual-upload flow. Needs sync if used.
5. **No HTTPS on backend-to-Higgsfield proxy** — proxy is `socks5://` (no TLS). Higgsfield credentials traverse the proxy in cleartext. Fix: use `socks5h://` with TLS or a VPN tunnel.

## Deployment

### Frontend → Vercel
1. `cd frontend && npm install`
2. `vercel link` → pick/create project `higgsfield-genjutsu-unlimited`.
3. Env var: `NEXT_PUBLIC_BACKEND_URL=https://<your-backend>.onrender.com`
4. `vercel deploy --prod`

### Backend → Render
1. New Web Service → connect `SabauAlexandru-py/higgsfield-genjutsu-unlimited`.
2. Root Directory: `backend`.
3. Build: `pip install -r requirements.txt && python -m playwright install --with-deps chromium`
4. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Env: `PROXY_LIST`, `HEADLESS=true`, `CORS_ORIGINS=<vercel-url>`, `VIDEO_DIR=/tmp/videos`.

### Backend → Railway (alternative)
1. New Project → Deploy from GitHub → pick repo.
2. Root Directory: `backend`.
3. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Variables: same as Render.

## Local Dev
```bash
cd backend && pip install -r requirements.txt
python -m playwright install chromium
uvicorn main:app --reload            # :8000
cd ../frontend && npm install
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 npm run dev   # :3000
```
