#!/bin/sh
set -eu
INSTALL_SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$INSTALL_SOURCE/packaging/install.py" "$@"
