"""The organized source archive and detached session supervisor remain self-contained."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from core import game_supervisor
from core.version import __version__

ROOT=Path(__file__).resolve().parents[1]


class ProjectLayoutTests(TestCase):
    def test_source_archive_installs_and_starts_outside_checkout(self):
        spec=importlib.util.spec_from_file_location('layout_installer',ROOT/'packaging/install.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=base/'source';source.mkdir()
            files=[*installer.MODULES,*installer.DOCUMENTS,*installer.ASSETS,
                   'run.sh','run-qt.sh','run-gtk.sh','install.sh','packaging/install.py',
                   'packaging/build-appimage.py','packaging/build-release.py','packaging/qt_bundle.py',
                   'packaging/AppRun','packaging/appimage-entry.py','packaging/bwrap-appimage',
                   'packaging/io.github.estante.Launcher.desktop']
            for name in dict.fromkeys(files):
                target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,target)
            build=subprocess.run([sys.executable,str(source/'packaging/build-release.py')],cwd=base,capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            with tarfile.open(source/'dist'/f'Estante-{__version__}-linux.tar.gz') as archive:
                archive.extractall(base/'extracted',filter='data')
            extracted=base/'extracted/Estante'
            stage=base/'stage'
            subprocess.run([sys.executable,str(extracted/'packaging/install.py'),'--prefix','/opt/Test','--destdir',str(stage)],cwd=base,check=True,capture_output=True)
            entry=stage/'opt/Test/share/estante/qt_app/__main__.py'
            result=subprocess.check_output([sys.executable,'-I',str(entry),'--version'],cwd=base,text=True)
            self.assertEqual(result.strip(),'Estante '+__version__)
            for package in ('core','integrations','gtk_app','qt_app'):
                self.assertTrue((entry.parents[1]/package/'__init__.py').is_file())

    def test_detached_supervisor_has_all_required_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'session';folder.mkdir()
            (folder/'status.json').write_text(json.dumps({'state':'ready'}))
            process=SimpleNamespace(pid=123,estante_session_token='test')
            with patch.object(game_supervisor.tempfile,'mkdtemp',return_value=str(folder)),patch.object(game_supervisor.shutil,'which',return_value='/usr/bin/systemd-run'),patch.object(game_supervisor.subprocess,'run',return_value=SimpleNamespace(returncode=0)):
                game_supervisor.prepare({'id':'test'},process,temporary,'date',0,{})
            # Isolated Python cannot import from the original checkout accidentally.
            code='import sys;sys.path.insert(0,sys.argv[1]);from core.library import Library;from core.game_session import game_processes;from integrations.heroic_import import launch_url;print("SNAPSHOT_OK")'
            output=subprocess.check_output([sys.executable,'-I','-c',code,str(folder)],cwd=temporary,text=True)
            self.assertEqual(output.strip(),'SNAPSHOT_OK')
