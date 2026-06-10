#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${BONFIRE_VENV:-$HOME/.bonfire/venv}"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

if [ -t 1 ]; then
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    GREEN=$'\033[32m'
    CYAN=$'\033[36m'
    YELLOW=$'\033[33m'
    RED=$'\033[31m'
    RESET=$'\033[0m'
else
    BOLD="" DIM="" GREEN="" CYAN="" YELLOW="" RED="" RESET=""
fi

info()  { printf "${CYAN}=>${RESET} %s\n" "$*"; }
ok()    { printf "${GREEN}=>${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}=>${RESET} %s\n" "$*" >&2; }
err()   { printf "${RED}=>${RESET} %s\n" "$*" >&2; }

find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" > /dev/null 2>&1; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PYTHON_MAJOR, $MIN_PYTHON_MINOR) else 1)" 2>/dev/null; then
                echo "$cmd"
                return
            fi
        fi
    done
    echo ""
}

PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    err "python >= ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR} is required but not found"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
info "using python ${BOLD}${PYTHON_VERSION}${RESET} ${DIM}($(command -v "$PYTHON"))${RESET}"

info "creating virtualenv at ${BOLD}${VENV_DIR}${RESET} ..."
mkdir -p "$(dirname "$VENV_DIR")"
"$PYTHON" -m venv "$VENV_DIR"

info "installing crc-bonfire ..."
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install --upgrade crc-bonfire --quiet

BONFIRE_VERSION=$("${VENV_DIR}/bin/bonfire" version 2>/dev/null || echo "unknown")
echo ""
ok "${BOLD}bonfire ${BONFIRE_VERSION}${RESET} installed successfully!"
echo ""
echo -e "  add the following to your shell profile ${DIM}(~/.bashrc, ~/.zshrc, etc.)${RESET}:"
echo ""
echo -e "    ${YELLOW}export PATH=\"${VENV_DIR}/bin:\$PATH\"${RESET}"
echo ""
echo -e "  then restart your shell or run:"
echo ""
echo -e "    ${YELLOW}source ~/.bashrc${RESET}  ${DIM}# or ~/.zshrc${RESET}"
echo ""
