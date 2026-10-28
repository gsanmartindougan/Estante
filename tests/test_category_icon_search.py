import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from metadata import CategoryIcons, IconifyIcons
from library import Library
from image_cache import Gdk
from gi.repository import GLib

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill="currentColor" d="M4 4h8v8H4z"/></svg>'


class CategoryIconSearchTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_bootstrap_catalog_search_and_browse_all_reuse_one_request(self):
        with patch.object(CategoryIcons, 'request', return_value=io.BytesIO(json.dumps({
                'heart-fill': 1, 'heart': 2, 'controller': 3, '../bad': 4}).encode())) as request:
            client = CategoryIcons(self.root)
            self.assertEqual([row['name'] for row in client.search('heart fill')], ['heart-fill'])
            self.assertEqual(len(client.search('')), 3)
            request.assert_called_once_with(CategoryIcons.CATALOG_URL)
        self.assertEqual(client.search('controller')[0]['license'], 'MIT')

    def test_fresh_catalog_is_available_offline(self):
        (self.root / 'bootstrap-catalog.json').write_text('["heart", "controller"]')
        with patch.object(CategoryIcons, 'request', side_effect=OSError('offline')) as request:
            self.assertEqual(len(CategoryIcons(self.root).search('')), 2)
            request.assert_not_called()

    def test_expired_catalog_falls_back_when_offline(self):
        cached = self.root / 'bootstrap-catalog.json'
        cached.write_text('["heart"]')
        os.utime(cached, (0, 0))
        with patch.object(CategoryIcons, 'request', side_effect=OSError('offline')):
            self.assertEqual(CategoryIcons(self.root).search('heart')[0]['name'], 'heart')

    def test_bad_catalog_does_not_silently_hide_errors(self):
        with patch.object(CategoryIcons, 'request', return_value=io.BytesIO(b'{}')):
            with self.assertRaises(ValueError):
                CategoryIcons(self.root).search('heart')

    def test_download_renders_transparent_white_png_and_reuses_file(self):
        client = CategoryIcons(self.root)
        url = CategoryIcons.ICON_ROOT + 'controller.svg'
        with patch.object(CategoryIcons, 'request', return_value=io.BytesIO(SVG)) as request:
            path = client.download(url)
            self.assertEqual(client.download(url), path)
            request.assert_called_once_with(url)
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(Path(path).read_bytes()))
        self.assertEqual((texture.get_width(), texture.get_height()), (128, 128))
        pixbuf = Gdk.pixbuf_get_from_texture(texture)
        pixels = pixbuf.get_pixels()
        self.assertEqual(pixels[3], 0)
        center = 64 * pixbuf.get_rowstride() + 64 * 4
        self.assertEqual(tuple(pixels[center:center + 4]), (255, 255, 255, 255))

    def test_invalid_bootstrap_urls_never_reach_network(self):
        client = CategoryIcons(self.root)
        with patch.object(CategoryIcons, 'request') as request:
            for url in ('https://example.com/a.svg', CategoryIcons.ICON_ROOT + '../a.svg',
                        CategoryIcons.ICON_ROOT + 'a.svg?other=1'):
                with self.assertRaises(ValueError):
                    client.download(url)
            request.assert_not_called()

    def test_iconify_search_parses_collections_and_caches_metadata(self):
        data = {'icons': ['mdi:heart', 'bi:steam', 'mdi:heart', 'bad:../path'],
                'collections': {'mdi': {'author': {'name': 'Author'}, 'license': {'spdx': 'MIT'}}}}
        with patch.object(IconifyIcons, 'request', return_value=io.BytesIO(json.dumps(data).encode())) as request:
            client = IconifyIcons(self.root)
            rows = client.search('heart')
            self.assertEqual(client.search('heart'), rows)
            self.assertEqual([row['name'] for row in rows], ['mdi:heart', 'bi:steam'])
            self.assertEqual(rows[0]['author'], 'Author')
            self.assertEqual(rows[0]['license'], 'MIT')
            self.assertIn('limit=64', request.call_args.args[0])
            request.assert_called_once()
            client.validate_download_url(rows[0]['url'])

    def test_iconify_expansion_is_requested_only_when_explicit(self):
        with patch.object(IconifyIcons, 'request', return_value=io.BytesIO(b'{"icons": []}')) as request:
            IconifyIcons(self.root).search('game', full=True)
        self.assertIn('limit=999', request.call_args.args[0])

    def test_empty_iconify_query_does_not_make_an_invalid_request(self):
        with patch.object(IconifyIcons, 'request') as request:
            self.assertEqual(IconifyIcons(self.root).search('  '), [])
            request.assert_not_called()

    def test_iconify_only_accepts_its_svg_endpoint_and_white_color(self):
        client = IconifyIcons(self.root)
        with patch.object(IconifyIcons, 'request') as request:
            for url in ('https://example.com/a.svg', 'https://api.iconify.design/mdi/../heart.svg',
                        'https://user@api.iconify.design/mdi/heart.svg?color=%23ffffff',
                        'https://api.iconify.design/mdi/heart.svg?redirect=evil'):
                with self.assertRaises(ValueError):
                    client.download(url)
            request.assert_not_called()
        with patch.object(IconifyIcons, 'request', return_value=io.BytesIO(SVG)):
            self.assertTrue(Path(client.download('https://api.iconify.design/mdi/heart.svg?color=%23ffffff')).is_file())

    def test_source_credit_survives_rename_and_clears_on_local_replacement(self):
        library = Library(home=self.root, data_dir=self.root / 'library')
        library.manage_category('Steam')
        image = self.root / 'icon.png'
        image.write_bytes(b'icon')
        credit = {'source': 'https://icons.getbootstrap.com/icons/steam/',
                  'author': 'The Bootstrap Authors', 'license': 'MIT', 'url': 'temporary preview'}
        library.set_category_icon('Steam', image, credit)
        library.manage_category('PC', previous='Steam')
        library = Library(home=self.root, data_dir=library.root)
        self.assertEqual(library.state['category_icon_sources']['PC']['license'], 'MIT')
        self.assertNotIn('url', library.state['category_icon_sources']['PC'])
        library.set_category_icon('PC', image)
        self.assertNotIn('PC', library.state['category_icon_sources'])

    def test_removing_category_or_icon_removes_credit(self):
        library = Library(home=self.root, data_dir=self.root / 'library')
        image = self.root / 'icon.png'
        image.write_bytes(b'icon')
        library.set_category_icon(None, image, {'source': 'https://icons.getbootstrap.com/'})
        library.set_category_icon(None)
        self.assertNotIn('', library.state['category_icon_sources'])
        library.manage_category('Steam')
        library.set_category_icon('Steam', image, {'source': 'https://icons.getbootstrap.com/'})
        library.manage_category('', previous='Steam', delete=True)
        self.assertNotIn('Steam', library.state['category_icon_sources'])
