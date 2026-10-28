#!/usr/bin/env python3
"""Install Estante without pip, network access or a distribution-specific manager."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

MODULES = ('native_memory.py', 'background_jobs.py', 'game_supervisor.py', 'tray.py', 'screensaver_config.py', 'screensaver.py', 'game_session.py', 'profiling.py', 'image_cache.py', 'estante.py', 'appearance.py', 'carousel.py', 'controls.py', 'library.py',
           'metadata.py', 'settings_view.py', 'steam_artwork.py', 'igdb_artwork.py', 'version.py', 'updates.py', 'i18n.py', 'backgrounds.py', 'scraping.py', 'steam_import.py', 'heroic_import.py')
QT_FILES = tuple('qt_app/' + path.name for path in sorted((Path(__file__).resolve().parent / 'qt_app').iterdir()) if path.suffix in ('.py', '.qml', '.js'))
MODULES += ('tools/memory_fixture.py', 'estante_qt.py', 'requirements-qt.txt', *QT_FILES)
APP_ID = 'io.github.estante.Launcher'
SOURCE = Path(__file__).resolve().parent
DOCUMENTS = ('README.md', 'README.en.md')
ASSETS = ('packaging/io.github.estante.Launcher.svg',) + tuple(str(path.relative_to(SOURCE)) for path in sorted((SOURCE / 'assets/backgrounds').glob('*')) if path.is_file())


def main():
    from version import __version__
    parser = argparse.ArgumentParser(description='Instala Estante para tu usuario o para todo el sistema.')
    parser.add_argument('--frontend', choices=('gtk','qt'), default='qt')
    parser.add_argument('--python', default=None, help='Intérprete Python del lanzador instalado')
    parser.add_argument('--version', action='version', version='Estante ' + __version__)
    location = parser.add_mutually_exclusive_group()
    location.add_argument('--user', action='store_true', help='Instalar en ~/.local (predeterminado)')
    location.add_argument('--system', action='store_true', help='Instalar en /usr/local; necesita permisos de administrador')
    location.add_argument('--prefix', type=Path, help='Prefijo de instalación personalizado')
    parser.add_argument('--destdir', type=Path, help='Raíz temporal para construir paquetes')
    parser.add_argument('--uninstall', action='store_true', help='Desinstalar conservando los datos personales')
    args = parser.parse_args()
    prefix = (args.prefix or (Path('/usr/local') if args.system else Path.home() / '.local')).expanduser().absolute()
    root = args.destdir.absolute() / prefix.relative_to('/') if args.destdir else prefix
    app = root / 'share/estante'
    desktop = root / 'share/applications' / (APP_ID + '.desktop')
    icon = root / 'share/icons/hicolor/scalable/apps' / (APP_ID + '.svg')
    launcher = root / 'bin/estante'
    files = [app / name for name in (*MODULES, *DOCUMENTS, *ASSETS)] + [desktop, icon, launcher]
    if args.uninstall:
        for target in files:
            target.unlink(missing_ok=True)
        if app.exists():
            # Only bytecode generated for this application's modules is disposable.
            cache = app / '__pycache__'
            if cache.is_dir():
                for name in MODULES:
                    for compiled in cache.glob(Path(name).stem + '.*.pyc'):
                        compiled.unlink()
                if not any(cache.iterdir()):
                    cache.rmdir()
            for directory in (app / 'assets/backgrounds', app / 'assets'):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            for name in MODULES:
                module=Path(name)
                bytecode=app/module.parent/'__pycache__'
                if bytecode.is_dir():
                    for compiled in bytecode.glob(module.stem+'.*.pyc'): compiled.unlink()
            for directory in sorted((p for p in app.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                if not any(directory.iterdir()): directory.rmdir()
            if not any(app.iterdir()):
                app.rmdir()
        print('Estante desinstalado. Tus juegos, ajustes e imágenes se conservan.')
    else:
        if not args.destdir:
            probe = ("from PySide6 import QtCore, QtQuick, QtQml, QtWidgets, QtSvg" if args.frontend == 'qt' else
                     "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Gtk, Adw")
            check = subprocess.run([args.python or sys.executable, '-c', probe], capture_output=True, text=True)
            if check.returncode:
                parser.exit(1, 'Faltan dependencias del frontend ' + args.frontend + '. Consulta README.md.\n')
        for name in (*MODULES, *DOCUMENTS, *ASSETS):
            if not (SOURCE / name).is_file():
                parser.exit(1, 'Paquete incompleto: falta ' + name + '\n')
        for target in (app, desktop.parent, icon.parent, launcher.parent):
            target.mkdir(parents=True, exist_ok=True)
        for name in (*MODULES, *DOCUMENTS, *ASSETS):
            (app / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, app / name)
            (app / name).chmod(0o644)
        command = shlex.quote(str(prefix / 'share/estante' / ('estante_qt.py' if args.frontend == 'qt' else 'estante.py')))
        interpreter = shlex.quote(args.python) if args.python else '/usr/bin/env python3'
        launcher.write_text('#!/bin/sh\nexec ' + interpreter + ' ' + command + ' "$@"\n')
        launcher.chmod(0o755)
        text = (SOURCE / 'packaging' / (APP_ID + '.desktop')).read_text()
        # Desktop Exec uses its own quoting rules, rather than shell escaping.
        executable = str(prefix / 'bin/estante').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
        desktop.write_text(text.replace('Exec=estante', 'Exec="' + executable + '"') + 'X-Estante-Version=' + __version__ + '\n')
        desktop.chmod(0o644)
        shutil.copyfile(SOURCE / 'packaging' / (APP_ID + '.svg'), icon)
        icon.chmod(0o644)
        print('Estante ' + __version__ + ' instalado en ' + str(prefix))
        if not args.destdir:
            print('Ábrelo desde el menú de aplicaciones o ejecuta: ' + str(prefix / 'bin/estante'))
    if not args.destdir and shutil.which('update-desktop-database') and desktop.parent.is_dir():
        subprocess.run(['update-desktop-database', str(desktop.parent)], check=False)


if __name__ == '__main__':
    try:
        main()
    except PermissionError:
        sys.exit('Sin permisos de escritura. Usa --user o ejecuta la instalación --system con sudo.')
