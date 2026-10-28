from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from estante import Shelf
from library import Library
from image_cache import GLib


class CategoryIconTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.library = Library(home=self.root, data_dir=self.root / 'data')
        self.library.manage_category('Steam')
        self.source = self.root / 'icon.png'
        self.source.write_bytes(b'icon bytes')

    def test_icon_is_copied_persisted_and_survives_source_removal(self):
        self.library.set_category_icon('Steam', self.source)
        path = Path(self.library.category_icon('Steam'))
        self.assertNotEqual(path, self.source)
        self.source.unlink()
        reopened = Library(home=self.root, data_dir=self.library.root)
        self.assertEqual(Path(reopened.category_icon('Steam')).read_bytes(), b'icon bytes')
        self.assertEqual(reopened.categories(), ['Steam'])

    def test_rename_keeps_icon_and_delete_removes_assignment(self):
        self.library.set_category_icon('Steam', self.source)
        icon = self.library.category_icon('Steam')
        self.library.manage_category('PC', previous='Steam')
        self.assertEqual(self.library.category_icon('PC'), icon)
        self.assertEqual(self.library.category_icon('Steam'), '')
        self.library.manage_category('', previous='PC', delete=True)
        self.assertEqual(self.library.category_icon('PC'), '')

    def test_all_and_named_category_icons_are_independent_and_removable(self):
        for category in (None, 'Steam'):
            self.library.set_category_icon(category, self.source)
        self.library.set_category_icon('Steam')
        self.assertEqual(self.library.category_icon('Steam'), '')
        self.assertTrue(self.library.category_icon(None))
        self.library.set_category_icon(None)
        self.assertEqual(self.library.category_icon(None), '')

    def test_missing_icon_falls_back_and_failed_import_preserves_assignment(self):
        self.library.set_category_icon('Steam', self.source)
        path = self.library.category_icon('Steam')
        with self.assertRaises(OSError):
            self.library.set_category_icon('Steam', self.root / 'missing.png')
        self.assertEqual(self.library.category_icon('Steam'), path)
        Path(path).unlink()
        self.assertEqual(self.library.category_icon('Steam'), '')
        with self.assertRaises(ValueError):
            self.library.set_category_icon('Unknown', self.source)


class CategoryIconPresentationTests(TestCase):
    def host(self):
        host = SimpleNamespace(category_names=['Steam'], active_category='Steam',
                               category_labels=[Mock() for _ in range(3)],
                               category_images=[Mock() for _ in range(3)],
                               category_slots=[Mock() for _ in range(3)], category_caption=Mock(),
                               library=Mock(), get_scale_factor=lambda: 2)
        host.library.category_icon.side_effect = lambda name: '/steam.png' if name == 'Steam' else ''
        return host

    def test_selected_category_keeps_name_next_to_icon(self):
        host = self.host()
        with patch('estante.images.request') as request, patch('estante.images.load') as load:
            Shelf.update_categories(host)
            load.assert_not_called()
            args = request.call_args.args
            self.assertEqual(args[:3], ('/steam.png', 56, 56))
            args[3]('texture', None)
        host.category_slots[1].set_visible_child_name.assert_called_with('icon')
        host.category_slots[1].set_tooltip_text.assert_called_once_with('Steam')
        host.category_images[1].set_paintable.assert_called_with('texture')
        self.assertEqual(host.category_images[1].category_path, '/steam.png')
        host.category_caption.set_text.assert_called_once_with('Steam')
        host.category_slots[0].set_visible_child_name.assert_called_once_with('text')

    def test_invalid_image_uses_text_instead_of_breaking_toolbar(self):
        host = self.host()
        with patch('estante.images.request') as request:
            Shelf.update_categories(host)
            request.call_args.args[3](None, GLib.Error('invalid image'))
        host.category_slots[1].set_visible_child_name.assert_called_once_with('text')
        self.assertEqual(host.category_images[1].category_path, '')
