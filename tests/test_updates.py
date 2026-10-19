from copy import deepcopy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from i18n import set_language, get_language
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from updates import latest_release, install_appimage, version_tuple, update_available


def response(content):
    value = MagicMock()
    value.__enter__.return_value = io.BytesIO(content)
    return value


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        previous = get_language()
        self.addCleanup(set_language, previous)
        set_language('es')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'Estante.AppImage'
        self.target.write_bytes(b'previous version')
        self.content = b'\x7fELF\x02\x01\x01\x00AI\x02' + b'new appimage'
        self.release = {'version': '0.2.0', 'asset': {
            'name': 'Estante-0.2.0-x86_64.AppImage', 'size': len(self.content),
            'digest': 'sha256:' + hashlib.sha256(self.content).hexdigest(),
            'browser_download_url': 'https://github.com/gsanmartindougan/Estante/releases/download/v0.2.0/Estante-0.2.0-x86_64.AppImage'}}

    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_tuple('v0.10.0'), version_tuple('0.9.0'))
        with self.assertRaises(ValueError):
            version_tuple('v0.2.0-beta')

    def test_release_detection_and_no_update(self):
        import json
        data = {'tag_name': 'v0.2.0', 'assets': [self.release['asset']]}
        with patch('updates.urlopen', return_value=response(json.dumps(data).encode())):
            self.assertEqual(latest_release('0.1.0')['version'], '0.2.0')
        with patch('updates.urlopen', return_value=response(json.dumps(data).encode())):
            self.assertIsNone(latest_release('0.2.0'))
        data['prerelease'] = True
        with patch('updates.urlopen', return_value=response(json.dumps(data).encode())):
            self.assertIsNone(latest_release('0.1.0'))

    def test_missing_public_release_is_explained(self):
        with patch('updates.urlopen', side_effect=HTTPError('https://api.github.com', 404, 'Not Found', {}, None)):
            with self.assertRaisesRegex(ValueError, 'versión pública'):
                latest_release()

    def test_install_atomically_replaces_appimage_and_preserves_open_file(self):
        with self.target.open('rb') as running, patch('updates.urlopen', return_value=response(self.content)):
            self.assertEqual(install_appimage(self.release, self.target), '0.2.0')
            self.assertEqual(running.read(), b'previous version')
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertTrue(self.target.stat().st_mode & 0o111)
        self.assertFalse(list(self.target.parent.glob('.estante-update-*')))

    def test_failed_downloads_keep_original_and_clean_temporary_files(self):
        for content in (b'partial', self.content[:-1] + b'x'):
            with self.subTest(content=content), patch('updates.urlopen', return_value=response(content)):
                with self.assertRaises(ValueError):
                    install_appimage(self.release, self.target)
                self.assertEqual(self.target.read_bytes(), b'previous version')
                self.assertFalse(list(self.target.parent.glob('.estante-update-*')))
        with patch('updates.urlopen', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                install_appimage(self.release, self.target)
        self.assertEqual(self.target.read_bytes(), b'previous version')
        self.assertFalse(list(self.target.parent.glob('.estante-update-*')))

    def test_requires_checksum_repo_url_and_appimage_format(self):
        release = deepcopy(self.release)
        release['asset']['digest'] = ''
        self.assertIn('SHA-256', update_available(release, self.target))
        self.assertIn('requiere ejecutar el AppImage', update_available(self.release))
        release = deepcopy(self.release)
        release['asset']['browser_download_url'] = 'https://example.com/file.AppImage'
        with self.assertRaisesRegex(ValueError, 'repositorio'):
            install_appimage(release, self.target)
        release = deepcopy(self.release)
        data = b'not an appimage'
        release['asset'].update(size=len(data), digest='sha256:' + hashlib.sha256(data).hexdigest())
        with patch('updates.urlopen', return_value=response(data)):
            with self.assertRaisesRegex(ValueError, 'AppImage válido'):
                install_appimage(release, self.target)
        self.assertEqual(self.target.read_bytes(), b'previous version')
