#!/usr/bin/env bash
# Linux/macOS bootstrap. The wizard reads from /dev/tty even with curl | bash.
set -euo pipefail
ref="${YAPOC_REF:-main}"
case "$(uname -s)" in
  Darwin) yapoc_os=macOS ;;
  Linux) yapoc_os=Linux ;;
  *) echo 'Use install.ps1 in Windows PowerShell, or run this installer on macOS/Linux.' >&2; exit 1 ;;
esac
printf '\nYAPOC setup — %s (%s)\n' "$yapoc_os" "$(uname -m)"
# Finder-launched terminals may not have Homebrew on PATH yet.
if [ "$yapoc_os" = macOS ]; then
  for yapoc_bin in /opt/homebrew/bin /usr/local/bin; do
    if [ -d "$yapoc_bin" ]; then export PATH="$PATH:$yapoc_bin"; fi
  done
fi
if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  if [ "$yapoc_os" = macOS ] && command -v brew >/dev/null 2>&1; then
    printf 'Node.js 22+ is required. Install Node 22 with Homebrew? [y/N]: ' > /dev/tty
    IFS= read -r yapoc_answer < /dev/tty
    case "$yapoc_answer" in
      y|Y|yes|YES)
        brew install node@22
        export PATH="$(brew --prefix node@22)/bin:$PATH"
        ;;
      *) echo 'Install Node.js 22+ from https://nodejs.org/en/download and run setup again.'; exit 1 ;;
    esac
  else
    printf 'Install Node.js 22+ for %s from https://nodejs.org/en/download and run setup again.\n' "$yapoc_os" >&2
    exit 1
  fi
fi
node -e 'if(Number(process.versions.node.split(".")[0])<22)process.exit(1)'
if [ -n "${YAPOC_LOCAL_INSTALLER:-}" ]; then
  exec node "$YAPOC_LOCAL_INSTALLER" "$@" </dev/tty
fi
temporary="$(mktemp -d)"
trap 'rm -f "$temporary/install.mjs"; rmdir "$temporary"' EXIT
curl -fsSL "https://raw.githubusercontent.com/kuweg/yapoc/$ref/installer/index.mjs" -o "$temporary/install.mjs"
node "$temporary/install.mjs" --ref "$ref" "$@" </dev/tty
