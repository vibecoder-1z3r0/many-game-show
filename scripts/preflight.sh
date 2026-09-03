#!/usr/bin/env bash
# Preflight check for running Many Game Show on a new machine (e.g. the
# actual conference laptop). Checks host-level prerequisites that `uv sync`
# does NOT handle for you — everything else (Python 3.13, all Python deps)
# lives inside uv's auto-created .venv and needs nothing pre-installed.
#
# Exit code 0 = ready to `make sync && make run`.
# Exit code 1 = something needs fixing first (see output).

set -u

PASS=0
FAIL=0
WARN=0

pass() { echo "  OK   $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL $1"; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN $1"; WARN=$((WARN + 1)); }

echo "Many Game Show — preflight check"
echo "================================="
echo

echo "-- Required tools --"

if command -v uv >/dev/null 2>&1; then
  pass "uv found ($(uv --version))"
else
  fail "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  fail "  (or: brew install uv / pipx install uv / see https://docs.astral.sh/uv/)"
fi

if command -v git >/dev/null 2>&1; then
  pass "git found ($(git --version))"
else
  fail "git not found — needed to clone/update the repo"
fi

echo
echo "-- Network reachability --"

check_url() {
  local url="$1" label="$2" required="$3"
  if curl -fsS --max-time 4 -o /dev/null "$url" 2>/dev/null; then
    pass "$label reachable"
  elif [ "$required" = "required" ]; then
    fail "$label NOT reachable — needed for '$4'"
  else
    warn "$label NOT reachable — $4"
  fi
}

check_url "https://pypi.org" "PyPI" required "uv sync (fetching Python packages)"
check_url "https://astral.sh" "astral.sh (uv releases)" optional \
  "only needed if uv itself isn't installed yet"
check_url "https://fonts.googleapis.com" "Google Fonts" optional \
  "squad-squabble.html loads Orbitron from here live; falls back to a system font if unreachable, just looks plainer"

echo
echo "-- Local environment --"

if command -v lsof >/dev/null 2>&1 && lsof -ti:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  warn "port 8000 is already in use — 'make run' will fail until it's freed"
else
  pass "port 8000 is free"
fi

if [ -d ".venv" ]; then
  pass ".venv already exists (uv sync will reuse/update it)"
else
  warn ".venv not created yet — run 'make sync' first"
fi

if command -v uv >/dev/null 2>&1; then
  if [ -f "uv.lock" ]; then
    pass "uv.lock present (reproducible installs)"
  else
    warn "uv.lock missing — 'uv sync' will generate one"
  fi
fi

echo
echo "-- UI tests (only needed if you plan to run 'make test-ui') --"

PW_CACHE="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
if [ -d "$PW_CACHE" ] && find "$PW_CACHE" -maxdepth 1 -iname 'chromium*' 2>/dev/null | grep -q .; then
  pass "a Playwright Chromium build appears to be installed"
else
  warn "no Playwright Chromium build found — run: uv run playwright install --with-deps chromium"
  warn "  (only needed for 'make test-ui'; not needed to just run the app)"
fi

echo
echo "================================="
echo "Passed: $PASS   Warnings: $WARN   Failed: $FAIL"
echo

if [ "$FAIL" -gt 0 ]; then
  echo "Fix the FAIL items above before 'make sync && make run'."
  exit 1
else
  echo "Ready for: make sync && make run"
  exit 0
fi
