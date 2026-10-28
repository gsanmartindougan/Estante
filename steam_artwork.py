"""Optional Steam Store screenshots for game backgrounds; no account required."""
from i18n import tr
from i18n import get_language
import json
import re
from html import unescape
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

    def synopsis(self, game_id):
        identity = str(int(game_id))
        result = self.request('appdetails', appids=identity,
                              l='spanish' if get_language() == 'es' else 'english').get(identity, {})
        data = result.get('data', {}) if result.get('success') else {}
        text = data.get('short_description') or ''
        text = unescape(re.sub(r'<[^>]+>', ' ', text))
        text = ' '.join(text.split())
        if not text:
            raise ValueError(tr('No hay sinopsis disponible para este juego.'))
        return text

    def metadata(self, game_id):
        """Public Store data, chosen by the user; never requires a Steam API key."""
        from datetime import date
        identity=str(int(game_id))
        result=self.request('appdetails',appids=identity,
                            l='spanish' if get_language()=='es' else 'english').get(identity,{})
        data=result.get('data',{}) if result.get('success') else {}
        if not data.get('name'):
            raise ValueError(tr('Steam no tiene una ficha disponible para este juego.'))
        description=' '.join(unescape(re.sub(r'<[^>]+>',' ',data.get('short_description') or '')).split())
        result=dict(title=data['name'],description=description,synopsis=description,
                    developers=data.get('developers') or [],publishers=data.get('publishers') or [],
                    genres=[row['description'] for row in data.get('genres',[]) if row.get('description')],
                    platforms=[label for key,label in [('windows','Microsoft Windows'),('mac','macOS'),('linux','Linux')]
                               if data.get('platforms',{}).get(key)],
                    source='https://store.steampowered.com/app/'+identity+'/',steam_appid=identity)
        raw=(data.get('release_date') or {}).get('date','').lower().replace(',','').replace('.','')
        months={'jan':1,'ene':1,'january':1,'enero':1,'feb':2,'february':2,'febrero':2,
                'mar':3,'march':3,'marzo':3,'apr':4,'abr':4,'april':4,'abril':4,'may':5,'mayo':5,
                'jun':6,'june':6,'junio':6,'jul':7,'july':7,'julio':7,'aug':8,'ago':8,'august':8,'agosto':8,
                'sep':9,'sept':9,'september':9,'septiembre':9,'oct':10,'october':10,'octubre':10,
                'nov':11,'november':11,'noviembre':11,'dec':12,'dic':12,'december':12,'diciembre':12}
        parts=raw.split()
        if len(parts)==3:
            try:
                if parts[0].isdigit(): day,month,year=int(parts[0]),months[parts[1]],int(parts[2])
                else: day,month,year=int(parts[1]),months[parts[0]],int(parts[2])
                result['release_date']=date(year,month,day).isoformat()
            except (KeyError,ValueError): pass
        # Missing Store values must not erase manually entered metadata.
        return {key:value for key,value in result.items() if value}

    def screenshots(self, game_id):
        identity = str(int(game_id))
        result = self.request('appdetails', appids=identity, l='spanish' if get_language() == 'es' else 'english').get(identity, {})
        if not result.get('success'):
            raise ValueError(tr('Steam no tiene capturas disponibles para este juego.'))
        return [{'url': row['path_full'], 'width': 1920, 'height': 1080}
                for row in result.get('data', {}).get('screenshots', []) if row.get('path_full')]
