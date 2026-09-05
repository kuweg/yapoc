#!/usr/bin/env bash
# Install & switch YAPOC from `yapoc start` (bare uvicorn, dies with no
# restart) to a systemd USER unit running `yapoc supervise` (auto-restart,
# survives crashes and reboots when linger is enabled).
#
# Run ONCE, as your normal user (do NOT run as root / sudo):
#   bash scripts/systemd/install-supervisor.sh
#
# What it does:
#   1. Resolves ABSOLUTE paths for this checkout (project dir + poetry venv).
#   2. Rewrites scripts/systemd/yapoc.service with the resolved paths.
#   3. Stops the currently-running `yapoc start` uvicorn (frees port 8000).
#   4. Copies the unit to ~/.config/systemd/user/yapoc.service.
#   5. systemctl --user daemon-reload && enable --now yapoc.service
#   6. Prints how to verify / roll back.
#
# Rollback / go back to `yapoc start`:
#   systemctl --user disable --now yapoc.service
#   cd "$(dirname "$0")/../.." && poetry run yapoc start
set -euo pipefail

YELLOW=$'\033[1;33m'; GREEN=$'\033[1;32m'; RED=$'\033[1;31m'; RESET=$'\033[0m'
log()  { printf '%s>%s %s\n' "$YELLOW" "$RESET" "$*"; }
ok()   { printf '%sok:%s %s\n' "$GREEN" "$RESET" "$*"; }
fail() { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# ── refuse root ────────────────────────────────────────────────────────────────
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    fail "Do not run as root/sudo. Run as your normal user so the unit lands in ~/.config."
fi

# ── resolve project + venv ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
log "Project directory: $PROJECT_DIR"

if ! PY="$(cd "$PROJECT_DIR" && poetry env info -p 2>/dev/null)"; then
    fail "Could not resolve the poetry venv. Run 'poetry env info -p' in $PROJECT_DIR."
fi
PY="$PY/bin/python"
[[ -x "$PY" ]] || fail "Python not found at $PY"
ok "Resolved python: $PY"

# Port/host defaults captured below; edit if you run on something other than :8000.
HOST="${YAPOC_HOST:-0.0.0.0}"
PORT="${YAPOC_PORT:-8000}"

# ── generate unit file ─────────────────────────────────────────────────────────
UNIT_SRC="$SCRIPT_DIR/yapoc.service"
cat > "$UNIT_SRC" <<EOF
[Unit]
Description=YAPOC backend under supervisor (auto-restart on crash)
Documentation=https://github.com/kuweg/yapoc
After=default.target network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PY -m app.cli.main supervise --host $HOST --port $PORT
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30
KillMode=control-group

[Install]
WantedBy=default.target
EOF
ok "Wrote unit template to $UNIT_SRC"

# ── is there a running `yapoc start`/bare uvicorn to stop first? ──────────────
pgrep -f "uvicorn app.backend.main" >/dev/null 2>&1 && {
    log "Stopping existing bare uvicorn (frees port $PORT before supervisor start)."
    ( cd "$PROJECT_DIR" && poetry run yapoc stop ) || true
    sleep 2
} || ok "No prior bare uvicorn running."

# ── install the unit ───────────────────────────────────────────────────────────
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cp "$UNIT_SRC" "$UNIT_DIR/yapoc.service"
ok "Installed unit to $UNIT_DIR/yapoc.service"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
systemctl --user daemon-reload
systemctl --user enable --now yapoc.service
ok "Enabled + started yapoc.service."

# ── sanity check ───────────────────────────────────────────────────────────────
sleep 3
if systemctl --user is-active --quiet yapoc.service; then
    ok "yapoc.service is ACTIVE. Supervisor owns uvicorn now."
else
    RED; echo "Unit installed but not active. Diagnose with:"
    echo "  systemctl --user status yapoc.service"
    echo "  journalctl --user -u yapoc.service -n 50"
    RESET
fi

cat <<'EOF'

─── Verify / monitor ───
  systemctl --user status yapoc.service
  tail -f app/agents/master/SUPERVISOR.MD     # supervisor event log

─── Survive a reboot (optional but recommended) ───
  loginctl enable-linger "$USER"

─── Roll back to `yapoc start` ───
  systemctl --user disable --now yapoc.service
  cd $PROJECT_DIR && poetry run yapoc start
EOF
