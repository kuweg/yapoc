#!/usr/bin/env bash
# yapoc-lifecycle.sh — start YAPOC with a sanity-checked agent-settings.json.
#
# As of agent-settings.json v2 (stored at app/config/agent-settings.json),
# API keys are never written to disk — they are resolved from the
# environment on every adapter construction. This script therefore no
# longer fills/wipes secrets; its job is to:
#
#   1. Make sure app/config/agent-settings.json exists and is valid JSON
#      (heal from the built-in default if not).
#   2. Run yapoc.
#   3. On exit — normal, Ctrl+C, SIGTERM, HUP, QUIT, or crash — do a
#      best-effort verification that no legacy secret-bearing files from
#      the v1 layout were left behind.
#
# Usage:
#   bash scripts/yapoc-lifecycle.sh               # interactive REPL
#   bash scripts/yapoc-lifecycle.sh start         # start backend
#   bash scripts/yapoc-lifecycle.sh chat "hi"     # one-shot

set -u  # unset vars = error; do NOT set -e so cleanup always runs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

SETTINGS_FILE="$REPO_ROOT/app/config/agent-settings.json"
LEGACY_FILES=(
    "$REPO_ROOT/app/agents/doctor/agent-settings.json"
    "$REPO_ROOT/app/agents/doctor/agent-settings-base.json"
)

log() { printf '[lifecycle] %s\n' "$*" >&2; }

cleanup() {
    local rc=${1:-$?}
    log "cleanup (exit=$rc)"
    # Best-effort sweep of any legacy secret-bearing files. v2 stores no
    # keys, but if a user downgraded and came back we want to leave the
    # repo in a clean state.
    for f in "${LEGACY_FILES[@]}"; do
        if [ -f "$f" ]; then
            log "removing legacy file: $f"
            rm -f "$f" || true
        fi
    done
    exit "$rc"
}

# Install traps FIRST so even an early failure still runs cleanup.
trap 'cleanup $?' EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM
trap 'cleanup 129' HUP
trap 'cleanup 131' QUIT

if [ ! -f "$SETTINGS_FILE" ]; then
    log "$SETTINGS_FILE missing — healing from built-in default"
    poetry run python -m app.utils.agent_settings heal || {
        log "heal failed — aborting"
        exit 1
    }
fi

# Validate JSON before launching yapoc so a corrupt file doesn't silently
# cause every agent to fall through to CONFIG.md.
if ! poetry run python -m app.utils.agent_settings show >/dev/null; then
    log "$SETTINGS_FILE corrupt — healing"
    poetry run python -m app.utils.agent_settings heal || {
        log "heal failed — aborting"
        exit 1
    }
fi

log "starting yapoc $*"
poetry run yapoc "$@"
rc=$?

# Normal completion — trap still fires to run cleanup
exit $rc
