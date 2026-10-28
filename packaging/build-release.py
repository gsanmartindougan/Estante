#!/usr/bin/env python3
"""Create a source installer archive using an explicit file list."""
import importlib.util
from pathlib import Path
import tarfile
import runpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', root / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
files = [*installer.MODULES, *installer.DOCUMENTS, *installer.ASSETS, 'run.sh', 'run-qt.sh', 'run-gtk.sh', 'install.sh', 'install.py',
         'packaging/build-appimage.py', 'packaging/qt_bundle.py', 'packaging/AppRun', 'packaging/appimage-entry.py', 'packaging/bwrap-appimage',
         'packaging/io.github.estante.Launcher.desktop', 'packaging/io.github.estante.Launcher.svg']
version = runpy.run_path(str(root / 'version.py'))['__version__']
output = root / 'dist' / f'Estante-{version}-linux.tar.gz'
output.parent.mkdir(exist_ok=True)
with tarfile.open(output, 'w:gz') as archive:
    for name in dict.fromkeys(files):
        archive.add(root / name, arcname='Estante/' + name)
print(output)
