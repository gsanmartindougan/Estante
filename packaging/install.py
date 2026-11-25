#!/usr/bin/env python3
"""Install Estante's primary Rust/Slint application."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
APP_ID = 'io.github.estante.Launcher'
DOCUMENTS = ('README.md', 'README.en.md')
ASSETS = (
    tuple(
        str(path.relative_to(SOURCE))
        for path in sorted((SOURCE / 'assets/backgrounds').glob('*'))
        if path.is_file()
    )
    + tuple(
        str(path.relative_to(SOURCE))
        for path in sorted((SOURCE / 'assets/controller').rglob('*'))
        if path.is_file()
    )
)
VERSION_TEXT = (SOURCE / 'rust/Cargo.toml').read_text(encoding='utf-8')
VERSION_MATCH = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', VERSION_TEXT)
if VERSION_MATCH is None:
    raise RuntimeError('Could not read the application version from rust/Cargo.toml')
VERSION = VERSION_MATCH.group(1)


def main():
    parser = argparse.ArgumentParser(description='Install Estante for your user or system-wide.')
    parser.add_argument('--version', action='version', version='Estante ' + VERSION)
    location = parser.add_mutually_exclusive_group()
    location.add_argument('--user', action='store_true', help='Install to ~/.local (default)')
    location.add_argument('--system', action='store_true', help='Install to /usr/local; requires administrator privileges')
    location.add_argument('--prefix', type=Path, help='Custom installation prefix')
    parser.add_argument('--destdir', type=Path, help='Temporary root for package staging')
    parser.add_argument('--uninstall', action='store_true', help='Uninstall while preserving personal data')
    args = parser.parse_args()

    prefix = (args.prefix or (Path('/usr/local') if args.system else Path.home() / '.local')).expanduser().absolute()
    root = args.destdir.absolute() / prefix.relative_to('/') if args.destdir else prefix
    app = root / 'share/estante'
    desktop = root / 'share/applications' / (APP_ID + '.desktop')
    icon = root / 'share/icons/hicolor/scalable/apps' / (APP_ID + '.svg')
    launcher = root / 'bin/estante'
    payload = (*DOCUMENTS, *ASSETS)
    files = [app / name for name in payload] + [desktop, icon, launcher]

    if args.uninstall:
        for target in files:
            target.unlink(missing_ok=True)
        if app.exists():
            for directory in sorted(
                (path for path in app.rglob('*') if path.is_dir()),
                key=lambda path: len(path.parts),
                reverse=True,
            ):
                if not any(directory.iterdir()):
                    directory.rmdir()
            if not any(app.iterdir()):
                app.rmdir()
        print('Estante uninstalled. Your games, settings and artwork remain untouched.')
    else:
        rust_binary = SOURCE / 'rust/target/release/estante'
        rust_sources = [
            path for path in (SOURCE / 'rust').rglob('*')
            if path.is_file() and 'target' not in path.parts
        ]
        rust_stale = not rust_binary.is_file() or any(
            path.stat().st_mtime_ns > rust_binary.stat().st_mtime_ns
            for path in rust_sources
        )
        if rust_stale:
            if not shutil.which('cargo'):
                parser.exit(1, 'Cargo is missing. Install Rust and run the installer again.\n')
            subprocess.run(
                ['cargo', 'build', '--release', '--manifest-path', str(SOURCE / 'rust/Cargo.toml')],
                check=True,
            )

        for name in payload:
            if not (SOURCE / name).is_file():
                parser.exit(1, 'Incomplete package: missing ' + name + '\n')
        for target in (app, desktop.parent, icon.parent, launcher.parent):
            target.mkdir(parents=True, exist_ok=True)
        for name in payload:
            target = app / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
            target.chmod(0o644)

        shutil.copyfile(rust_binary, launcher)
        launcher.chmod(0o755)
        template = (SOURCE / 'packaging' / (APP_ID + '.desktop')).read_text()
        executable = (
            str(prefix / 'bin/estante')
            .replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('`', '\\`')
            .replace('$', '\\$')
            .replace('%', '%%')
        )
        desktop.write_text(template.replace('Exec=estante', 'Exec="' + executable + '"'))
        desktop.chmod(0o644)
        shutil.copyfile(SOURCE / 'packaging' / (APP_ID + '.svg'), icon)
        icon.chmod(0o644)
        print('Estante ' + VERSION + ' installed to ' + str(prefix))
        if not args.destdir:
            print('Open it from the applications menu or run: ' + str(launcher))

    if not args.destdir and shutil.which('update-desktop-database') and desktop.parent.is_dir():
        subprocess.run(['update-desktop-database', str(desktop.parent)], check=False)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        sys.exit('Permission denied. Use --user or run a system install with sudo.')
