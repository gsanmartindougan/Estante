#!/usr/bin/env python3
"""Build an offline AppImage using the runtime/tools of appimage-builder's AppImage.

Bundles the build machine's Python/GTK stack. Cross-distribution validation is still
required before publishing; no files are uploaded by this script.
"""
import argparse
import ctypes.util
import importlib.util
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import runpy

ROOT = Path(__file__).resolve().parents[1]
APP_ID = 'io.github.estante.Launcher'
VERSION = runpy.run_path(str(ROOT / 'version.py'))['__version__']


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def dependencies(binary):
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True)
    if 'not found' in result.stdout:
        raise RuntimeError('Dependencia ausente: ' + result.stdout)
    return [Path(value) for value in re.findall(r'(?:=>\s*)?(/[^\s]+)\s+\(', result.stdout)]


def prepare(appdir):
    if platform.machine() != 'x86_64':
        raise RuntimeError('Este constructor admite x86_64; no genera imágenes ARM.')
    spec = importlib.util.spec_from_file_location('installer', ROOT / 'install.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    subprocess.run([sys.executable, str(ROOT / 'install.py'), '--prefix', '/usr', '--destdir', str(appdir)], check=True)
    libraries = appdir / 'usr/lib'
    version = 'python' + sysconfig.get_python_version()
    stdlib = Path(sysconfig.get_path('stdlib'))
    pythonlib = libraries / version
    shutil.copytree(stdlib, pythonlib, ignore=shutil.ignore_patterns('site-packages', 'dist-packages', '__pycache__', 'test', 'tests', 'idlelib', 'tkinter', '_tkinter*', 'ensurepip'), dirs_exist_ok=True)
    for module in ('gi', 'cairo'):
        found = importlib.util.find_spec(module)
        if not found or not found.origin:
            raise RuntimeError('Falta el módulo de construcción: ' + module)
        source = Path(found.origin).parent
        shutil.copytree(source, pythonlib / 'site-packages' / module,
                        ignore=shutil.ignore_patterns('__pycache__', 'include'), dirs_exist_ok=True)
    copy(Path(sys.executable).resolve(), appdir / 'usr/bin/python3')
    typelibs = libraries / 'girepository-1.0'
    typelib_sources = [Path('/usr/lib/girepository-1.0'), Path('/usr/lib/x86_64-linux-gnu/girepository-1.0')]
    wanted = ('Adw-1', 'Gtk-4.0', 'Gdk-4.0', 'Gsk-4.0', 'GdkPixbuf-2.0', 'Graphene-1.0',
              'GLib-2.0', 'GObject-2.0', 'Gio-2.0', 'Pango-1.0', 'PangoCairo-1.0',
              'GModule-2.0', 'HarfBuzz-0.0', 'cairo-1.0', 'freetype2-2.0', 'fontconfig-2.0',
              'GIRepository-2.0', 'GdkX11-4.0', 'GdkWayland-4.0')
    for name in wanted:
        source = next((directory / (name + '.typelib') for directory in typelib_sources
                       if (directory / (name + '.typelib')).is_file()), None)
        if source:
            copy(source, typelibs / source.name)
        elif name in wanted[:13]:
            raise RuntimeError('Falta el typelib: ' + name)
    libdirs = [Path('/usr/lib'), Path('/usr/lib/x86_64-linux-gnu')]
    seeds = []
    for name in ('gtk-4', 'adwaita-1', 'girepository-1.0', 'SDL2-2.0', 'SDL3', 'gdk_pixbuf-2.0',
                 'gio-2.0', 'graphene-1.0', 'pangocairo-1.0', 'gmodule-2.0', 'nss_dns', 'nss_files'):
        soname = ctypes.util.find_library(name)
        if soname:
            source = next((directory / soname for directory in libdirs if (directory / soname).exists()), None)
            if source:
                seeds.append(source)
        elif name in ('gtk-4', 'adwaita-1', 'SDL2-2.0'):
            raise RuntimeError('Falta la biblioteca: ' + name)
    for directory in libdirs:
        for relative in ('gio/modules', 'gdk-pixbuf-2.0', 'gtk-4.0', 'glycin-loaders'):
            source = directory / relative
            if source.is_dir():
                shutil.copytree(source, libraries / relative, dirs_exist_ok=True)
    # Recent GdkPixbuf versions use sandboxed out-of-process Glycin codecs.
    # Keep their sandbox, but expose the read-only bundle to it via a bwrap wrapper.
    if (libraries / 'glycin-loaders').is_dir():
        bwrap = shutil.which('bwrap')
        if not bwrap:
            raise RuntimeError('Falta bubblewrap para empaquetar los cargadores Glycin.')
        copy(bwrap, appdir / 'usr/bin/bwrap.bin')
        copy(ROOT / 'packaging/bwrap-appimage', appdir / 'usr/bin/bwrap')
        (appdir / 'usr/bin/bwrap').chmod(0o755)
        for binary in (libraries / 'glycin-loaders').rglob('glycin-*'):
            if not binary.is_file():
                continue
            wrapper = binary.with_name(binary.name + '.wrapper')
            wrapper.write_text('#!/bin/sh\nset -eu\n'
                'root=$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)\n'
                'exec "$root/usr/lib/ld-linux-x86-64.so.2" --library-path "$root/usr/lib" '
                '"${0%.wrapper}" "$@"\n')
            wrapper.chmod(0o755)
    seeds.extend(p for p in appdir.rglob('*') if p.is_file() and p.open('rb').read(4) == b'\x7fELF')
    seen = set()
    while seeds:
        source = seeds.pop()
        if source in seen:
            continue
        seen.add(source)
        for dependency in dependencies(source):
            target = libraries / dependency.name
            if not target.exists():
                copy(dependency.resolve(), target)
                seeds.append(dependency)
    # GI and SDL can dlopen libraries that do not occur in Python's ELF dependencies.
    for source in list(seen):
        if source.parent in libdirs and not (libraries / source.name).exists():
            copy(source.resolve(), libraries / source.name)
    loader = Path('/lib64/ld-linux-x86-64.so.2')
    copy(loader.resolve(), libraries / 'ld-linux-x86-64.so.2')
    schemas = Path('/usr/share/glib-2.0/schemas')
    shutil.copytree(schemas, appdir / 'usr/share/glib-2.0/schemas', dirs_exist_ok=True)
    subprocess.run(['glib-compile-schemas', str(appdir / 'usr/share/glib-2.0/schemas')], check=True)
    for name in ('Adwaita', 'hicolor'):
        source = Path('/usr/share/icons') / name
        if source.is_dir():
            shutil.copytree(source, appdir / 'usr/share/icons' / name, dirs_exist_ok=True)
    for source in (Path('/usr/share/mime'), Path('/usr/share/fontconfig'), Path('/usr/share/licenses'), Path('/usr/share/glycin-loaders')):
        if source.is_dir():
            shutil.copytree(source, appdir / 'usr/share' / source.name, dirs_exist_ok=True, ignore_dangling_symlinks=True)
    fonts = list(Path('/usr/share/fonts').rglob('DejaVuSans*.ttf'))
    for font in fonts:
        copy(font, appdir / 'usr/share/fonts' / font.name)
    (appdir / 'etc/fonts').mkdir(parents=True, exist_ok=True)
    (appdir / 'etc/fonts/fonts.conf').write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig><dir prefix="relative">../../usr/share/fonts</dir><dir>/usr/share/fonts</dir><dir prefix="xdg">fonts</dir><cachedir prefix="xdg">fontconfig</cachedir></fontconfig>')
    certificate = next((path for path in (Path('/etc/ssl/certs/ca-certificates.crt'), Path('/etc/pki/tls/certs/ca-bundle.crt')) if path.is_file()), None)
    if certificate:
        copy(certificate, appdir / 'etc/ssl/cert.pem')
    for name in (APP_ID + '.desktop', APP_ID + '.svg'):
        copy(ROOT / 'packaging' / name, appdir / name)
    with (appdir / (APP_ID + '.desktop')).open('a') as desktop:
        desktop.write('X-Estante-Version=' + VERSION + '\n')
    copy(ROOT / 'packaging' / (APP_ID + '.svg'), appdir / '.DirIcon')
    copy(ROOT / 'packaging/AppRun', appdir / 'AppRun')
    (appdir / 'AppRun').chmod(0o755)
    copy(ROOT / 'packaging/appimage-entry.py', appdir / 'usr/share/estante/appimage-entry.py')
    return appdir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builder', type=Path, default=Path.home() / 'Applications/appimagebuilder.appimage')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / f'Estante-{VERSION}-x86_64.AppImage')
    parser.add_argument('--appdir-only', action='store_true')
    args = parser.parse_args()
    output = args.output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    appdir = output.parent / 'Estante.AppDir'
    if appdir.exists():
        raise RuntimeError(str(appdir) + ' ya existe. Muévelo o elimínalo antes de reconstruir.')
    prepare(appdir)
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
