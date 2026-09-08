#!/usr/bin/env bash
# deploy-everything.sh
# One-command build + push + deploy for higgsfield-genjutsu-unlimited
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; PURPLE='\033[0;35m'; CYAN='\033[0;36m'; NC='\033[0m'
banner(){ echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${PURPLE}  $1${NC}"; echo -e "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
info(){ echo -e "${CYAN}[*]${NC} $1"; }
ok(){   echo -e "${GREEN}[+]${NC} $1"; }
warn(){ echo -e "${YELLOW}[!]${NC} $1"; }
err(){  echo -e "${RED}[x]${NC} $1"; }

REPO="higgsfield-genjutsu-unlimited"
OWNER="SabauAlexandru-py"
REMOTE="git@github.com:${OWNER}/${REPO}.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

banner "Higgsfield Genjutsu Unlimited — Deployer"

if ! command -v git >/dev/null 2>&1; then err "git missing"; exit 1; fi
ok "git present"

if ! command -v gh >/dev/null 2>&1; then
  info "gh CLI missing — installing via Homebrew..."
  brew install gh
fi
ok "gh present"

if ! gh auth status >/dev/null 2>&1; then
  warn "gh not authenticated. Launching login..."
  gh auth login --web --git-protocol ssh
fi
ok "gh authenticated"

cd "$SCRIPT_DIR"
if [ ! -d .git ]; then
  git init -q
  git branch -M main 2>/dev/null || true
fi
ok "git repo ready"

if ! gh repo view "${OWNER}/${REPO}" >/dev/null 2>&1; then
  info "creating remote repo ${OWNER}/${REPO} (public)..."
  gh repo create "${OWNER}/${REPO}" --public --description "Unlimited free Higgsfield Genjutsu videos via auto account creation" --source=. --remote=origin --push=false
else
  ok "remote repo already exists"
  git remote remove origin 2>/dev/null || true
  git remote add origin "$REMOTE"
fi
ok "origin -> $REMOTE"

git add -A
if git diff --cached --quiet; then
  warn "nothing to commit (clean tree)"
else
  git commit -q -m "Initial commit - Higgsfield Genjutsu Unlimited v1.0"
  ok "committed"
fi

info "pushing to main..."
git push -u origin main
ok "pushed to github.com/${OWNER}/${REPO}"

banner "Frontend → Vercel"
if ! command -v vercel >/dev/null 2>&1; then
  info "vercel CLI missing — installing..."
  npm i -g vercel
fi
ok "vercel present"

if ! vercel whoami >/dev/null 2>&1; then
  warn "vercel not logged in. Run: vercel login  (then re-run this script)"
  exit 0
fi
ok "vercel logged in as: $(vercel whoami)"

info "installing frontend deps..."
cd frontend
[ -d node_modules ] || npm install
ok "deps installed"

info "linking + deploying to production..."
if [ ! -f .vercel/project.json ]; then
  vercel link --yes --project higgsfield-genjutsu-unlimited
fi
vercel deploy --prod --yes
ok "frontend deployed to Vercel"

banner "Backend → Render / Railway"
cat <<'EOF'
NEXT STEPS — Backend deployment

1. Render.com:
   - New → Web Service → connect repo SabauAlexandru-py/higgsfield-genjutsu-unlimited
   - Root Directory:  backend
   - Build Command:   pip install -r requirements.txt && python -m playwright install --with-deps chromium
   - Start Command:  uvicorn main:app --host 0.0.0.0 --port $PORT
   - Env: PROXY_LIST, HEADLESS=true, BROWSER_LOCALE=en-US, CORS_ORIGINS=https://higgsfield-genjutsu-unlimited.vercel.app

2. Railway.app:
   - New Project → Deploy from GitHub repo → select repo
   - Root Directory: backend
   - Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
   - Variables: same as Render

3. Wire frontend → backend:
   - Vercel dashboard → project → Settings → Environment Variables
   - Add: NEXT_PUBLIC_BACKEND_URL = https://your-backend.onrender.com
   - Redeploy frontend.

4. Residential proxies:
   - Edit backend/.env (copy from .env.example)
   - PROXY_LIST = comma-separated socks5://user:pass@host:port
EOF

ok "all done"
echo -e "${PURPLE}Repo:    https://github.com/${OWNER}/${REPO}${NC}"
