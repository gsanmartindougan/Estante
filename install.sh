#!/bin/sh
set -eu
INSTALL_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_PYTHON=python3
INSTALL_FRONTEND=slint
if [ "${1-}" = qt ] || [ "${1-}" = slint ]; then
    INSTALL_FRONTEND=$1
    shift
    set -- --frontend "$INSTALL_FRONTEND" "$@"
fi
for option in "$@"; do
    case "$option" in
        qt|--frontend=qt) INSTALL_FRONTEND=qt ;;
        slint|--frontend=slint) INSTALL_FRONTEND=slint ;;
    esac
done
if [ "$INSTALL_FRONTEND" = qt ] && [ -x "$INSTALL_SOURCE/.venv-qt/bin/python" ]; then
    INSTALL_PYTHON="$INSTALL_SOURCE/.venv-qt/bin/python"
fi
exec "$INSTALL_PYTHON" "$INSTALL_SOURCE/packaging/install.py" --python "$INSTALL_PYTHON" "$@"
