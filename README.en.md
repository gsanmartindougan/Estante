# Estante

Version: **0.3.0** · [Documentación en español](README.md)

A simple native Linux game library inspired by Cartridges. Launch games from **Steam**, **Faugus Launcher**, **Heroic Games Launcher**, **shell scripts** and **AppImages**, using a gamepad, keyboard or mouse.

Faugus games are imported directly: you do not need to create `.desktop` entries. Faugus keeps control of the runner, prefix and launch arguments.

## Qt frontend (Linux)

The default frontend is now Qt Quick/PySide6. The previous GTK frontend remains
available through `./run-gtk.sh`.

```sh
python3 -m venv .venv-qt
.venv-qt/bin/pip install -r requirements-qt.txt
./run.sh
```

`./run.sh --games 100` uses a temporary test library. Do not run both frontends
against the same data simultaneously. Installation and AppImage builds default to
Qt; `--frontend gtk` selects the previous frontend. See the [Qt guide](qt_app/README.md)
and [migration evidence](docs/migracion-qt-2026-10-24.md) (Spanish).
The videos on this page show the Qt frontend in 0.3.0.

## AI-assisted development and human review

Estante was developed with the assistance of artificial intelligence to generate and modify code, documentation and tests. The project has undergone **thorough human review**, including validation of its behavior and design decisions.

AI is a development tool; responsibility for changes and published releases rests with the project maintainer. This review does not guarantee that the software is free of bugs. Please report any issues through the repository's issue tracker.

The configurable **screensaver** smoothly cycles through game backgrounds, unloads the library from memory and restores the selected game, category and search when you return. Enable it in Settings → Global → Screensaver. Idle activation stays disabled while playing. Timers accept 1–60 seconds or minutes, with game backgrounds or a selected bundled background. Adjustable dimming and proportional fitting support standard, ultrawide and portrait displays without excessively enlarging small images. The screensaver stays in the same window, also works from Settings, preserves unsaved edits and restores the selection on return.

**While playing**, in Global settings: keep open, hide and restore, show the screensaver until the game ends, or minimize to the system tray. Clicking the tray icon restores the window; if no tray is available, Estante stays visible.

## Layouts and videos

Choose a layout without changing your library. Each has independent cover, selection and background settings. These videos show **Estante 0.3.0 (Qt)**; click a preview to open its MP4.

### Grid

A cover grid with the selected game's information and activity in the right-hand panel. Customize portrait or square covers, their size and corner radius. Grid shows **10 games per page** by default; change it under **Settings → Grid → Pagination**. Browse with **L3 / R3**, LB/RB or the page buttons.

[![Grid preview](docs/showcase/01-grid.jpg)](docs/showcase/01-grid.mp4)



https://github.com/user-attachments/assets/6153c697-b3d7-4719-8077-ec1f9be05b9c



### Carousel

A horizontal wheel with depth and continuous circular navigation. The selected game stays centered with adjustable focus zoom. Place the wheel at the top or bottom while viewing the game's synopsis, information and activity.

[![Carousel preview](docs/showcase/02-carousel.jpg)](docs/showcase/02-carousel.mp4)



https://github.com/user-attachments/assets/1602fb11-a99e-485d-a255-3e0ba46edf85



### Sense

A compact cover row over the game's background. Selection stays anchored to the left while games move as you navigate. Adjust the selected cover's size and enable its gentle animation.

[![Sense preview](docs/showcase/03-sense.jpg)](docs/showcase/03-sense.mp4)



https://github.com/user-attachments/assets/5a80e739-cc28-4a9f-a033-06c0943ce49e



### List

A logo wheel highlights the selected game alongside its cover, synopsis and details. Place it on any of the four screen edges: navigation is vertical on the sides and horizontal at the top or bottom. Adjust logo size, selected logo size and cover size independently.

[![List preview](docs/showcase/04-list.jpg)](docs/showcase/04-list.mp4)



https://github.com/user-attachments/assets/fff8e42e-b4ea-47ca-90c7-e97b1c2d447d



### Settings

Global settings cover language, controller type, startup behavior, integrations and background source. Each layout has independent visual settings organized into collapsible sections. **L3 + R3** opens the current layout's settings directly; you can also use the gear button.

[![Settings preview](docs/showcase/05-settings.jpg)](docs/showcase/05-settings.mp4)



https://github.com/user-attachments/assets/abd091ee-4039-403d-bb5d-9cdd9117199f



## Install the AppImage

The **x86_64 AppImage** includes Python, Qt Quick/PySide6 and SDL2. Faugus must be installed separately to launch its games.

We recommend [Gear Lever](https://flathub.org/apps/it.mijorus.gearlever) to manage the AppImage and add Estante to your application menu. Open `Estante-0.3.0-x86_64.AppImage` with Gear Lever and use its integration option.

You can also run the file directly:

```sh
chmod +x Estante-0.3.0-x86_64.AppImage
./Estante-0.3.0-x86_64.AppImage
```

If FUSE is unavailable:

```sh
./Estante-0.3.0-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

To uninstall, remove Estante through Gear Lever, or delete the AppImage if you manage it manually. Remove any extracted folder or manually created menu shortcut too. Your library, artwork and settings are preserved.

## Native installation

Requires Python 3.10+, PySide6 and SDL2. Install SDL2 with your distribution's
package manager (`SDL2` on Fedora, `sdl2` on Arch, `libsdl2-2.0-0` on Debian/Ubuntu).

Extract `Estante-0.3.0-linux.tar.gz`, enter `Estante`, and use a persistent Qt environment:

```sh
python3 -m venv "$HOME/.local/share/estante-venv"
"$HOME/.local/share/estante-venv/bin/pip" install -r requirements-qt.txt
"$HOME/.local/share/estante-venv/bin/python" install.py --python "$HOME/.local/share/estante-venv/bin/python"
```

This installs into `~/.local` without administrator privileges. Launch Estante from
the menu or `~/.local/bin/estante`. Keep `estante-venv` after installation. The old
GTK frontend requires PyGObject, GTK 4.10+, libadwaita and `--frontend gtk`.

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

## Two backgrounds per game (0.2.1)

Choose the first image in **Edit → Change banner…** and the second in **Choose second background…**.
Both support the same image sources. In each layout's settings, **Background split** offers:

- **Single background**: the existing behavior.
- **Horizontal**: one image at the top and one at the bottom.
- **Vertical**: one image on the left and one on the right.
- **Diagonal**: divide the area between the two images diagonally.

Each layout saves its own split, dividing the entire window between both heroes.
Hero position controls cropping within each image's area, and background fill remains configurable;
blur and dominant-color fills use both images. A missing second image falls back to the first.
**Remove second background** clears its assignment without deleting the file or changing the first image.

## Library and controls

Settings keep their save button and confirmation messages fixed below the scrolling
content. Press **Y / Triangle** on the gamepad or **Ctrl+S** to save the current section.
Categories are saved through their create, rename and delete actions.

- **Add** accepts `.sh` files and AppImages, including arguments and a working directory. Scripts run with Bash; AppImages need execute permission.
- Import Faugus games manually through **Settings → Scan and scraping → Scan Faugus**. Repeat the scan to import new games or refresh their Faugus data. Its version must support `--game ID`.
- Choose **Grid**, **Carousel**, **Sense** or **List** in Settings. Each layout has independent cover format, corner radius, selection ring and hero position settings.
- Create, rename and delete categories in **Settings → Categories**. Assign them from **Edit → Categories** for each game.
- Assign optional category icons through **Choose icon…**. **Find icon…** searches Bootstrap Icons and Iconify with an editable query and selectable previews, without an API key. Switch providers, browse Bootstrap, and navigate results in pages of 12 icons. **Use text** restores the name. **All** can also have an icon; names remain available as tooltips and accessibility labels.
- Choose portrait or square covers and banners from SteamGridDB, your computer or an image URL. SteamGridDB needs an API key; Steam offers 16:9 screenshots without credentials. IGDB supports games from other platforms using Twitch client credentials.
- Find game information through Wikidata or edit it manually. Playtime and completed sessions appear beside the selected game.

| Action | Keyboard | Gamepad |
| --- | --- | --- |
| Navigate | Arrow keys / Tab | D-pad / left stick |
| Confirm | Enter / Space | A / Cross |
| Back | Escape | B / Circle |
| Search | Ctrl+F or `/` | Select / Back; also X / Square |
| Switch layout | Ctrl+Tab (Shift: previous) | LB + RB · L1 + R1 |
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

### List layout

Splits the library into logos on the left and game details on the right. Up/down, the D-pad or stick move through a circular vertical carousel with the selected game centered. The mouse wheel also changes games. Right opens Play/Edit; left returns to the list.

Logos load from SteamGridDB when an API key and an unambiguous match are available. Choose another through **Edit → Logo**, including local files or a URL. Games without a logo display their title. **Settings → List** provides independent logo size, selection ring and background settings. Ctrl+Tab or LB+RB include List when cycling layouts.

In **Settings → Categories**, search and assign games to each category, change their order with **Move up/Move down**, and choose the **default category** opened at startup. It defaults to **All**. This order is used by the category selector and controller triggers. Changes save automatically; renaming the default preserves it and deleting it falls back to All.


### Manual scanning and scraping

**Settings → Scan and scraping** imports Faugus games without modifying its files. Upgrading an existing library preserves a snapshot of the former automatic imports; subsequent imports require **Scan Faugus**.

Scraping processes the whole library, with artwork from SteamGridDB (requires a saved API key) and information from Wikidata. **Complete missing data** keeps valid images and populated fields; **Replace existing data** replaces available data while retaining anything without a new result. Ambiguous matches are skipped. Browsing no longer downloads images automatically. Individual image and metadata selection remains available through Edit.

### Importing Steam and Faugus

Use **Settings → Scan and scraping → Scan Steam / Scan Faugus**. Steam scans installed games from local manifests, including libraries on other drives, without account credentials or an API key. Proton, runtimes and common Steam tools are excluded. Games launch through their native or Flatpak Steam client.

Scans assign **Steam** and **Faugus** categories while retaining other categories and custom artwork. Faugus entries using the **Steam** runner or a `steam://` URI are skipped, including previously imported ones. Titles and executable names are not used to identify these duplicates. Steam and Faugus files are never modified.

Remove a game through **Edit → Organization → Remove from library**. Its files are not deleted or uninstalled. Removed Steam and Faugus games are excluded from future scans; restore them with their customizations from **Settings → Scan and scraping → Removed games → Restore removed games**. Local scripts and AppImages can be added again using Add.

**Settings → List → List position** places the wheel on the left, right, top or bottom, with details on the opposite side. Side wheels use up/down; top and bottom wheels use left/right. Move toward the details to focus Play/Edit and toward the wheel to return to the logos.

### Image decoding

Pillow is optional when running from source: it is used for large JPEGs requiring substantial downscaling if the system scaled decoder fails. Building the AppImage requires Pillow on the build machine and bundles it to avoid creating original-resolution JPEG textures for thumbnails. PNG keeps the GDK decoder and can still require its source buffer.


### Heroic Games Launcher

Open **Settings → Scan and scraping → Import games from Heroic**. Estante reads
native and Flatpak installations for installed Epic, GOG, Amazon and locally
sideloaded games, creating a Heroic category. Rescan after installing or removing
games. Artwork and category edits remain in Estante; Heroic configuration and
credentials are not modified.

Games start through Heroic with `--no-gui`, preserving its runner and prefix.
Session monitoring uses Heroic's per-game environment identifiers, including when
Heroic was already running. The 25-second starting screen, session recording and
selected playing behavior also apply. Available cached artwork URLs are downloaded
without a SteamGridDB key; artwork failures do not prevent importing a game.
