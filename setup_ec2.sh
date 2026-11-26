#!/usr/bin/env bash
# Provision this project on a fresh EC2 Linux instance (Amazon Linux 2023 / Ubuntu).
# Installs Python + venv, project deps, Playwright Firefox and its system libs,
# then runs the offline test suite. Does NOT log in to LinkedIn (see EC2_SETUP.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

log() { printf '\n=== %s ===\n' "$*"; }

log "detecting package manager"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip xvfb ca-certificates curl
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3 python3-pip xorg-x11-server-Xvfb ca-certificates curl
  sudo dnf install -y gtk3 alsa-lib dbus-glib libXt mesa-libgbm || true
else
  echo "unsupported distro: need apt-get or dnf" >&2
  exit 1
fi

log "creating virtualenv"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip wheel
.venv/bin/python -m pip install -r requirements.txt

log "installing Playwright Firefox (+ system dependencies)"
if ! .venv/bin/python -m playwright install --with-deps firefox; then
  echo "--with-deps failed (common on Amazon Linux); installing the browser only"
  .venv/bin/python -m playwright install firefox
fi

log "preparing directories"
mkdir -p secrets output logs
chmod 700 secrets
[ -f .env ] || { cp .env.example .env && chmod 600 .env; }

log "verifying the install offline (no LinkedIn access)"
.venv/bin/python -m playwright --version
.venv/bin/python tests/test_heuristics.py

cat <<'NEXT'

Setup complete.

Next:
  1. Put an authenticated session on this instance — see EC2_SETUP.md section 3
     (recommended: log in on your laptop with `python login.py`, copy
     secrets/linkedin_state.json.enc here and export LI_SESSION_KEY).
  2. Validate it:   .venv/bin/python login.py --check
  3. Extract:       .venv/bin/python run_analytics.py --url "<company admin analytics URL>"
NEXT
