from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from core.version import __version__

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_qt_staged_install_contains_qml_runtime_and_default_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            command=[sys.executable,str(ROOT/'packaging/install.py'),'--prefix','/opt/Qt Test','--destdir',directory]
            subprocess.run(command,check=True,capture_output=True)
            app=Path(directory)/'opt/Qt Test/share/estante'
            self.assertTrue((app/'qt_app/Library.qml').is_file())
            self.assertTrue((app/'qt_app/VirtualKeyboard.qml').is_file())
            self.assertTrue((app/'qt_app/Gamepad.js').is_file())
            self.assertTrue((app/'packaging/io.github.estante.Launcher.svg').is_file())
            self.assertTrue((app/'tools/memory_fixture.py').is_file())
            launcher=Path(directory)/'opt/Qt Test/bin/estante'
            self.assertIn('qt_app/__main__.py',launcher.read_text())
            version=subprocess.check_output([sys.executable,str(app/'qt_app/__main__.py'),'--version'],text=True)
            self.assertEqual(version.strip(),'Estante '+__version__)
            subprocess.run(command+['--uninstall'],check=True,capture_output=True)
            self.assertFalse((app/'qt_app/Library.qml').exists())
