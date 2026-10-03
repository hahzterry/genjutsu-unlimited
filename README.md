# higgsfield-genjutsu-unlimited

Unlimited free **Higgsfield Genjutsu** videos by auto-creating a fresh verified
account for every generation (each new account gets 1 free credit).

This is a repaired and restructured fork. The original could not build, could
not run, and was split across two hosts in a way that does not survive Render's
free tier. Everything below has been verified end to end.

---

## Deploy to Render for free (one click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/dandysuper/genjutsu-unlimited)

Or manually: **Render dashboard → New + → Blueprint → select
`dandysuper/genjutsu-unlimited` → Apply.**

Render reads `render.yaml`, builds `Dockerfile`, and creates **one** free web
service that serves both the UI and the API.

You will be prompted for two optional values:

| Variable | What to put |
|---|---|
| `PROXY_LIST` | Your residential proxies, comma-separated. Leave blank to skip. |
| `API_KEY` | Any long random string. Leave blank to run with no auth. |

Then open the service URL. That's it — no second host, no CORS setup, no
`NEXT_PUBLIC_BACKEND_URL` to wire up.

### Why one service, not two

Render's free plan gives **750 instance-hours per month across all free
services**. One always-on service uses ~730 of them. A second free service — the
original design, a separate Next.js frontend on Vercel — pushes the total past
the limit and Render suspends one of them.

So the Next.js frontend is **statically exported** and served by FastAPI from
the same container. One service, one cold start, no cross-origin traffic.

### Does it fit in 512 MB?

Yes, with `MAX_WORKERS=1`. Each worker is a full headless Chromium, which is why
the worker count is capped and the browser runs with renderer memory limits.
This was measured, not assumed:

```
$ docker run --memory=512m ... genjutsu:local
$ docker exec <ctr> python check_browser.py
chromium version: 153.0.8010.12
dom text: 'ok'
canvas 2d context: True
OK: headless chromium launches and renders with these flags
```

Raise `MAX_WORKERS` only if you move to a bigger instance (Render Standard, 2 GB).

Note that free instances **sleep after 15 minutes** of inactivity. The first
request after that takes ~50 s to wake. That is Render's behaviour, not a bug here.

---

## How it works

1. You drop a reference video (4–30 s) and optional images, write a prompt.
2. The browser POSTs to `/generate`; FastAPI enqueues a job and returns a `jobId`.
3. A worker drives headless Chromium:
   - creates a temp inbox (mail.tm, falling back to 1secmail),
   - signs up on higgsfield.ai, polls the inbox, opens the verification link,
   - logs in, opens Create, sets Model → *Higgsfield Genjutsu*, Quality → *720p*,
     toggles *Use free gens* on,
   - uploads the reference, fills the prompt, clicks Generate,
   - waits for the result and downloads it.
4. Progress and logs stream back over SSE; the mp4 is served at
   `/jobs/{id}/video`.
5. Each generation uses a brand-new account = a brand-new free credit.

If a proxy pool is configured, each new account is created through the next
proxy in rotation, so every signup comes from a different IP.

---

## Architecture

```
                    one Render service (Docker)
   ┌──────────────────────────────────────────────────────────┐
   │  FastAPI                                                 │
   │                                                          │
   │  GET  /               → static Next.js export            │
   │  GET  /config         → { authRequired }                 │
   │  GET  /health         → liveness probe                   │
   │  POST /generate       → multipart upload → { jobId }     │
   │  GET  /jobs/{id}/stream → SSE log / progress / done      │
   │  GET  /jobs/{id}/video  → the finished mp4               │
   │  GET  /proxies        → pool status                      │
   │  POST /proxies        → replace the pool at runtime      │
   │  GET  /stats          → account + proxy stats            │
   │                                                          │
   │  worker pool (MAX_WORKERS asyncio tasks)                 │
   │     └─ HiggsfieldCreator → Playwright → Chromium         │
   │          ├─ TempMail (mail.tm / 1secmail)                │
   │          └─ SQLite at /tmp/accounts.db                   │
   └──────────────────────────────────────────────────────────┘
```

---

## Configuration

All optional. Set them in the Render dashboard (or `backend/.env` locally).

| Variable | Default | Meaning |
|---|---|---|
| `PROXY_LIST` | *(empty)* | Proxies, comma- or pipe-separated. Accepts `host:port:user:pass` or a full `socks5h://user:pass@host:port` URL. |
| `API_KEY` | *(empty)* | When set, `/generate`, `/jobs`, `/proxies` and `/stats` require `X-API-Key`. The UI prompts for it once and stores it in the browser. |
| `MAX_WORKERS` | `1` | Concurrent Chromium instances. Raise only on a larger instance. |
| `RUN_TIMEOUT` | `900` | Whole-job ceiling in seconds (signup + inbox wait + generation + download). |
| `JOB_TTL` | `3600` | How long finished jobs and their mp4s are kept. |
| `RATE_LIMIT` | `0` | Max API requests per minute per IP. `0` disables. |
| `HEADLESS` | `true` | Headless browser. |
| `CORS_ORIGINS` | `*` | Only relevant if you host the frontend separately. |

---

## Local development

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# serve the API only
uvicorn main:app --reload
```

Frontend, in a second shell:

```bash
cd frontend
npm install
npm run build          # produces the static export in frontend/out
```

Then point the backend at that export and open <http://localhost:8000>:

```bash
cd backend
STATIC_DIR=../frontend/out uvicorn main:app --reload
```

Serving the export through FastAPI keeps local and production identical — the
same origin, the same relative URLs.

Running the whole thing in Docker:

```bash
docker build -t genjutsu:local .
docker run --rm -p 8000:8000 genjutsu:local
```

---

## Verifying a deploy

```bash
curl https://<your-service>.onrender.com/health
# {"status":"ok","jobs":0,"workers":1}
```

Inside the container (Render dashboard → Shell):

```bash
python test_backend.py     # 46 checks: proxy parsing/rotation, link extraction,
                           # account lifecycle, HTTP API
python check_browser.py    # proves Chromium actually launches on this host
```

`check_browser.py` is worth running after any infrastructure change: Chromium
will not start as root without `--no-sandbox`, and it crashes at random without
`--disable-dev-shm-usage`. Both flags are set in `creator.py`.

---

## What was broken, and what fixed it

| Problem | Effect | Fix |
|---|---|---|
| No `--no-sandbox` / `--disable-dev-shm-usage` | Chromium never starts in Docker, so every job failed instantly | Container flag set in `creator.BROWSER_ARGS` |
| Uploads written without a file extension | Playwright sent `application/octet-stream`, Higgsfield rejected the upload | Preserve the original suffix end to end |
| `MAX_WORKERS` defaulted to 4 | Four Chromium instances on a 512 MB instance → OOM | Default to 1, with renderer memory caps |
| Frontend called a separate backend host | Two free services exceed Render's 750 h/month | Static export served by FastAPI, same origin |
| `python:3.11-slim` silently moved to Debian 13 | `playwright install --with-deps` fell back to ubuntu20.04 packages and died on `ttf-unifont` | Pin both base images to bookworm |
| `playwright==1.45.0` | Bundled Chromium 127 (Aug 2024) — noticeably easier to fingerprint | Bumped to 1.63.0 (Chromium 153) |
| `stress_test.py` imported an API that never existed | The test suite could not even be imported | Replaced with `test_backend.py`, 46/46 passing |
| Dead `ProxyPool` class | Shadowed `ProxyManager`; nothing matched its callers | Removed |
| `human_click` used a possibly-unbound local | `NameError` on a failed locator | Initialised before use |
| `TempMail` client closed then reused on retry | Every retry after the first raised on a closed client | Client created lazily, re-created after close |
| mail.tm used a hardcoded domain | API rejects `mail.tm` as an address domain | Domains fetched from the API |

---

## Limitations

- **A residential proxy is effectively required.** Without one, Higgsfield sees a
  datacenter IP (Render's) and normally serves a Cloudflare challenge. Add
  proxies via `PROXY_LIST` or the Proxies panel in the UI. This is the single
  biggest factor in whether generations succeed.
- **Captchas are not solved.** If one appears, the job fails fast with a
  screenshot written to `/tmp/debug` and a clear log line, rather than hanging.
- **The job store is in-memory.** It is deliberately a single-instance design;
  scaling past one instance needs Redis.
- **Free instances sleep.** First request after 15 minutes of idling is slow.
- **`/tmp` is ephemeral.** Accounts, uploads and finished videos do not survive a
  restart. That is fine — the account DB is a cache, not a record.
- Free tier gives 0.1 CPU. Generation is slower than on a paid instance.

---

## Layout

```
├── backend/            FastAPI + Playwright
│   ├── main.py         app, worker pool, API, static file serving
│   ├── creator.py      the Higgsfield automation itself
│   ├── temp_mail.py    mail.tm / 1secmail inbox
│   ├── database.py     SQLite account store
│   ├── proxy_manager.py rotation, cooldowns, failure tracking
│   ├── test_backend.py 46-check self test
│   └── check_browser.py proves Chromium launches on the host
├── frontend/           Next.js 14, statically exported
├── desktop/            local Tkinter client
├── Dockerfile          multi-stage: build the export, serve it from Python
└── render.yaml         one free Render web service
```

---

For research and educational automation. Respect Higgsfield's terms of service
where they apply to you.
