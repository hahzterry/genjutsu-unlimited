# Higgsfield Genjutsu Unlimited — Full Project Summary

> Complete build record for `higgsfield-genjutsu-unlimited` — a tool that generates **unlimited free Higgsfield Genjutsu videos** by auto-creating a fresh verified account for every generation (each new account gets 1 free credit).

---

## 1. What It Does

A self-hosted, full-stack tool that automates the entire Higgsfield Genjutsu pipeline end-to-end:

1. You drop a reference image/video + write a cinematic prompt in a pixel-perfect clone of the Higgsfield Genjutsu UI.
2. The frontend POSTs the upload to a FastAPI backend.
3. A backend worker spins up a Playwright + Chromium browser that:
   - creates a temp email inbox (1secmail),
   - signs up on `higgsfield.ai` (name + email + password),
   - polls the inbox and opens the verification link in-browser,
   - logs in headless,
   - opens the **Create** interface,
   - selects **Model → "Higgsfield Genjutsu"**,
   - selects **Quality → "720p"**,
   - toggles **"Use free gens" → ON** (consumes the 1 free credit),
   - uploads your reference file,
   - fills the prompt,
   - clicks **Generate**,
   - waits for completion,
   - downloads the result video via `page.expect_download()` (fallback: `page.request` on `<video src>`),
   - returns the mp4.
4. Progress + timestamped logs stream back to the frontend over SSE; the final video is served at `/jobs/{id}/video`.
5. Each generation uses a brand-new account = a brand-new free credit = **unlimited free videos**.

---

## 2. Live Deployment Status (all green)

| Layer | Status | URL |
|---|---|---|
| **GitHub repo** | 200 | https://github.com/SabauAlexandru-py/higgsfield-genjutsu-unlimited |
| **Backend (Railway)** | `{"status":"ok"}` | https://higgsfield-genjutsu-unlimited-production.up.railway.app/health |
| **Frontend (Vercel)** | 200 | https://higgsfield-genjutsu-unlimited.vercel.app |
| **Env wiring** | set | `NEXT_PUBLIC_BACKEND_URL` → Railway backend (Production + Preview + Development) |

- **Railway project:** `eec8159b-2302-4692-a391-8bc928fed417` (name: `higgsfield-genjutsu-unlimited`)
- **Railway service:** `3bfb6f3f-09ae-485e-9908-60bc80817a0a`
- **Railway domain:** `higgsfield-genjutsu-unlimited-production.up.railway.app` (bound to port 8000, ACTIVE)
- **Railway account:** `alexmoto1102@gmail.com`
- **Vercel project:** `syn-mgmt/higgsfield-genjutsu-unlimited` (auto-deploys on push to `main`)
- **Latest commit:** `2e5b5cc` on `main`
- **Frontend note:** `syn-mgmt` team has Deployment Protection / SSO enabled — the URL redirects to Vercel SSO. Open it logged into Vercel, or disable protection to make it public.

---

## 3. Project Structure (31 files)

```
higgsfield-genjutsu-unlimited/
├── frontend/                  # Next.js 14 App Router + TypeScript + Tailwind
│   ├── app/
│   │   ├── page.tsx            # Main Genjutsu UI clone (upload/prompt/generate/progress/logs/video/history)
│   │   ├── api/generate/route.ts   # Proxies multipart upload to backend -> { jobId }
│   │   ├── layout.tsx          # Root layout, dark bg, metadata
│   │   └── globals.css        # Tailwind directives + neon scrollbar
│   ├── components/
│   │   ├── UploadZone.tsx      # Drag-drop, exact text "DROP REFERENCE VIDEO OR IMAGE HERE..."
│   │   ├── ProgressBar.tsx    # Animated gradient progress bar
│   │   ├── LogPanel.tsx        # Timestamped live logs, autoscroll
│   │   ├── VideoPlayer.tsx     # Result video player + download
│   │   └── History.tsx         # Generation history sidebar (localStorage)
│   ├── lib/utils.ts            # cn() (shadcn-style), ts(), humanSize()
│   ├── vercel.json             # Frontend Vercel config
│   ├── tailwind.config.ts      # Purple neon theme (#bb00ff / #7a00b3)
│   ├── postcss.config.js
│   ├── next.config.js
│   ├── tsconfig.json
│   └── package.json
├── backend/                    # FastAPI + Playwright
│   ├── main.py                 # FastAPI app: /generate, /jobs/{id}/stream (SSE), /jobs/{id}/video, /health, worker pool
│   ├── creator.py              # HiggsfieldCreator: full pipeline, 3 retries, proxy rotation, Model/Quality/Use-free-gens, captcha detection, page.expect_download
│   ├── temp_mail.py            # Async 1secmail wrapper (create + poll inbox + extract verification link)
│   ├── database.py            # aiosqlite account store (save / get-with-credits / mark-used)
│   ├── Dockerfile              # Python + Playwright Chromium image (Railway/Render/fly)
│   ├── railway.json            # Railway deploy config (DOCKERFILE builder, healthcheck)
│   ├── requirements.txt       # fastapi, uvicorn, httpx, aiosqlite, playwright, etc.
│   └── .env.example           # PROXY_LIST, HEADLESS, BROWSER_LOCALE, CORS_ORIGINS, VIDEO_DIR
├── desktop/                    # Tkinter mirror of the UI (local)
│   ├── main.py
│   └── requirements.txt
├── docs/
│   ├── PRD.md                  # Product requirements
│   ├── DESIGN.md               # Architecture (text diagram), data flow, anti-detection, flaw mitigation, deploy guides
│   └── README-Vercel.md        # Vercel-specific deployment guide
├── Dockerfile                  # Root Dockerfile (backend/ prefixed COPYs, context = repo root)
├── railway.json               # Root Railway config (forces DOCKERFILE builder)
├── deploy-everything.sh        # One-command: gh repo create + git push + vercel deploy --prod
├── README.md
├── .gitignore
└── vercel.json (root)         # Redirects to the Vercel frontend
```

---

## 4. Architecture (text diagram)

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  Frontend (Next.js / Vercel) │        │  Backend (FastAPI / Railway)  │
│                             │        │                              │
│  UploadZone ─┐              │  POST  │  /generate ──► WORK_QUEUE     │
│  Prompt      │  /api/gen    │ ─────► │                  │           │
│  Generate btn┘              │        │                  ▼           │
│  ProgressBar ◄── SSE ◄─────┼────────┤  worker pool (N) │           │
│  LogPanel    ◄── SSE ◄─────┼────────┤   │              │           │
│  VideoPlayer◄── /video ────┼────────┤   ▼              ▼           │
│  History     │              │        │ HiggsfieldCreator            │
└─────────────────────────────┘        │   ├─ TempMail (1secmail)     │
                                       │   ├─ Playwright + Chromium   │
                                       │   └─ SQLite (accounts.db)    │
                                       └──────────────────────────────┘
                                                  │
                                                  ▼
                                       ┌────────────────────┐
                                       │  higgsfield.ai     │
                                       │  (proxied, headless)│
                                       └────────────────────┘
```

### Data flow (per generation)
1. User drops file + prompt → `POST /api/generate` → backend `POST /generate`.
2. Backend saves reference, creates `Job`, enqueues `WORK_QUEUE`.
3. Worker picks job → `HiggsfieldCreator.run()`:
   - `TempMail.create()` → temp inbox
   - `goto /signup` → fill name/email/password → submit
   - `TempMail.wait_for_link()` → `goto verification link`
   - `goto /login` → fill creds → submit
   - `goto /create` → select Model=Genjutsu, Quality=720p, toggle Use free gens ON
   - `set_input_files(reference)` → fill prompt → click Generate
   - wait for result `<video>` or download button
   - `page.expect_download()` → save mp4 (fallback: `page.request` on `<video src>`)
4. Worker emits `progress` + `log` SSE events throughout; final `done` event carries filename.
5. Frontend `EventSource` updates ProgressBar / LogPanel; on `done` sets VideoPlayer src to `/jobs/{id}/video` + writes History to localStorage.

---

## 5. The Real Higgsfield UI Flow (from the screenshot)

The settings panel the bot drives (matches the actual Higgsfield interface):
- **Model** row → select **"Higgsfield Genjutsu"** (green squiggle icon, chevron menu)
- **Quality** row → select **"720p"** (chevron menu)
- **Use free gens** row → toggle switch (with a green badge showing a star + "1" free gen). The bot reads `aria-checked`/`data-state` and clicks it ON only if currently OFF — this is what consumes the 1 free credit per fresh account.

---

## 6. Anti-Detection Strategy
- Playwright Chromium with `--disable-blink-features=AutomationControlled`.
- Fingerprint spoof via `add_init_script`: `navigator.webdriver=undefined`, fixed `languages`, fake `plugins`.
- Per-attempt proxy rotation from `PROXY_LIST` (residential socks5 recommended).
- Random human delays 500–2000ms between actions.
- Realistic viewport (1440×900) + desktop User-Agent.
- Captcha detection at signup/verify/login/create → fail fast + screenshot (no silent 5-min hang).

---

## 7. Bugs Found & Fixed During the Build

| # | Bug | Fix |
|---|---|---|
| 1 | `creator.py` didn't touch the Model/Quality/Use-free-gens settings | Rewrote `_run_genjutsu` to drive the real settings UI (select_menu_option + ensure_toggle_on) |
| 2 | Video download fallback used bare `httpx.get()` — no session cookies → 401 on protected URLs | Switched to `self.page.request.get()` (rides the browser cookie jar) |
| 3 | No captcha detection → bot hung for 5 min | Added `detect_captcha()` at signup/verify/login/create + screenshot + clear error |
| 4 | No failure screenshots | Every failed attempt dumps a full-page PNG to `/tmp/debug` |
| 5 | No name field on signup | Added best-effort first/last name fills |
| 6 | `database.py` used `NULLS FIRST` (invalid SQLite) | Fixed to `ORDER BY last_used IS NOT NULL, last_used ASC` |
| 7 | `main.py` worker referenced undefined `creator_out` | Rewrote worker: proper `creator.run()` → `job.video_path`, progress loop, terminal events |
| 8 | Railway used Railpack (ignored Dockerfile) → build failed | Added root `Dockerfile` + `railway.json` forcing `DOCKERFILE` builder |
| 9 | `undetected-playwright==3.4.5` doesn't exist (max is 0.3.0) | Switched to standard `playwright==1.45.0` (kept fingerprint spoof via init scripts) |
| 10 | Railway domain had no target port → 502 | Bound domain to port 8000 (`railway domain update --port 8000`) |

---

## 8. Configuration (backend/.env — copy from .env.example)

| Var | Default | Meaning |
|---|---|---|
| `PROXY_LIST` | (none) | comma-separated `socks5://user:pass@host:port` (rotated per attempt) |
| `HEADLESS` | `true` | headless browser on server |
| `BROWSER_LOCALE` | `en-US` | browser locale |
| `CORS_ORIGINS` | `*` | allowed frontend origins (set to the Vercel URL) |
| `VIDEO_DIR` | `/tmp/videos` | where result mp4s land |
| `UPLOAD_DIR` | `/tmp/uploads` | where reference files land |
| `DEBUG_DIR` | `/tmp/debug` | failure screenshots |
| `MAX_WORKERS` | `2` | parallel generation workers |
| `DB_PATH` | `accounts.db` | SQLite account store |

### Currently set on Railway
- `HEADLESS=true`, `BROWSER_LOCALE=en-US`, `MAX_WORKERS=2`
- `CORS_ORIGINS=https://higgsfield-genjutsu-unlimited.vercel.app,https://higgsfield-genjutsu-unlimited-2ux2k4x42-syn-mgmt.vercel.app`
- `PROXY_LIST` = **empty** (no residential proxy yet — see "Next steps")

---

## 9. How to Run

### Local
```bash
cd /Users/alexandru.sabau/Projects/higgsfield-genjutsu-unlimited/backend
pip install -r requirements.txt
python -m playwright install chromium
uvicorn main:app --reload            # :8000

cd ../frontend
npm install
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 npm run dev   # :3000
```

### One-command redeploy
```bash
cd /Users/alexandru.sabau/Projects/higgsfield-genjutsu-unlimited
./deploy-everything.sh
```

### Redeploy just the backend
```bash
cd /Users/alexandru.sabau/Projects/higgsfield-genjutsu-unlimited
railway up -y --detach --service 3bfb6f3f-09ae-485e-9908-60bc80817a0a
```

### Redeploy just the frontend
```bash
cd /Users/alexandru.sabau/Projects/higgsfield-genjutsu-unlimited/frontend
vercel deploy --prod --yes
```

---

## 10. API Reference (backend)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/generate` | multipart: `file` + `prompt` → `{ "jobId": "..." }` |
| `GET` | `/jobs/{id}/stream` | SSE: `log` / `progress` / `done` / `error` events |
| `GET` | `/jobs/{id}/video` | `FileResponse` of the result mp4 |
| `GET` | `/health` | `{ "status": "ok", "jobs": N }` |

---

## 11. Known Limitations / Next Steps

1. **No residential proxy** — Higgsfield may flag the Railway datacenter IP. Add:
   ```
   railway variable set "PROXY_LIST=socks5://user:pass@host:port,socks5://user2:pass2@host2:port2"
   ```
2. **Captcha = the only manual gap.** If Higgsfield shows one, the bot fails fast with a screenshot in `/tmp/debug`. Wire a solver (2captcha / anti-captcha) into `detect_captcha` when encountered.
3. **Single-instance job store** — `JOBS` dict is in-memory. For multi-instance scale, move to Redis.
4. **1secmail may be down/rate-limited** — `TempMail` interface is swappable; drop in mail.tm by changing `API`/`DOMAINS` in `temp_mail.py`.
5. **Vercel Deployment Protection** is on for `syn-mgmt` — frontend redirects to SSO. Disable for public access.
6. **Railway free/hobby plan** has limited hours — watch usage.

---

## 12. Accounts / Credentials Used
- **GitHub:** `SabauAlexandru-py` (SSH key `~/.ssh/id_ed25519_github`)
- **Vercel:** `synmgmtmain-8987` (team `syn-mgmt`)
- **Railway:** `alexmoto1102@gmail.com`

---

## 13. File Inventory (all committed to `main`)

**Frontend (16):** `package.json`, `next.config.js`, `tailwind.config.ts`, `postcss.config.js`, `tsconfig.json`, `vercel.json`, `app/globals.css`, `app/layout.tsx`, `app/page.tsx`, `app/api/generate/route.ts`, `components/UploadZone.tsx`, `components/ProgressBar.tsx`, `components/LogPanel.tsx`, `components/VideoPlayer.tsx`, `components/History.tsx`, `lib/utils.ts`

**Backend (8):** `main.py`, `creator.py`, `temp_mail.py`, `database.py`, `requirements.txt`, `.env.example`, `Dockerfile`, `railway.json`

**Desktop (2):** `main.py`, `requirements.txt`

**Docs (3):** `PRD.md`, `DESIGN.md`, `README-Vercel.md`

**Root (6):** `Dockerfile`, `railway.json`, `deploy-everything.sh`, `README.md`, `.gitignore`, `vercel.json`

---

*Built and deployed September 8, 2026. Repo: https://github.com/SabauAlexandru-py/higgsfield-genjutsu-unlimited*
