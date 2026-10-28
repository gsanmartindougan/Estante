#!/bin/sh
set -eu
INSTALL_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_PYTHON=python3
INSTALL_FRONTEND=qt
for option in "$@"; do
    case "$option" in gtk|--frontend=gtk) INSTALL_FRONTEND=gtk ;; esac
done
if [ "$INSTALL_FRONTEND" = qt ] && [ -x "$INSTALL_SOURCE/.venv-qt/bin/python" ]; then
    INSTALL_PYTHON="$INSTALL_SOURCE/.venv-qt/bin/python"
fi
exec "$INSTALL_PYTHON" "$INSTALL_SOURCE/install.py" --python "$INSTALL_PYTHON" "$@"
