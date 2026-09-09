#!/usr/bin/env bash
set -euo pipefail
if ! command -v node >/dev/null 2>&1; then
  echo 'Install Node.js 22+ and Docker, then run this installer again.' >&2
  exit 1
fi
installer_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec node "$installer_dir/install.mjs" "$@"
