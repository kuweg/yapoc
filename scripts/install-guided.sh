#!/usr/bin/env bash
# Linux/macOS bootstrap. The wizard reads from /dev/tty even with curl | bash.
set -euo pipefail
ref="${YAPOC_REF:-main}"
if ! command -v node >/dev/null 2>&1; then
  echo 'Install Node.js 22+ from https://nodejs.org/en/download then run this command again.' >&2
  exit 1
fi
node -e 'if(Number(process.versions.node.split(".")[0])<22)process.exit(1)' || {
  echo 'Node.js 22 or newer is required.' >&2; exit 1;
}
temporary="$(mktemp -d)"
trap 'rm -f "$temporary/install.mjs"; rmdir "$temporary"' EXIT
curl -fsSL "https://raw.githubusercontent.com/kuweg/yapoc/$ref/installer/index.mjs" -o "$temporary/install.mjs"
node "$temporary/install.mjs" --ref "$ref" "$@" </dev/tty
