"""Optional Steam Store screenshots for game backgrounds; no account required."""
from i18n import tr
from i18n import get_language
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SteamArtwork:
    def request(self, endpoint, **parameters):
        url = 'https://store.steampowered.com/api/' + endpoint + '?' + urlencode(parameters)
        with urlopen(Request(url, headers={'User-Agent': 'Estante/0.1'}), timeout=20) as response:
            return json.load(response)

    def search(self, title):
        rows = self.request('storesearch/', term=title, l='spanish' if get_language() == 'es' else 'english', cc='ES' if get_language() == 'es' else 'US')
        return [{'id': row['id'], 'name': row['name']} for row in rows.get('items', [])]

    def screenshots(self, game_id):
        identity = str(int(game_id))
        result = self.request('appdetails', appids=identity, l='spanish' if get_language() == 'es' else 'english').get(identity, {})
        if not result.get('success'):
            raise ValueError(tr('Steam no tiene capturas disponibles para este juego.'))
        return [{'url': row['path_full'], 'width': 1920, 'height': 1080}
                for row in result.get('data', {}).get('screenshots', []) if row.get('path_full')]
