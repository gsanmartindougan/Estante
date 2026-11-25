"""The primary source archive contains only the Rust/Slint project."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTests(TestCase):
    def test_source_archive_is_slint_only_and_self_describing(self):
        spec = importlib.util.spec_from_file_location(
            'layout_installer', ROOT / 'packaging/install.py'
        )
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'source'
            source.mkdir()
            files = [
                *installer.DOCUMENTS,
                *installer.ASSETS,
                'run.sh',
                'install.sh',
                'packaging/install.py',
                'packaging/build-appimage.py',
                'packaging/build-release.py',
                'packaging/bwrap-appimage',
                'packaging/io.github.estante.Launcher.desktop',
                'packaging/io.github.estante.Launcher.svg',
                'docs/estructura-del-proyecto.md',
            ]
            for name in files:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            shutil.copytree(
                ROOT / 'rust',
                source / 'rust',
                ignore=shutil.ignore_patterns('target'),
            )

            build = subprocess.run(
                [sys.executable, str(source / 'packaging/build-release.py')],
                cwd=base,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            archive_path = source / 'dist' / f'Estante-{installer.VERSION}-linux.tar.gz'
            with tarfile.open(archive_path) as archive:
                names = archive.getnames()
                self.assertTrue(any(name.endswith('rust/Cargo.toml') for name in names))
                self.assertFalse(any('/qt_app/' in name for name in names))
                self.assertFalse(any('/core/' in name for name in names))
                self.assertFalse(any('/integrations/' in name for name in names))
                self.assertFalse(any('/requirements/qt.txt' in name for name in names))
                archive.extractall(base / 'extracted', filter='data')

            extracted = base / 'extracted/Estante'
            version = subprocess.check_output(
                [sys.executable, str(extracted / 'packaging/install.py'), '--version'],
                text=True,
            )
            self.assertEqual(version.strip(), 'Estante ' + installer.VERSION)
