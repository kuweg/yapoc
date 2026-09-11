#!/usr/bin/env bash
set -euo pipefail
installer_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if command -v node >/dev/null 2>&1 && node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  exec node "$installer_dir/install.mjs" "$@"
fi
export YAPOC_LOCAL_INSTALLER="$installer_dir/install.mjs"
exec bash "$installer_dir/scripts/install-guided.sh" "$@"
