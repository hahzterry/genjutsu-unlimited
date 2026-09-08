# Product Requirements — higgsfield-genjutsu-unlimited

## Problem
Higgsfield gives every new account **1 free Genjutsu credit**. Power users hit that wall
after a single render. Manual account creation is tedious and breaks creative flow.

## Solution
A self-hosted tool that **auto-creates a fresh verified account per generation**,
burns the free credit, and returns the rendered video — giving effectively unlimited
free Genjutsu videos from the user's perspective.

## Personas
- **Creator** — wants many Genjutsu variants without paying per render.
- **Operator** — runs the backend, rotates proxies, watches logs.

## Functional Requirements
1. Web UI (Next.js) that visually matches the real Higgsfield Genjutsu screen.
2. Drag-and-drop reference upload (image or video) with live preview.
3. Cinematic prompt textarea with sensible default.
4. One-click **GENERATE WITH GENJUTSU** button.
5. Real-time progress bar + timestamped live logs.
6. Result video player with download.
7. Generation history sidebar (persisted in localStorage).
8. Backend (FastAPI) that performs the full invisible automation:
   temp email → signup → verify → login → Genjutsu → upload → prompt → generate → download.
9. 3 retry attempts per generation, proxy rotation per attempt.
10. SQLite account store for potential reuse of accounts with leftover credits.
11. Parallel generation queue (configurable workers).
12. Residential proxy support via `PROXY_LIST` env var.

## Non-Functional Requirements
- Anti-detection via `undetected-playwright` + fingerprint spoofing + human delays.
- Robust selectors with multiple fallbacks (text / placeholder / role / css).
- Cold-start tolerant: backend recovers and retries on transient failures.
- Single-instance job store (Redis optional for horizontal scale).
- Frontend deployable to Vercel; backend deployable to Render/Railway.

## Out of Scope (v1)
- Captcha solving (manual fallback noted in DESIGN.md).
- Paid-account automation.
- Multi-tenant auth on the tool itself.

## Success Metrics
- ≥ 95% of generate clicks yield a downloadable mp4 within 5 minutes.
- Median end-to-end latency < 3 minutes on a residential proxy.
- Zero manual intervention across 50 consecutive generations.
