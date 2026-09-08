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

## Data Flow (per generation)

1. User drops file + prompt → `POST /api/generate` → backend `POST /generate`.
2. Backend saves reference, creates `Job`, enqueues `WORK_QUEUE`.
3. Worker picks job → `HiggsfieldCreator.run()`:
   a. `TempMail.create()` → temp inbox.
   b. `goto /signup` → fill email/password → submit.
   c. `TempMail.wait_for_link()` → `goto verification link`.
   d. `goto /login` → fill creds → submit.
   e. `goto /genjutsu` → `set_input_files(reference)` → fill prompt → click Generate.
   f. Wait for result `<video>` or download button.
   g. `page.expect_download()` → save mp4 (fallback: fetch `<video src>`).
4. Worker emits `progress` + `log` SSE events throughout; final `done` event carries filename.
5. Frontend `EventSource` updates ProgressBar / LogPanel; on `done` sets VideoPlayer src
   to `/jobs/{id}/video` and writes History entry to localStorage.

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
| Proxy banned mid-run | Retry picks a new proxy from `PROXY_LIST`. |
| Job store lost on restart | v1 in-memory; v2 move to Redis. Reference file persists in `uploads/`. |
| Email verification link expired | Fresh account created on next attempt. |
| Concurrent account creation race | Each worker has its own `TempMail` instance; no shared state. |

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
