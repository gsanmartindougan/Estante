#!/usr/bin/env python3
"""Build the primary offline Rust/Slint AppImage.

Uses the runtime and tools from appimage-builder's AppImage. Cross-distribution
validation is still required before publishing; no files are uploaded here.
"""
import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import runpy

ROOT = Path(__file__).resolve().parents[1]
APP_ID = 'io.github.estante.Launcher'
VERSION = runpy.run_path(str(ROOT / 'packaging/install.py'))['VERSION']


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def dependencies(binary):
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True)
    if 'not found' in result.stdout:
        raise RuntimeError('Dependencia ausente: ' + result.stdout)
    return [Path(value) for value in re.findall(r'(?:=>\s*)?(/[^\s]+)\s+\(', result.stdout)]


def prepare_rust(appdir):
    if platform.machine() != 'x86_64':
        raise RuntimeError('Este constructor admite x86_64; no genera imágenes ARM.')
    binary = ROOT / 'rust/target/release/estante'
    if not shutil.which('cargo'):
        if not binary.is_file():
            raise RuntimeError('Falta cargo para compilar el frontend Rust.')
    else:
        subprocess.run(['cargo', 'build', '--release', '--manifest-path',
                        str(ROOT / 'rust/Cargo.toml')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'packaging/install.py'),
                    '--prefix', '/usr', '--destdir', str(appdir)], check=True)

    libraries = appdir / 'usr/lib'
    libraries.mkdir(parents=True, exist_ok=True)
    pending = [binary]
    seen = set()
    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        for dependency in dependencies(source):
            target = libraries / dependency.name
            if not target.exists():
                resolved = dependency.resolve()
                copy(resolved, target)
                pending.append(resolved)

    loader = next((path for path in (Path('/lib64/ld-linux-x86-64.so.2'),
                                    Path('/usr/lib/ld-linux-x86-64.so.2')) if path.is_file()), None)
    if loader is None:
        raise RuntimeError('Falta el cargador ELF x86_64.')
    copy(loader.resolve(), libraries / 'ld-linux-x86-64.so.2')
    script = '''#!/bin/sh
set -eu
ESTANTE_APPDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export ESTANTE_APPDIR
export ESTANTE_ASSET_DIR="$ESTANTE_APPDIR/usr/share/estante/assets"
LOADER="$ESTANTE_APPDIR/usr/lib/ld-linux-x86-64.so.2"
LIBRARIES="$ESTANTE_APPDIR/usr/lib"
PROGRAM="$ESTANTE_APPDIR/usr/bin/estante"
if [ "${1-}" = "--self-test" ]; then
    "$LOADER" --library-path "$LIBRARIES" "$PROGRAM" --version
    for image in 1.png 2.png 3.png 4.png 5.png 6.png; do
        test -s "$ESTANTE_ASSET_DIR/backgrounds/$image"
    done
    exit 0
fi
exec "$LOADER" --library-path "$LIBRARIES" "$PROGRAM" "$@"
'''
    (appdir / 'AppRun').write_text(script)
    (appdir / 'AppRun').chmod(0o755)
    return appdir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builder', type=Path, default=Path.home() / 'Applications/appimagebuilder.appimage')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--appdir-only', action='store_true')
    args = parser.parse_args()
    default_name = f'Estante-{VERSION}-x86_64.AppImage'
    output = (args.output or ROOT / 'dist' / default_name).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    appdir = output.parent / (
        'Estante.AppDir' if args.output is None
        else output.stem + '.AppDir'
    )
    if appdir.exists():
        raise RuntimeError(str(appdir) + ' ya existe. Muévelo o elimínalo antes de reconstruir.')
    prepare_rust(appdir)
    with tempfile.TemporaryDirectory(prefix='estante-cache-check-') as cache:
        subprocess.run([str(appdir / 'AppRun'), '--self-test'], check=True,
                       env={**os.environ, 'XDG_CACHE_HOME': cache})
    if args.appdir_only:
        print(appdir)
        return
    builder = args.builder.expanduser().resolve()
    if not builder.is_file():
        raise RuntimeError('No se encuentra appimage-builder AppImage; indica --builder /ruta/al/archivo.AppImage')
    # Reuse the installed builder's generic Type-2 runtime and compression tool.
    # Both are obtained locally; no runtime is downloaded and no FUSE is required.
    offset = int(subprocess.check_output([str(builder), '--appimage-offset'], text=True).strip())
    with tempfile.TemporaryDirectory(prefix='.estante-appimage-', dir=output.parent) as directory:
        work = Path(directory)
        subprocess.run([str(builder), '--appimage-extract'], cwd=work, check=True, stdout=subprocess.DEVNULL)
        tool = work / 'squashfs-root/usr/bin/mksquashfs'
        if not tool.is_file():
            raise RuntimeError('El AppImage de appimage-builder no incluye mksquashfs.')
        squash = work / 'estante.squashfs'
        # The tool may have a relative ELF interpreter intended for its own AppRun.
        subprocess.run(['/lib64/ld-linux-x86-64.so.2', str(tool), str(appdir), str(squash),
                        '-noappend', '-all-root', '-comp', 'gzip', '-processors', '2'], check=True)
        candidate = work / output.name
        with candidate.open('wb') as target, builder.open('rb') as runtime, squash.open('rb') as filesystem:
            target.write(runtime.read(offset))
            shutil.copyfileobj(filesystem, target)
        candidate.chmod(0o755)
        check = work / 'check'
        check.mkdir()
        subprocess.run([str(candidate), '--appimage-extract'], cwd=check, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(check / 'squashfs-root/AppRun'), '--self-test'], check=True,
                       env={**os.environ, 'XDG_CACHE_HOME': str(check / 'cache')})
        # Replace atomically, including when the previous AppImage is running.
        os.replace(candidate, output)
    print('AppImage generado y comprobado: ' + str(output))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
