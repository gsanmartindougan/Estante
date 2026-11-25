# Estante

Estante organizes a game library from Steam, Faugus, Heroic and local launchers.
The primary application uses Rust and Slint; Qt is no longer part of this
project.

## Features

- **List** and **Grid** views, navigable by keyboard or controller.
- Game imports, search, categories and editing.
- Per-game backgrounds, covers and logos with presentation settings.
- Session history, screensaver and a status bar with time, date and battery
  when the device exposes it.

Existing library and settings data remain under
`$XDG_DATA_HOME/estante` (usually `~/.local/share/estante`).

## Run and install

From source:

```sh
./run.sh
```

Install the native binary to `~/.local`:

```sh
./install.sh
```

The x86_64 AppImage is available from [GitHub Releases](https://github.com/gsanmartindougan/Estante/releases).
Install Faugus separately to launch its games.

## Build and package

```sh
cargo build --offline --release --manifest-path rust/Cargo.toml
python3 packaging/build-release.py
python3 packaging/build-appimage.py --appdir-only
```

A full AppImage build also needs appimage-builder. Python is used by the install
and packaging tools and by optional brand-asset tooling. The installed
application and its normal runtime do not depend on Python.

## Qt legacy project

The Qt frontend has moved into the sibling project `estante-qt-legacy`. Its
sources, dependencies, installer and documentation are kept there; they are not
included in the primary Estante binary or source archive.
