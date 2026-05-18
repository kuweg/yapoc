#!/usr/bin/env bash
# YAPOC one-line installer.
#
# Usage (after the repo is published):
#   curl -fsSL https://raw.githubusercontent.com/kuweg/yapoc/main/scripts/install.sh | bash
#
# Or with auto-yes (assume yes for every prompt):
#   curl -fsSL https://raw.githubusercontent.com/kuweg/yapoc/main/scripts/install.sh | bash -s -- --yes
#
# Environment overrides:
#   INSTALL_DIR=/path/to/dir   Where to clone YAPOC. Default: $HOME/yapoc.
#   YAPOC_REPO=<git-url>       Override the repo to clone (for forks).
#   YAPOC_BRANCH=main          Branch to check out.
#
# Guarantees:
#   - Never runs as root. Aborts immediately if EUID == 0.
#   - Never edits shell rc files. PATH hints are printed; user copies them.
#   - Never calls sudo without a confirmation prompt and a printed reason.
#   - Idempotent: re-running detects an existing checkout and runs `git pull`.

set -euo pipefail

# ── globals ────────────────────────────────────────────────────────────────────

YAPOC_REPO="${YAPOC_REPO:-https://github.com/kuweg/yapoc.git}"
YAPOC_BRANCH="${YAPOC_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/yapoc}"
ASSUME_YES="false"
SKIP_FRONTEND="false"

# Style: bold yellow header, dim grey notes.
HDR="$(printf '\033[1;33m')"
DIM="$(printf '\033[2m')"
ERR="$(printf '\033[1;31m')"
OK="$(printf '\033[1;32m')"
RST="$(printf '\033[0m')"

# ── parse args ─────────────────────────────────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES="true" ;;
        --skip-frontend) SKIP_FRONTEND="true" ;;
        -h|--help)
            sed -n '2,19p' "$0"
            exit 0
            ;;
        *)
            printf '%sunknown flag:%s %s\n' "$ERR" "$RST" "$arg" >&2
            exit 2
            ;;
    esac
done

# ── helpers ────────────────────────────────────────────────────────────────────

log()  { printf '%s>%s %s\n' "$HDR" "$RST" "$*"; }
info() { printf '%s  %s%s\n' "$DIM" "$*" "$RST"; }
fail() { printf '%sx%s %s\n' "$ERR" "$RST" "$*" >&2; exit 1; }
ok()   { printf '%sv%s %s\n' "$OK" "$RST" "$*"; }

run() {
    printf '%s+ %s%s\n' "$DIM" "$*" "$RST"
    "$@"
}

confirm() {
    if [[ "$ASSUME_YES" == "true" ]]; then
        return 0
    fi
    local prompt="${1:-Continue?} [y/N] "
    local reply
    read -r -p "$prompt" reply </dev/tty || return 1
    [[ "$reply" =~ ^[Yy]$ ]]
}

on_error() {
    printf '\n%sinstall failed at line %s%s\n' "$ERR" "$1" "$RST" >&2
    printf '%sLast successful step was logged above. Re-run with --yes to retry.%s\n' "$DIM" "$RST" >&2
}
trap 'on_error $LINENO' ERR

# ── refuse root ────────────────────────────────────────────────────────────────

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    fail "Do not run this installer as root. Run as your normal user; we'll ask for sudo only when needed."
fi

# ── OS detection ───────────────────────────────────────────────────────────────

OS_KIND=""
PKG_MGR=""
case "$(uname -s)" in
    Linux)
        OS_KIND="linux"
        if   command -v apt-get >/dev/null 2>&1; then PKG_MGR="apt"
        elif command -v dnf      >/dev/null 2>&1; then PKG_MGR="dnf"
        elif command -v pacman   >/dev/null 2>&1; then PKG_MGR="pacman"
        fi
        ;;
    Darwin)
        OS_KIND="macos"
        if command -v brew >/dev/null 2>&1; then PKG_MGR="brew"; fi
        ;;
    *)
        fail "Unsupported OS: $(uname -s). Follow the manual README install."
        ;;
esac

log "YAPOC installer — OS: $OS_KIND, package manager: ${PKG_MGR:-none-detected}"
log "Install dir:    $INSTALL_DIR"
log "Repo / branch:  $YAPOC_REPO ($YAPOC_BRANCH)"

confirm "Proceed?" || fail "Aborted."

# ── pre-checks (read-only) ─────────────────────────────────────────────────────

check_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        case "$OS_KIND-$PKG_MGR" in
            macos-brew)  fail "Python 3 not found. Install with: brew install python@3.12" ;;
            linux-apt)   fail "Python 3 not found. Install with: sudo apt install python3.12 python3-pip" ;;
            linux-dnf)   fail "Python 3 not found. Install with: sudo dnf install python3.12" ;;
            linux-pacman)fail "Python 3 not found. Install with: sudo pacman -S python" ;;
            *)           fail "Python 3 not found. Install Python 3.12 or newer." ;;
        esac
    fi
    local v
    v="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    case "$v" in
        3.12|3.13|3.14|3.15|3.16) ok "Python $v" ;;
        *)  fail "Python $v is too old. YAPOC requires Python 3.12+." ;;
    esac
}

check_git() {
    command -v git >/dev/null 2>&1 || fail "git not found. Install git and re-run."
    ok "git $(git --version | awk '{print $3}')"
}

log "Pre-checks"
check_python
check_git

# ── Poetry ─────────────────────────────────────────────────────────────────────

install_poetry() {
    log "Poetry"
    if command -v poetry >/dev/null 2>&1; then
        ok "poetry $(poetry --version 2>/dev/null | awk '{print $NF}')"
        return
    fi

    if command -v pipx >/dev/null 2>&1; then
        info "Installing Poetry via pipx (no sudo)…"
        run pipx install poetry
    else
        info "pipx not found. Falling back to the official Poetry installer."
        info "(Runs python3 - to pipe the installer; no sudo, installs under \$HOME.)"
        if ! confirm "Install Poetry now?"; then
            fail "Poetry is required."
        fi
        run bash -c 'curl -sSL https://install.python-poetry.org | python3 -'
    fi

    # Poetry might land in ~/.local/bin (pipx) or ~/.local/share/pypoetry/bin (curl|python).
    if ! command -v poetry >/dev/null 2>&1; then
        info "Poetry installed but not on PATH. Add this to your shell rc and re-source it:"
        info '  export PATH="$HOME/.local/bin:$PATH"'
        fail "Re-run the installer once PATH is updated."
    fi
    ok "poetry installed"
}

install_poetry

# ── Redis ──────────────────────────────────────────────────────────────────────

install_redis() {
    log "Redis"
    if command -v redis-server >/dev/null 2>&1; then
        ok "redis-server present"
        return
    fi
    case "$OS_KIND-$PKG_MGR" in
        macos-brew)
            info "Installing redis via Homebrew (no sudo)…"
            run brew install redis
            ;;
        linux-apt)
            info "redis-server not found. Will install via: sudo apt install redis-server"
            if confirm "Run sudo apt install redis-server?"; then
                run sudo apt update
                run sudo apt install -y redis-server
            else
                info "Skipped. Set REDIS_URL to a reachable Redis or install manually before running YAPOC."
                return
            fi
            ;;
        linux-dnf)
            info "redis-server not found. Will install via: sudo dnf install redis"
            if confirm "Run sudo dnf install redis?"; then
                run sudo dnf install -y redis
            else
                return
            fi
            ;;
        linux-pacman)
            info "redis-server not found. Will install via: sudo pacman -S redis"
            if confirm "Run sudo pacman -S redis?"; then
                run sudo pacman -S --noconfirm redis
            else
                return
            fi
            ;;
        *)
            info "No package manager detected. Install redis-server manually and ensure it listens on :6379."
            return
            ;;
    esac
    ok "redis-server installed"
}

install_redis

# ── Clone the repo ─────────────────────────────────────────────────────────────

clone_repo() {
    log "Source"
    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ -d "$INSTALL_DIR/.git" ]] && \
           git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null \
               | grep -q "yapoc"; then
            info "Existing YAPOC checkout at $INSTALL_DIR — updating."
            run git -C "$INSTALL_DIR" fetch --quiet origin "$YAPOC_BRANCH"
            run git -C "$INSTALL_DIR" checkout "$YAPOC_BRANCH"
            run git -C "$INSTALL_DIR" pull --ff-only
        else
            fail "$INSTALL_DIR exists but is not a YAPOC checkout. Move or remove it first."
        fi
    else
        run git clone --branch "$YAPOC_BRANCH" "$YAPOC_REPO" "$INSTALL_DIR"
    fi
    ok "source ready at $INSTALL_DIR"
}

clone_repo

# ── poetry install ─────────────────────────────────────────────────────────────

log "Python dependencies"
( cd "$INSTALL_DIR" && run poetry install --no-interaction )
ok "poetry dependencies installed"

# ── hand off to the Python wizard ─────────────────────────────────────────────

log "Configuration wizard"
if [[ "$ASSUME_YES" == "true" ]] && [[ ! -t 0 ]]; then
    info "stdin is not a TTY (--yes passed). Skipping interactive wizard."
    info "Run [poetry run yapoc init] from inside $INSTALL_DIR when you're ready."
else
    # The wizard handles provider pick, key validation, .env write, and
    # agent-settings rewrite. Drop into the repo directory first so relative
    # paths in the wizard line up.
    ( cd "$INSTALL_DIR" && poetry run yapoc init )
fi

# ── preflight ──────────────────────────────────────────────────────────────────

log "Preflight"
( cd "$INSTALL_DIR" && poetry run yapoc doctor ) || \
    info "Preflight reported failures. Review the table above and fix the red rows."

# ── done ───────────────────────────────────────────────────────────────────────

echo
ok "YAPOC installed. To start using it:"
printf '   %scd %s%s\n' "$DIM" "$INSTALL_DIR" "$RST"
printf '   %spoetry run yapoc start%s   # background daemon\n' "$DIM" "$RST"
printf '   %spoetry run yapoc%s         # interactive REPL\n' "$DIM" "$RST"
echo
