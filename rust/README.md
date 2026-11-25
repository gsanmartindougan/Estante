# Estante Rust/Slint

Estante's primary Linux application is the Rust/Slint frontend. Run it from the
repository root with `./run.sh` or with:

```sh
cargo run --manifest-path rust/Cargo.toml
```

Install from the checkout with `./install.sh`; it builds the release binary
when needed and installs the desktop entry and bundled backgrounds.

The app reads the existing `library.json` and `settings.json` in
`$XDG_DATA_HOME/estante` (default `~/.local/share/estante`), preserves unknown
JSON fields and writes updates atomically. Set `ESTANTE_DATA_DIR` to use a
separate profile.

The Slint frontend includes Steam, Faugus and Heroic imports, local `.sh` and
AppImage entries, editing, filtering, categories, and the Grid and List layouts.
It also supports metadata and artwork search, SDL2 gamepad navigation, the
built-in search keyboard, session history, the idle slideshow and configured
while-playing behavior. It does not require Python at runtime.

Build the release binary and source archive from the repository root:

```sh
cargo build --offline --release --manifest-path rust/Cargo.toml
python3 packaging/build-release.py
```

The Qt legacy frontend is maintained separately in the sibling
`estante-qt-legacy` project. It shares the existing data format and
`$XDG_DATA_HOME/estante` directory; do not run both frontends against the same
library at the same time.
