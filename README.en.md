# Estante

Current version: **0.1.0** · [Documentación en español](README.md)

A simple native Linux game library inspired by Cartridges. Launch games from **Faugus Launcher**, **shell scripts** and **AppImages**, using a gamepad, keyboard or mouse.

Faugus games are imported directly: you do not need to create `.desktop` entries. Faugus keeps control of the runner, prefix and launch arguments.

## Install the AppImage

The **x86_64 AppImage** includes Python, GTK, libadwaita and SDL2. Faugus must be installed separately to launch its games.

We recommend [Gear Lever](https://flathub.org/apps/it.mijorus.gearlever) to manage the AppImage and add Estante to your application menu. Open `Estante-0.1.0-x86_64.AppImage` with Gear Lever and use its integration option.

You can also run the file directly:

```sh
chmod +x Estante-0.1.0-x86_64.AppImage
./Estante-0.1.0-x86_64.AppImage
```

If FUSE is unavailable:

```sh
./Estante-0.1.0-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

To uninstall, remove Estante through Gear Lever, or delete the AppImage if you manage it manually. Remove any extracted folder or manually created menu shortcut too. Your library, artwork and settings are preserved.

## Native installation

Requires Python 3, PyGObject, GTK **4.10 or newer**, libadwaita and SDL2 for gamepad support.

| Distribution | Dependencies |
| --- | --- |
| Fedora | `sudo dnf install python3 python3-gobject gtk4 libadwaita SDL2` |
| Arch / CachyOS | `sudo pacman -S python python-gobject gtk4 libadwaita sdl2` |
| Ubuntu 24.04+ / Debian 13+ | `sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 libsdl2-2.0-0` |

`sdl2-compat` can replace `sdl2` on distributions that provide it.

Extract `Estante-0.1.0-linux.tar.gz`, enter the `Estante` directory and run:

```sh
sh install.sh
```

This installs into `~/.local`, without administrator privileges. Launch Estante from the application menu or run `~/.local/bin/estante`. For all users, use `sudo sh install.sh --system` instead.

Run the new installer again to update. To uninstall, use the matching command from a copy of the installer:

```sh
sh install.sh --uninstall
# For a system-wide installation:
sudo sh install.sh --system --uninstall
```

If you used `--prefix`, supply the same prefix when updating or uninstalling. Personal data is preserved.

## Language

Estante follows the system language by default: **Spanish for Spanish systems, English for every other system language**.

Choose **Settings → Global → Language** to use the system language, Español or English. Save and reopen Estante to apply the change. Your game titles, category names and saved game information are preserved.

## Library and controls

- **Add** accepts `.sh` files and AppImages, including arguments and a working directory. Scripts run with Bash; AppImages need execute permission.
- Faugus games appear automatically. Use **Refresh** after adding games in Faugus. Its version must support `--game ID`.
- Choose **Grid**, **Carousel** or **Sense** in Settings. Each layout has independent cover format, corner radius, selection ring and hero position settings.
- Create, rename and delete categories in **Settings → Categories**. Assign them from **Edit → Categories** for each game.
- Choose portrait or square covers and banners from SteamGridDB, your computer or an image URL. SteamGridDB needs an API key; Steam offers 16:9 screenshots without credentials. IGDB supports games from other platforms using Twitch client credentials.
- Find game information through Wikidata or edit it manually. Playtime and completed sessions appear beside the selected game.

| Action | Keyboard | Gamepad |
| --- | --- | --- |
| Navigate | Arrow keys / Tab | D-pad / left stick |
| Confirm | Enter / Space | A / Cross |
| Back | Escape | B / Circle |
| Search | Ctrl+F or `/` | Select / Back; also X / Square |
| Previous / next letter | — | LB/RB · L1/R1 |
| Previous / next category | Page Up / Page Down | LT/RT · L2/R2 |
| Settings | Settings button | Start |

Click to select; double-click to play. In horizontal layouts, down opens the game actions and up returns to covers; directions are reversed when Carousel is at the bottom.

## Updates and local data

The version appears at the bottom of the library. In **Settings → Global → Updates**, use **Check for updates** and then **Download and install** to update the AppImage. Downloads are checked with SHA-256 before replacing the file. Reopen Estante to use the new version. Native installations link to the new installer instead.

Updates require a public GitHub release tagged `vX.Y.Z` with an asset named `Estante-X.Y.Z-x86_64.AppImage` and a SHA-256 digest provided by GitHub. No download starts until you request it.

Settings, credentials, artwork and statistics are stored in `~/.local/share/estante` or `$XDG_DATA_HOME/estante`. Do not share `settings.json`, which contains API credentials. Removing a game preserves its original file. Closing Estante leaves games running; sessions still running when Estante closes are not recorded.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 packaging/build-release.py
python3 packaging/build-appimage.py --builder ~/Applications/appimagebuilder.appimage
```

Builds go into `dist/`; nothing is uploaded automatically. The version is defined in `version.py`. To run from source, use `sh run.sh`. Graphical checks require a desktop session: `python3 tests/check_ui.py`.

The AppImage is built from the build machine's libraries. Graphical compatibility on other distributions still needs validation; an ARM build is not currently provided.
