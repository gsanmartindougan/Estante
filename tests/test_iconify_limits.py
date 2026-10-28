import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from metadata import CategoryIcons, IconifyIcons
from settings_view import SettingsView


class IconifyLimitTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def clock(self):
        now = [100.0]
        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds
        return now, sleeps, sleep

    def test_rate_limit_retries_after_server_pause(self):
        now, sleeps, sleep = self.clock()
        error = HTTPError('https://api.iconify.design/search', 429, 'Too Many Requests', {'Retry-After': '7'}, None)
        client = IconifyIcons(self.root)
        client.on_wait = Mock()
        with patch.object(IconifyIcons, '_next_request_at', 0), \
             patch('metadata.time.monotonic', side_effect=lambda: now[0]), \
             patch('metadata.time.sleep', side_effect=sleep), \
             patch.object(CategoryIcons, 'request', side_effect=[error, 'response']) as request:
            self.assertEqual(client.request('https://api.iconify.design/search'), 'response')
        self.assertEqual(sleeps, [7])
        self.assertEqual(request.call_count, 2)
        client.on_wait.assert_called_once_with(7)

    def test_long_cooldown_prevents_further_requests_without_blocking(self):
        now, sleeps, sleep = self.clock()
        error = HTTPError('https://api.iconify.design/search', 429, 'Too Many Requests', {'Retry-After': '120'}, None)
        with patch.object(IconifyIcons, '_next_request_at', 0), \
             patch('metadata.time.monotonic', side_effect=lambda: now[0]), \
             patch('metadata.time.sleep', side_effect=sleep), \
             patch.object(CategoryIcons, 'request', side_effect=error) as request:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, '120'):
                    IconifyIcons(self.root).request('https://api.iconify.design/search')
            request.assert_called_once()
        self.assertEqual(sleeps, [])

    def test_successful_requests_from_different_clients_share_spacing(self):
        now, sleeps, sleep = self.clock()
        with patch.object(IconifyIcons, '_next_request_at', 0), \
             patch('metadata.time.monotonic', side_effect=lambda: now[0]), \
             patch('metadata.time.sleep', side_effect=sleep), \
             patch.object(CategoryIcons, 'request', return_value='response'):
            IconifyIcons(self.root).request('https://api.iconify.design/search')
            IconifyIcons(self.root).request('https://api.iconify.design/mdi.json')
        self.assertEqual(sleeps, [IconifyIcons.REQUEST_INTERVAL])

    def test_repeated_rate_errors_have_bounded_attempts(self):
        now, sleeps, sleep = self.clock()
        errors = [HTTPError('https://api.iconify.design/search', 429, 'limited', {}, None) for _ in range(3)]
        with patch.object(IconifyIcons, '_next_request_at', 0), \
             patch('metadata.time.monotonic', side_effect=lambda: now[0]), \
             patch('metadata.time.sleep', side_effect=sleep), \
             patch.object(CategoryIcons, 'request', side_effect=errors) as request:
            with self.assertRaises(ValueError):
                IconifyIcons(self.root).request('https://api.iconify.design/search')
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleeps, [5, 10])

    def test_persistent_search_cache_survives_new_settings_client(self):
        with patch.object(IconifyIcons, 'request', return_value=io.BytesIO(b'{"icons":["mdi:heart"],"collections":{}}')) as request:
            rows = IconifyIcons(self.root).search('heart')
            request.assert_called_once()
        with patch.object(IconifyIcons, 'request', side_effect=AssertionError('unnecessary request')):
            self.assertEqual(IconifyIcons(self.root).search('heart'), rows)

    def test_batch_loads_collection_once_and_reuses_all_rendered_icons(self):
        rows = [{'name': 'mdi:' + name, 'url': 'https://api.iconify.design/mdi/' + name + '.svg?color=%23ffffff'}
                for name in ('second', 'first')]
        data = {'width': 24, 'height': 24, 'icons': {
            name: {'body': '<path fill="currentColor" d="M4 4h16v16H4z"/>'} for name in ('first', 'second')}}
        client = IconifyIcons(self.root)
        with patch.object(IconifyIcons, 'json_request', return_value=data) as request, \
             patch.object(IconifyIcons, 'request', side_effect=AssertionError('individual download')):
            client.prepare(rows)
            client.prepare(rows)
            self.assertTrue(all(Path(client.download(row['url'])).is_file() for row in rows))
            request.assert_called_once()
            self.assertEqual(parse_qs(urlsplit(request.call_args.args[0]).query)['icons'], ['first,second'])

    def test_cancelled_page_never_sends_a_batch_request(self):
        row = {'name': 'mdi:heart', 'url': 'https://api.iconify.design/mdi/heart.svg?color=%23ffffff'}
        with patch.object(IconifyIcons, 'json_request') as request:
            IconifyIcons(self.root).prepare([row], cancelled=lambda: True)
        request.assert_not_called()

    def test_transformed_alias_uses_canonical_endpoint_instead_of_wrong_render(self):
        self.assertIsNone(IconifyIcons.icon_svg({'icons': {'arrow': {'body': '<path/>', 'rotate': 1}}}, 'arrow'))
        self.assertIsNone(IconifyIcons.icon_svg({'aliases': {'arrow': {'parent': 'left'}}}, 'arrow'))


class LazyCategoryGamesTests(TestCase):
    def test_closed_group_does_not_load_games_and_opens_only_once(self):
        library = Mock()
        content = object()
        build = Mock(side_effect=lambda _: library.games())
        callback = SettingsView.load_group_once(content, build)
        reveal = Mock()
        reveal.get_reveal_child.return_value = False
        callback(reveal)
        library.games.assert_not_called()
        reveal.get_reveal_child.return_value = True
        callback(reveal)
        reveal.get_reveal_child.return_value = False
        callback(reveal)
        reveal.get_reveal_child.return_value = True
        callback(reveal)
        library.games.assert_called_once()
        build.assert_called_once_with(content)

    def test_failed_build_can_retry_on_next_open(self):
        build = Mock(side_effect=[OSError('unavailable'), None])
        callback = SettingsView.load_group_once(object(), build)
        reveal = Mock()
        reveal.get_reveal_child.return_value = True
        with self.assertRaises(OSError):
            callback(reveal)
        callback(reveal)
        self.assertEqual(build.call_count, 2)
