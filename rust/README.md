# Estante Slint

Slint is Estante's primary Linux frontend. Run it from the repository root with
`./run.sh` or with `cargo run --manifest-path rust/Cargo.toml`. The Qt frontend is legacy and remains
available explicitly through `./run-qt.sh`; do not run both frontends against the
same data at once. The artwork search and Steam metadata actions use `curl` for
HTTPS requests. Category icon downloads also use `rsvg-convert` to rasterize SVGs.

Install the primary Slint frontend from the checkout with `./install.sh`; this
builds the release binary when needed and installs the bundled backgrounds and
desktop entry. To install legacy Qt explicitly, use `./install.sh --frontend qt`.

Build the primary x86_64 AppImage with `python3 packaging/build-appimage.py`.
Build the legacy Qt AppImage with
`python3 packaging/build-appimage.py --frontend qt`. Use `--appdir-only` to
check the bundled executable and assets without the external AppImage builder.

The app reads the existing `library.json` and `settings.json` in
`$XDG_DATA_HOME/estante` (default `~/.local/share/estante`), preserves unknown
JSON fields, and writes updates atomically. Set `ESTANTE_DATA_DIR` to use a
separate profile. Do not run this frontend and the legacy Qt frontend against the
same data at the same time.

The primary Slint frontend includes the Steam, Faugus and Heroic imports, local
`.sh`/AppImage entries, editing, filtering, categories, and the Grid and List
layouts. Carousel and Sense remain part of the legacy Qt frontend. Visible
artwork loads asynchronously with bounded page caching.
Metadata lookup includes Steam and Wikidata; artwork lookup includes
SteamGridDB and IGDB. Batch scraping can be cancelled and merges results around
manual edits. SDL2 gamepad navigation, a built-in search keyboard, session
history, the idle slideshow and the configured while-playing behavior are also
ported. The `hide` behavior transfers a running game to a temporary `systemd-run`
user service, records its session and reopens the library state when the game
ends. Configured Steam, Faugus and Heroic background startup is included.

The Slint frontend is the primary development target. Qt remains available as a
legacy frontend; its sources and dependencies stay under `qt_app/` and
`requirements/qt.txt`. Remaining Slint gaps include the generic native input-method
bridge and diagnostics and tray icon/menu integration. `hide` requires a running
user systemd manager; if the transfer fails, Estante stays open and reports the
error.
Category settings now support reorder, rename, the default category, game search
and assignment, local icons, and Bootstrap/Iconify icon search. Release checks and
the keyboard can request COSMIC OSK or an active KWin virtual keyboard with the
configured built-in fallback. The generic compositor input method remains
unavailable. AppImage replacement is implemented, but has not been
exercised against a published update. The screensaver now has the six
bundled-background choices, lazy settings previews and a cross-fade between
slides. Bundled backgrounds can be located through `ESTANTE_ASSET_DIR` or beside
an installed executable; the Rust installer places them with the binary.
`playing_behavior=tray` currently minimizes the window; it does not yet create a
tray icon. Launcher settings show startup, closing and timeout states and allow
manual start/close.
