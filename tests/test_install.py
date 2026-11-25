from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_staged_install_contains_only_slint_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source'
            source.mkdir()
            for relative in (
                'README.md',
                'README.en.md',
                'install.sh',
                'packaging/install.py',
                'packaging/io.github.estante.Launcher.desktop',
                'packaging/io.github.estante.Launcher.svg',
            ):
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            shutil.copytree(ROOT / 'assets/backgrounds', source / 'assets/backgrounds')
            shutil.copytree(ROOT / 'assets/controller', source / 'assets/controller')
            shutil.copytree(
                ROOT / 'rust',
                source / 'rust',
                ignore=shutil.ignore_patterns('target'),
            )

            binary = source / 'rust/target/release/estante'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nprintf "Estante 0.5.0\\n"\n')
            binary.chmod(0o755)

            command = [
                sys.executable, str(source / 'packaging/install.py'),
                '--prefix', '/opt/Estante Test', '--destdir', str(base / 'stage'),
            ]
            subprocess.run(command, check=True, capture_output=True)
            app = base / 'stage/opt/Estante Test/share/estante'
            self.assertTrue((app / 'README.md').is_file())
            self.assertTrue((app / 'assets/backgrounds/1.png').is_file())
            self.assertFalse(list(app.rglob('*.py')))
            launcher = base / 'stage/opt/Estante Test/bin/estante'
            self.assertEqual(
                subprocess.check_output([str(launcher), '--version'], text=True).strip(),
                'Estante 0.5.0',
            )

            subprocess.run(command + ['--uninstall'], check=True, capture_output=True)
            self.assertFalse((app / 'README.md').exists())
