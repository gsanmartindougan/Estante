import io
import json
from email.utils import formatdate
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from metadata import GameMetadata


class MetadataRateLimitTests(TestCase):
    def setUp(self):
        self.now = 100.
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.waiting = Mock()
        self.client = GameMetadata(self.temp.name, on_wait=self.waiting)
        for name, replacement in (
                ('metadata.time.monotonic', lambda: self.now),
                ('metadata.time.time', lambda: 1000.),
                ('metadata.time.sleep', self.sleep)):
            context = patch(name, side_effect=replacement)
            context.start()
            self.addCleanup(context.stop)
        previous = GameMetadata._next_request_at
        GameMetadata._next_request_at = 0
        self.addCleanup(setattr, GameMetadata, '_next_request_at', previous)
        self.waits = []

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds

    def response(self, result, headers=None):
        response = io.BytesIO(json.dumps(result).encode())
        response.headers = headers or {}
        return response

    def test_429_honors_retry_after_then_succeeds(self):
        error = HTTPError('https://www.wikidata.org/w/api.php', 429, 'rate limit', {'Retry-After': '17'}, io.BytesIO())
        with patch('metadata.urlopen', side_effect=[error, self.response({'search': []})]) as request:
            self.assertEqual(self.client.api(action='wbsearchentities'), {'search': []})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.waits, [17])
        self.waiting.assert_called_once_with(17)
        parameters = parse_qs(urlparse(request.call_args.args[0].full_url).query)
        self.assertEqual(parameters['maxlag'], ['5'])

    def test_all_clients_share_spacing(self):
        second = GameMetadata(self.temp.name)
        with patch('metadata.urlopen', side_effect=[self.response({}), self.response({})]):
            self.client.api(action='test')
            second.api(action='test')
        self.assertAlmostEqual(self.waits[0], 1.1)

    def test_repeated_429_has_bounded_exponential_retries(self):
        errors = [HTTPError('https://www.wikidata.org', 429, 'limit', {}, io.BytesIO()) for _ in range(4)]
        with patch('metadata.urlopen', side_effect=errors) as request:
            with self.assertRaises(ValueError):
                self.client.api(action='test')
        self.assertEqual(request.call_count, 4)
        self.assertEqual(self.waits, [5, 10, 20])
        self.assertGreater(GameMetadata._next_request_at, self.now)

    def test_json_maxlag_and_http_503_retry(self):
        unavailable = HTTPError('https://www.wikidata.org', 503, 'busy', {'Retry-After': '12'}, io.BytesIO())
        with patch('metadata.urlopen', side_effect=[
                self.response({'error': {'code': 'maxlag'}}, {'Retry-After': '9'}),
                unavailable, self.response({'ok': True})]):
            self.assertEqual(self.client.api(action='test'), {'ok': True})
        self.assertEqual(self.waits, [9, 12])

    def test_other_http_errors_are_not_retried(self):
        error = HTTPError('https://www.wikidata.org', 403, 'forbidden', {}, io.BytesIO())
        with patch('metadata.urlopen', side_effect=error) as request:
            with self.assertRaises(HTTPError):
                self.client.api(action='test')
        self.assertEqual(request.call_count, 1)
        error.close()

    def test_retry_after_supports_http_date_and_invalid_values(self):
        self.assertEqual(self.client.retry_delay(formatdate(1040, usegmt=True), 0), 40)
        self.assertEqual(self.client.retry_delay('invalid', 1), 10)
