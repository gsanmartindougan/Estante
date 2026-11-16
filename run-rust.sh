#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Avoid loading the GL/Mesa backend beside NVIDIA Vulkan unless explicitly overridden.
: "${WGPU_BACKEND:=vulkan}"
export WGPU_BACKEND
if [ "${ESTANTE_DEBUG:-0}" = 1 ]; then
    exec cargo run --profile dev --manifest-path "$ROOT/rust/Cargo.toml" -- "$@"
fi
exec cargo run --release --manifest-path "$ROOT/rust/Cargo.toml" -- "$@"
