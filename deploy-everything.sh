#!/usr/bin/env bash
# deploy-everything.sh
# One-command build + push + deploy for higgsfield-genjutsu-unlimited v3.0
# Deploys: GitHub (repo) + Vercel (frontend) + Fly.io (backend, no hour limits)
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

banner "Higgsfield Genjutsu Unlimited v3.0 — Deployer"

# --- Prereqs ---
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
  git commit -q -m "Deploy: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ok "committed"
fi

info "pushing to main..."
git push -u origin main
ok "pushed to github.com/${OWNER}/${REPO}"

# --- Frontend → Vercel ---
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

cd "$SCRIPT_DIR"

# --- Backend → Fly.io ---
banner "Backend → Fly.io (no hour limits, horizontal scaling)"

if ! command -v fly >/dev/null 2>&1; then
  info "fly CLI missing — installing..."
  curl -L https://fly.io/install.sh | sh
  export PATH="$HOME/.fly/bin:$PATH"
fi
ok "fly present"

if ! fly auth whoami >/dev/null 2>&1; then
  warn "fly not authenticated. Launching login..."
  fly auth login
fi
ok "fly authenticated"

if ! fly apps list | grep -q "higgsfield-genjutsu-unlimited"; then
  info "creating Fly.io app..."
  fly launch --no-deploy --name higgsfield-genjutsu-unlimited --region iad --dockerfile Dockerfile
  ok "Fly.io app created"
else
  ok "Fly.io app already exists"
fi

info "deploying backend to Fly.io..."
fly deploy --dockerfile Dockerfile --strategy rolling
ok "backend deployed to Fly.io"

info "setting secrets..."
echo "  Set your API key and proxy list manually:"
echo -e "  ${YELLOW}fly secrets set API_KEY=<your-secret-key>${NC}"
echo -e "  ${YELLOW}fly secrets set PROXY_LIST=socks5://user:pass@host:port,socks5://user2:pass2@host2:port2${NC}"
echo -e "  ${YELLOW}fly secrets set CORS_ORIGINS=https://higgsfield-genjutsu-unlimited.vercel.app${NC}"

info "scaling to 2 VMs (4 concurrent workers)..."
fly scale count 2 --max-per-region 4
ok "scaled to 2 VMs"

FLY_URL="https://higgsfield-genjutsu-unlimited.fly.dev"

banner "Wire frontend → backend"
echo -e "  Vercel dashboard → project → Settings → Environment Variables"
echo -e "  Add: ${YELLOW}NEXT_PUBLIC_BACKEND_URL = ${FLY_URL}${NC}"
echo -e "  Add: ${YELLOW}NEXT_PUBLIC_API_KEY = <your-secret-key>${NC}"
echo -e "  Redeploy frontend."

banner "Done"
echo -e "${PURPLE}Repo:     https://github.com/${OWNER}/${REPO}${NC}"
echo -e "${PURPLE}Frontend:  https://higgsfield-genjutsu-unlimited.vercel.app${NC}"
echo -e "${PURPLE}Backend:   ${FLY_URL}${NC}"
echo -e "${PURPLE}Health:    ${FLY_URL}/health${NC}"
echo ""
echo -e "${YELLOW}To spam unlimited generations:${NC}"
echo -e "  1. Set PROXY_LIST with your residential proxies (fly secrets set ...)"
echo -e "  2. Set API_KEY and use it in the X-API-Key header"
echo -e "  3. Scale workers: fly scale count N  (each VM runs MAX_WORKERS browsers)"
echo -e "  4. Each generation creates a fresh account on a fresh IP = unlimited free videos"
