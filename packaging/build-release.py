#!/usr/bin/env python3
"""Create a source installer archive using an explicit file list."""
from pathlib import Path
import importlib.util
import tarfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', root / 'packaging/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
files = [*installer.DOCUMENTS, *installer.ASSETS, 'run.sh', 'install.sh',
         'packaging/install.py', 'packaging/build-appimage.py', 'packaging/build-release.py',
         'packaging/bwrap-appimage', 'packaging/io.github.estante.Launcher.desktop',
         'packaging/io.github.estante.Launcher.svg', 'docs/estructura-del-proyecto.md']
files.extend(str(path.relative_to(root)) for path in sorted((root / 'rust').rglob('*'))
             if path.is_file() and 'target' not in path.parts)
version = installer.VERSION
output = root / 'dist' / f'Estante-{version}-linux.tar.gz'
output.parent.mkdir(exist_ok=True)
with tarfile.open(output, 'w:gz') as archive:
    for name in dict.fromkeys(files):
        archive.add(root / name, arcname='Estante/' + name)
print(output)
