# higgsfield-genjutsu-unlimited

Unlimited free **Higgsfield Genjutsu** videos by auto-creating a fresh verified account
for every generation (each new account gets 1 free credit).

```
higgsfield-genjutsu-unlimited/
├── frontend/   Next.js 14 — pixel-perfect Genjutsu UI clone (Vercel)
├── backend/    FastAPI + undetected-playwright — invisible automation (Render/Railway)
├── desktop/    Tkinter mirror of the UI (local)
├── docs/       PRD, design, Vercel guide
└── deploy-everything.sh   one-command build/push/deploy
```

## Quick start (local)
```bash
cd backend
pip install -r requirements.txt
python -m playwright install chromium
uvicorn main:app --reload

cd ../frontend
npm install
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 npm run dev
```

## One-command deploy
```bash
./deploy-everything.sh
```

## How it works
1. Drop a reference image/video + write a prompt.
2. Frontend POSTs to backend → backend enqueues a job.
3. A worker spins up an undetected Playwright browser:
   - creates a temp inbox (1secmail),
   - signs up on higgsfield.ai, polls inbox, opens verification link,
   - logs in, opens Genjutsu, uploads reference, fills prompt, clicks Generate,
   - waits for completion, downloads the result via `page.expect_download()`.
4. Progress + logs stream back over SSE; final video served at `/jobs/{id}/video`.

## Config (backend/.env — copy from .env.example)
| Var | Default | Meaning |
|---|---|---|
| `PROXY_LIST` | (none) | comma-separated `socks5://user:pass@host:port` |
| `HEADLESS` | `true` | headless browser on server |
| `BROWSER_LOCALE` | `en-US` | browser locale |
| `CORS_ORIGINS` | `*` | allowed frontend origins |
| `VIDEO_DIR` | `./videos` | where result mp4s land |
| `MAX_WORKERS` | `2` | parallel generation workers |

For research / educational automation. Respect Higgsfield's ToS where applicable.
