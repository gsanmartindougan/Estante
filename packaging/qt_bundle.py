"""Build the Qt AppDir using the interpreter and Qt wheels of the build environment."""
import ctypes.util
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig

ROOT=Path(__file__).resolve().parents[1]


def prepare(appdir):
    subprocess.run([sys.executable,str(ROOT/'install.py'),'--frontend','qt','--prefix','/usr','--destdir',str(appdir)],check=True)
    libraries=appdir/'usr/lib'; libraries.mkdir(parents=True,exist_ok=True)
    version='python'+sysconfig.get_python_version()
    pythonlib=libraries/version
    shutil.copytree(sysconfig.get_path('stdlib'),pythonlib,ignore=shutil.ignore_patterns('site-packages','dist-packages','__pycache__','test','tests','idlelib','tkinter','_tkinter*','ensurepip'),dirs_exist_ok=True)
    sites=pythonlib/'site-packages'; sites.mkdir(exist_ok=True)
    sources={}
    for name in ('PySide6','shiboken6'):
        spec=importlib.util.find_spec(name)
        if not spec or not spec.origin: raise RuntimeError('Falta '+name+' en el intérprete de construcción')
        source=Path(spec.origin).parent
        sources[name]=source
        shutil.copytree(source,sites/name,ignore=shutil.ignore_patterns('__pycache__','include','glue','typesystems','doc','examples'),dirs_exist_ok=True)
    shutil.copy2(Path(sys.executable).resolve(),appdir/'usr/bin/python3')
    pyside=sources['PySide6']
    seeds=[Path(sys.executable).resolve(),*[p for p in Path(sysconfig.get_path('stdlib')).glob('lib-dynload/*.so') if not p.name.startswith('_tkinter')]]
    for module in ('QtCore','QtGui','QtQml','QtQuick','QtWidgets','QtNetwork','QtDBus','QtSvg','QtOpenGL'):
        seeds.extend(pyside.glob(module+'.*.so'))
    for folder in ('platforms','imageformats','iconengines','tls','xcbglintegrations','wayland-shell-integration','wayland-graphics-integration-client'):
        seeds.extend((pyside/'Qt/plugins'/folder).glob('*.so'))
    for folder in ('QtQuick','QtQml','QtCore','Qt'):
        seeds.extend((pyside/'Qt/qml'/folder).rglob('*.so'))
    sdl=ctypes.util.find_library('SDL2-2.0') or ctypes.util.find_library('SDL2')
    if not sdl: raise RuntimeError('Falta SDL2 en el sistema de construcción')
    candidates=[Path('/usr/lib')/sdl,Path('/usr/lib/x86_64-linux-gnu')/sdl]
    sdlpath=next((p for p in candidates if p.exists()),None)
    if not sdlpath: raise RuntimeError('No se pudo localizar '+sdl)
    seeds.append(sdlpath); shutil.copy2(sdlpath,libraries/'libSDL2-2.0.so.0')
    for binary in seeds:
        result=subprocess.run(['ldd',str(binary)],capture_output=True,text=True)
        if 'not found' in result.stdout: raise RuntimeError('Dependencia ausente para '+str(binary)+': '+result.stdout)
        for name in re.findall(r'(?:=>\s*)?(/[^\s]+)\s+\(',result.stdout):
            source=Path(name)
            if source.is_relative_to(pyside) or source.is_relative_to(sources['shiboken6']): continue
            target=libraries/source.name
            if not target.exists(): shutil.copy2(source,target)
    loader=next((p for p in (Path('/lib64/ld-linux-x86-64.so.2'),Path('/usr/lib/ld-linux-x86-64.so.2')) if p.exists()),None)
    if loader is None: raise RuntimeError('Falta el cargador ELF x86_64')
    shutil.copy2(loader,libraries/'ld-linux-x86-64.so.2')
    cert=next((p for p in (Path('/etc/ssl/cert.pem'),Path('/etc/ssl/certs/ca-certificates.crt')) if p.is_file()),None)
    if cert:
        target=appdir/'etc/ssl/cert.pem';target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(cert,target)
    for suffix in ('.desktop','.svg'):
        shutil.copy2(ROOT/'packaging'/('io.github.estante.Launcher'+suffix),appdir/('io.github.estante.Launcher'+suffix))
    shutil.copy2(ROOT/'packaging/io.github.estante.Launcher.svg',appdir/'.DirIcon')
    script='''#!/bin/sh
set -eu
ESTANTE_APPDIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export ESTANTE_APPDIR
export ESTANTE_HOST_PYTHONHOME="${PYTHONHOME-}"
export ESTANTE_HOST_PYTHONPATH="${PYTHONPATH-}"
export ESTANTE_HOST_QT_PLUGIN_PATH="${QT_PLUGIN_PATH-}"
export ESTANTE_HOST_QML_IMPORT_PATH="${QML_IMPORT_PATH-}"
export ESTANTE_HOST_QT_QPA_PLATFORM_PLUGIN_PATH="${QT_QPA_PLATFORM_PLUGIN_PATH-}"
export ESTANTE_HOST_SSL_CERT_FILE="${SSL_CERT_FILE-}"
export PYTHONHOME="$ESTANTE_APPDIR/usr"
export PYTHONPATH="$ESTANTE_APPDIR/usr/lib/PYVERSION/site-packages"
export QT_PLUGIN_PATH="$PYTHONPATH/PySide6/Qt/plugins"
export QML_IMPORT_PATH="$PYTHONPATH/PySide6/Qt/qml"
export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PLUGIN_PATH/platforms"
export SSL_CERT_FILE="$ESTANTE_APPDIR/etc/ssl/cert.pem"
exec "$ESTANTE_APPDIR/usr/lib/ld-linux-x86-64.so.2" --library-path "$ESTANTE_APPDIR/usr/lib" "$ESTANTE_APPDIR/usr/bin/python3" "$ESTANTE_APPDIR/usr/share/estante/estante_qt.py" "$@"
'''.replace('PYVERSION',version)
    (appdir/'AppRun').write_text(script);(appdir/'AppRun').chmod(0o755)
    return appdir
