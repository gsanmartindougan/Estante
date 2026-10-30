#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
exec python3 gtk_app/estante.py "$@"
