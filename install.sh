#!/bin/sh
set -eu
INSTALL_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_PYTHON=python3
INSTALL_FRONTEND=qt
if [ "${1-}" = rust ]; then
    shift
    set -- --frontend rust "$@"
fi
for option in "$@"; do
    case "$option" in rust|--frontend=rust) INSTALL_FRONTEND=rust ;; esac
done
if [ "$INSTALL_FRONTEND" = qt ] && [ -x "$INSTALL_SOURCE/.venv-qt/bin/python" ]; then
    INSTALL_PYTHON="$INSTALL_SOURCE/.venv-qt/bin/python"
fi
exec "$INSTALL_PYTHON" "$INSTALL_SOURCE/packaging/install.py" --python "$INSTALL_PYTHON" "$@"
