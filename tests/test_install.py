from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from version import __version__

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_staged_install_update_and_uninstall_preserve_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            command = [sys.executable, str(ROOT / 'install.py'), '--prefix', '/opt/Estante Test', '--destdir', directory]
            subprocess.run(command, check=True, capture_output=True)
            installed = stage / 'opt/Estante Test'
            self.assertEqual(len(list((installed / 'share/estante/assets/backgrounds').glob('*'))), 6)
            launcher = installed / 'bin/estante'
            self.assertTrue(launcher.stat().st_mode & 0o111)
            self.assertIn("'/opt/Estante Test/share/estante/estante.py'", launcher.read_text())
            subprocess.run(['sh', '-n', str(launcher)], check=True)
            desktop = installed / 'share/applications/io.github.estante.Launcher.desktop'
            self.assertIn('Exec="/opt/Estante Test/bin/estante"', desktop.read_text())
            self.assertIn('X-Estante-Version=' + __version__, desktop.read_text())
            result = subprocess.run([sys.executable, str(installed / 'share/estante/estante.py'), '--version'],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), 'Estante ' + __version__)
            self.assertEqual((installed / 'share/estante/carousel.py').read_bytes(), (ROOT / 'carousel.py').read_bytes())
            keep = installed / 'share/estante/user-file.txt'
            keep.write_text('preserve')
            subprocess.run(command, check=True, capture_output=True)
            subprocess.run(command + ['--uninstall'], check=True, capture_output=True)
            self.assertTrue(keep.exists())
            self.assertFalse(launcher.exists())
            self.assertFalse(desktop.exists())
            self.assertFalse((installed / 'share/estante/estante.py').exists())
