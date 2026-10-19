"""IGDB artwork and screenshots using Twitch client credentials."""
from i18n import tr
import json
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class IGDBArtwork:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.token = ''
        self.expires = 0

    def authenticate(self):
        if not self.client_id or not self.client_secret:
            raise ValueError(tr('Añade el Client ID y Client Secret de IGDB en Ajustes → Globales.'))
        if self.token and time.monotonic() < self.expires:
            return
        body = urlencode({'client_id': self.client_id, 'client_secret': self.client_secret,
                          'grant_type': 'client_credentials'}).encode()
        try:
            with urlopen(Request('https://id.twitch.tv/oauth2/token', data=body,
                         headers={'Content-Type': 'application/x-www-form-urlencoded'}), timeout=20) as response:
                result = json.load(response)
        except HTTPError as error:
            raise ValueError(tr('No se pudo autenticar con IGDB. Revisa las credenciales de Twitch.')) from error
        self.token = result['access_token']
        self.expires = time.monotonic() + max(0, result.get('expires_in', 0) - 60)

    def request(self, query):
        for attempt in range(2):
            self.authenticate()
            request = Request('https://api.igdb.com/v4/games', data=query.encode(), headers={
                'Client-ID': self.client_id, 'Authorization': 'Bearer ' + self.token,
                'Accept': 'application/json', 'Content-Type': 'text/plain'})
            try:
                with urlopen(request, timeout=20) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self.token = ''
                    continue
                raise ValueError(f"{tr('IGDB no pudo completar la consulta (HTTP ')}{error.code}).") from error

    def search(self, title):
        rows = self.request('search ' + json.dumps(title) +
                            '; fields name,first_release_date,platforms.name; limit 20;')
        return [{'id': row['id'], 'name': row['name'],
                 'platforms': ', '.join(p['name'] for p in row.get('platforms', []))} for row in rows]

    def images(self, game_id):
        rows = self.request(f'where id = {int(game_id)}; fields artworks.image_id,artworks.width,'
                            'artworks.height,screenshots.image_id,screenshots.width,screenshots.height; limit 1;')
        images, seen = [], set()
        for game in rows:
            for kind in ('artworks', 'screenshots'):
                for image in game.get(kind, []):
                    identity = image.get('image_id', '')
                    width, height = image.get('width', 0), image.get('height', 0)
                    if (not re.fullmatch(r'[A-Za-z0-9_-]+', identity) or identity in seen or
                            not height or width < 1280 or abs(width / height - 16 / 9) > 0.025):
                        continue
                    seen.add(identity)
                    images.append({'url': f'https://images.igdb.com/igdb/image/upload/t_original/{identity}.jpg',
                                   'width': width, 'height': height})
        return images
