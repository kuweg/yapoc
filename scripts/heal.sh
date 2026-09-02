#!/usr/bin/env bash
# heal.sh — regenerate app/config/agent-settings.json from the built-in default.
#
# Standalone recovery tool. Run when:
#   - agent-settings.json is missing, corrupt, or someone edited it into
#     an invalid state
#   - the Doctor agent is not responding and cannot self-heal
#   - you want to reset to the canonical primary + fallback chains
#
# v2 stores no API keys in this file, so there is no "wipe" mode any
# more; heal is always safe to run.
#
# Usage:
#   bash scripts/heal.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

SETTINGS_FILE="$REPO_ROOT/app/config/agent-settings.json"

log() { printf '[heal] %s\n' "$*" >&2; }

log "regenerating $SETTINGS_FILE from built-in default"
poetry run python -m app.utils.agent_settings heal
rc=$?

if [ $rc -eq 0 ]; then
    log "OK — $SETTINGS_FILE regenerated"
else
    log "FAILED (exit=$rc)"
fi
exit $rc
