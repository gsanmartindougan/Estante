#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ -n "${ESTANTE_QT_PYTHON:-}" ]; then
    QT_PYTHON=$ESTANTE_QT_PYTHON
elif [ -x .venv-qt/bin/python ]; then
    QT_PYTHON=./.venv-qt/bin/python
elif python3 -c 'import PySide6' 2>/dev/null; then
    QT_PYTHON=python3
elif [ -x /tmp/estante-qt-venv/bin/python ]; then
    QT_PYTHON=/tmp/estante-qt-venv/bin/python
else
    echo 'Instala el entorno Qt: python3 -m venv .venv-qt && .venv-qt/bin/pip install -r requirements-qt.txt' >&2
    exit 1
fi
exec "$QT_PYTHON" estante_qt.py "$@"
