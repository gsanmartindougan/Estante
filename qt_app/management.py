"""Asynchronous Qt adapter for the existing import/artwork/settings backends."""
from background_jobs import BackgroundJobs
from pathlib import Path
from urllib.error import URLError
import json
from threading import Event
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QSize
from PySide6.QtGui import QImageReader
from library import Library, SteamGridDB
from i18n import set_language, tr
from metadata import GameMetadata, MetadataRateLimitError, CategoryIcons, IconifyIcons
from steam_artwork import SteamArtwork
from igdb_artwork import IGDBArtwork
from scraping import scrape_game, apply_scrape_results
from qt_app.operations import current_game, update_game, save_local, save_settings, ARTWORK


def validate_image(path):
    reader = QImageReader(str(path))
    reader.setScaledSize(QSize(32, 32))
    if reader.read().isNull():
        raise ValueError('El archivo no es una imagen compatible o está dañado.')


class Manager(QObject):
    changed = Signal()
    delivered = Signal(object)
    progressEvent = Signal(str)
    configurationChanged = Signal()
    callbackEvent = Signal(object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.root = Path(controller.root)
        self._closed=False
        self._launcher_action=None
        self.callbackEvent.connect(self.callback)
        self.pool=BackgroundJobs(lambda callback: self.callbackEvent.emit(callback), workers=2, max_pending=8)
        self._busy = False
        self._message = ''
        self._results = []
        self._target = None
        self._cancel = Event()
        self._revision = 0
        self.delivered.connect(self.finish)
        self.progressEvent.connect(self.progress)

    @Slot(object)
    def callback(self, callback):
        if not self._closed: callback()

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(str, notify=changed)
    def message(self): return self._message

    @Property('QVariantList', notify=changed)
    def results(self): return self._results

    @Property('QVariantMap', notify=changed)
    def local(self):
        game = self.controller.catalog.selected or {}
        return dict(title=game.get('title',''), path=game.get('path',''), arguments=game.get('arguments',''), cwd=game.get('cwd',''), kind=game.get('kind',''))

    @Slot(str)
    def progress(self, text):
        if self._closed: return
        self._message = text
        self.changed.emit()

    def submit(self, work, mutated=False):
        if self._closed or self._busy or self.controller.busy or not self.controller.allow_edit:
            return
        self._busy = True
        self._message = 'Trabajando…'
        self._cancel = Event()
        revision = self._revision
        self.changed.emit()
        def run():
            try: result, error = work(), None
            except Exception as exception: result, error = None, str(exception)
            if not self._closed: self.delivered.emit((revision, result, error, mutated))
        self.pool.submit(run, None, None, "management")

    @Slot(object)
    def finish(self, value):
        revision, result, error, mutated = value
        self._busy = False
        if self._launcher_action is not None:
            client = self._launcher_action
            self._launcher_action = None
            if error: self.controller.launchers.cancel_action(client)
        if mutated:
            self.controller.refresh()
        if revision != self._revision:
            self.changed.emit()
            return
        if error:
            self._message = error
        elif isinstance(result,dict) and 'results' in result:
            self._results=result['results']
            self._message=result['message']
        elif isinstance(result, list):
            self._results = result
            self._message = f'{len(result)} resultados'
        else:
            self._message = str(result or 'Completado')
        self.changed.emit()

    @Slot()
    def close(self):
        self._cancel.set()
        self._revision += 1
        self._results = []
        self._target = None
        self.changed.emit()

    @Slot()
    def clearResults(self):
        if not self._busy:
            self._results = []
            self._target = None
            self.changed.emit()

    @Slot(str, str, str, str, bool)
    def saveLocal(self, title, path, arguments, cwd, editing):
        identity = self.controller.catalog.selected_id if editing else None
        self.submit(lambda: (save_local(self.root,title,path,arguments,cwd,identity), 'Juego guardado')[1], True)

    @Slot()
    def remove(self):
        identity = self.controller.catalog.selected_id
        def work():
            library=Library(data_dir=self.root)
            library.remove(current_game(library, identity))
            return 'Juego quitado de Estante'
        self.submit(work, True)

    @Slot(str)
    def openLauncher(self, client):
        self.operateLauncher(client, True)

    @Slot(str)
    def closeLauncher(self, client):
        self.operateLauncher(client, False)

    def operateLauncher(self, client, opening):
        from qt_app.launcher_processes import CLIENT_NAMES
        if client not in CLIENT_NAMES or self._busy or self._closed or self.controller.busy or not self.controller.allow_edit:
            return
        state = next(row['state'] for row in self.controller.launchers.entries if row['id']==client)
        if state in ('opening', 'closing'):
            return
        self._launcher_action = client
        self.controller.launchers.begin_action(client, opening)
        def work():
            from qt_app.launcher_processes import running_clients, close_client, launch_hidden
            name = CLIENT_NAMES[client]
            running = client in running_clients()
            if opening:
                if running: return name + ' ya está abierto.'
                self.progressEvent.emit('Abriendo ' + name + ' en segundo plano…')
                launch_hidden(client)
                return 'Inicio solicitado a ' + name + '.'
            if not running: return name + ' ya está cerrado.'
            self.progressEvent.emit('Cerrando ' + name + '…')
            close_client(client)
            return 'Cierre solicitado a ' + name + '.'
        self.submit(work)

    @Slot(str)
    def scan(self, source):
        def work():
            library=Library(data_dir=self.root)
            if source == 'restore': return f'{library.restore_excluded_imports()} juegos restaurados'
            scanners = {'steam': library.scan_steam, 'faugus': library.scan_faugus, 'heroic': library.scan_heroic}
            if source not in scanners:
                raise ValueError('Origen de juegos no válido.')
            added, total = scanners[source]()
            if source == 'heroic':
                downloader = SteamGridDB('', library.root/'covers')
                artwork_updates = []
                for game in library.games():
                    if self._cancel.is_set(): break
                    if game.get('kind') != 'heroic': continue
                    updated = dict(game)
                    self.progressEvent.emit('Importando Heroic · ' + game['title'])
                    for field, url in game.get('heroic_artwork', {}).items():
                        if self._cancel.is_set(): break
                        if game.get(field): continue
                        try:
                            updated[field] = downloader.download(url, custom=True)
                        except (OSError, ValueError):
                            pass  # The game remains playable when artwork is unavailable.
                    if updated != game: artwork_updates.append(updated)
                if artwork_updates: library.put_many(artwork_updates)
            return f'{added} añadidos · {total} encontrados'
        self.submit(work, True)

    @Slot(str, str, str)
    def category(self, action, name, previous):
        def work():
            library=Library(data_dir=self.root)
            if action == 'primary': library.set_primary_category(name or None)
            elif action == 'up': library.move_category(name, -1)
            elif action == 'down': library.move_category(name, 1)
            else: library.manage_category(name, previous=previous or None, delete=action=='delete')
            return 'Categorías actualizadas'
        self.submit(work, True)

    @Property('QStringList', notify=changed)
    def categoryNames(self):
        return self.controller.categories[1:]

    @Property(str, notify=changed)
    def primaryCategory(self):
        path=self.root/'library.json'
        return (json.loads(path.read_text()).get('primary_category') or '') if path.is_file() else ''

    @Slot(str,str,result='QVariantList')
    def categoryGames(self, name, query):
        from qt_app.catalog import normalized
        needle=normalized(query.strip())
        return [dict(id=game['id'],title=(game.get('metadata') or {}).get('title') or game['title'],member=name in game.get('categories',[]))
                for game in self.controller.catalog.games if needle in normalized((game.get('metadata') or {}).get('title') or game['title'])]

    @Slot(str,str,bool)
    def setCategoryMember(self, name, identity, selected):
        def work():
            library=Library(data_dir=self.root)
            games=library.games()
            current_game(library,identity)
            identities={game['id'] for game in games if name in game.get('categories',[])}
            if selected: identities.add(identity)
            else: identities.discard(identity)
            library.set_category_games(name,identities)
            return 'Categoría guardada'
        self.submit(work,True)

    @Slot(str, str)
    def importImage(self, field, location):
        if field not in ARTWORK: return
        identity = self.controller.catalog.selected_id
        def work():
            client = SteamGridDB('', self.root/'covers')
            path = client.download(location, custom=True) if location.startswith(('http://','https://')) else client.import_artwork(location)
            validate_image(path)
            update_game(self.root, identity, {field:path})
            return 'Imagen guardada'
        self.submit(work, True)

    @Slot(str)
    def clearImage(self, field):
        if field in ARTWORK:
            identity=self.controller.catalog.selected_id
            self.submit(lambda: (update_game(self.root, identity, {field:''}), 'Imagen retirada')[1], True)

    @Slot()
    def swapBackgrounds(self):
        identity=self.controller.catalog.selected_id
        def work():
            library=Library(data_dir=self.root); game=current_game(library,identity)
            library.put({**game,'banner':game.get('banner_secondary',''),'banner_secondary':game.get('banner','')})
            return 'Fondos intercambiados'
        self.submit(work, True)

    @Slot(str, str, str)
    def searchArtwork(self, provider, query, field):
        if self._busy: return
        self._results=[]
        self._target = (self.controller.catalog.selected_id, provider, field)
        def work():
            settings=self.controller.settings
            if provider=='metadata':
                client=GameMetadata(self.root/'metadata',on_wait=lambda delay:self.progressEvent.emit(f'Wikidata: esperando {delay:.0f} s…'))
                client.MAX_ATTEMPTS=1  # Interactive lookup must not disappear behind long bulk retries.
                try:
                    rows=client.search(query)
                except (MetadataRateLimitError,URLError,TimeoutError):
                    rows=SteamArtwork().search(query)
                    return dict(results=[dict(kind='match',name=row['name']+' · Steam',identity=str(row['id']),provider='metadata_steam') for row in rows],
                                message=f'Wikidata no está disponible o está limitando consultas. {len(rows)} resultados de Steam; elige el juego para descargar su ficha.')
                return [dict(kind='match',name=row.get('name','')+' · Wikidata',identity=str(row['id']),description=row.get('description','')) for row in rows]
            elif provider=='metadata_steam': client=SteamArtwork()
            elif provider=='steam': client=SteamArtwork()
            elif provider=='igdb': client=IGDBArtwork(settings.get('igdb_client_id',''),settings.get('igdb_client_secret',''))
            else: client=SteamGridDB(settings.get('steamgriddb_key',''),self.root/'covers')
            return [dict(kind='match',name=row.get('name',''),identity=str(row['id'])) for row in client.search(query)]
        self.submit(work)

    @Slot(int)
    def chooseResult(self, index):
        if not 0 <= index < len(self._results) or not self._target: return
        result=dict(self._results[index]); identity, provider, field=self._target
        provider=result.get('provider',provider)
        def work():
            settings=self.controller.settings
            if result['kind']=='match':
                gameid=result['identity']
                if provider in ('metadata','metadata_steam'):
                    data=GameMetadata(self.root/'metadata',on_wait=lambda delay:self.progressEvent.emit(f'Wikidata: esperando {delay:.0f} s…')).fetch(gameid) if provider=='metadata' else SteamArtwork().metadata(gameid)
                    library=Library(data_dir=self.root); game=current_game(library,identity)
                    library.put({**game,'metadata':{**(game.get('metadata') or {}),**data}})
                    return 'Ficha descargada'
                if provider=='steam': rows=SteamArtwork().screenshots(gameid)
                elif provider=='igdb': rows=IGDBArtwork(settings.get('igdb_client_id',''),settings.get('igdb_client_secret','')).images(gameid)
                else:
                    client=SteamGridDB(settings.get('steamgriddb_key',''),self.root/'covers')
                    rows=client.logos(gameid) if field=='logo' else client.heroes(gameid) if field.startswith('banner') else client.grids(gameid,square=field=='square_cover')
                return [dict(kind='image', name=(f"{row['width']} × {row['height']} px" if row.get('width') and row.get('height') else 'Resolución no disponible'),
                             url=row['url'], preview=row.get('thumb') or row['url']) for row in rows[:30]]
            path=SteamGridDB('',self.root/'covers').download(result['url'],custom=provider!='steamgriddb')
            validate_image(path)
            update_game(self.root,identity,{field:path})
            return 'Imagen guardada'
        self.submit(work, mutated=result['kind']=='image' or provider in ('metadata','metadata_steam'))

    @Slot(bool)
    @Slot(bool, 'QStringList', bool)
    def scrape(self, replace, fields=None, information=True):
        settings=dict(self.controller.settings)
        fields=list(ARTWORK) if fields is None else fields
        def work():
            if fields and not settings.get('steamgriddb_key'): raise ValueError('Añade una clave SteamGridDB en Ajustes o desactiva las imágenes.')
            library=Library(data_dir=self.root); games=library.games(); results=[]
            artwork=SteamGridDB(settings.get('steamgriddb_key',''),self.root/'covers') if settings.get('steamgriddb_key') else None
            metadata=GameMetadata(self.root/'metadata') if information else None
            def validate(path):
                validate_image(path)
            for i,game in enumerate(games):
                if self._cancel.is_set(): break
                patch,errors=scrape_game(game,artwork,metadata,replace,validate,fields=fields)
                results.append((game,patch,errors))
                self.progressEvent.emit(f'{i+1}/{len(games)} · {game["title"]}')
            changed,errors,_=apply_scrape_results(Library(data_dir=self.root),results)
            return f'{changed} actualizados · {errors} errores' + (' · cancelado' if self._cancel.is_set() else '')
        self.submit(work, True)

    @Slot('QVariantMap')
    def saveSettings(self, changes):
        def work(): return save_settings(self.root, changes)
        # Settings are small: atomically merge on the GUI thread, no background Qt access.
        if not self.controller.allow_edit or self._busy: return
        try:
            self.controller.settings=work()
            set_language(self.controller.settings.get('language','system'))
            self.controller.view_mode=self.controller.settings.get('layout',self.controller.view_mode)
            self.controller.appearanceChanged.emit()
            self.controller.changed.emit(); self.controller.selectionChanged.emit()
            self._message='Ajustes guardados'
        except Exception as error: self._message=str(error)
        self.changed.emit()

    @Property('QVariantList', notify=configurationChanged)
    def settingSpecs(self):
        from qt_app.settings_schema import specs
        return specs(self.controller.settings)

    @Slot(str, result='QVariantList')
    def settingGroups(self, mode):
        from qt_app.settings_schema import groups
        return groups(self.controller.settings, mode)

    @Slot('QVariantList')
    def saveSettingValues(self, values):
        if not self.controller.allow_edit or self._busy: return
        try:
            from qt_app.settings_schema import merge_values
            path=self.root/'settings.json'
            latest=json.loads(path.read_text()) if path.is_file() else dict(self.controller.settings)
            merged=merge_values(latest, values)
            self.controller.settings=save_settings(self.root, merged)
            self.controller.view_mode=self.controller.settings.get('layout',self.controller.view_mode)
            set_language(self.controller.settings.get('language','system'))
            self.controller.appearanceChanged.emit()
            self.controller.changed.emit(); self.controller.selectionChanged.emit()
            self.configurationChanged.emit()
            self._message='Ajustes guardados'
        except Exception as error: self._message=str(error)
        self.changed.emit()

    @Slot()
    def checkUpdates(self):
        def work():
            from updates import latest_release, update_available
            from version import __version__
            release=latest_release()
            self._release=release
            return f'Versión instalada: {__version__}. Última: {release["version"]}.' if release else 'Ya tienes la última versión.'
        self.submit(work)

    @Slot(str, str)
    def searchIcons(self, provider, query):
        if self._busy: return
        self._results=[]
        self._icon_provider=provider
        def work():
            from qt_app.icons import BootstrapIcons, SearchIcons
            client=(SearchIcons if provider=='iconify' else BootstrapIcons)(self.root/'category-icons')
            return [dict(row,kind='icon') for row in client.search(query)[:40]]
        self.submit(work)

    @Slot(int, str)
    def chooseIcon(self, index, category):
        if not 0 <= index < len(self._results): return
        row=dict(self._results[index]); provider=self._icon_provider
        def work():
            from qt_app.icons import BootstrapIcons, SearchIcons
            client=(SearchIcons if provider=='iconify' else BootstrapIcons)(self.root/'category-icons')
            if provider=='iconify': client.prepare([row],cancelled=self._cancel.is_set)
            path=client.download(row['url'])
            Library(data_dir=self.root).set_category_icon(category or None,path,credit=row)
            return 'Icono guardado'
        self.submit(work,True)

    @Slot(str, str)
    def importIcon(self, category, path):
        self.submit(lambda: (Library(data_dir=self.root).set_category_icon(category or None,path or None),'Icono actualizado')[1],True)

    @Slot()
    def updateAppImage(self):
        def work():
            from updates import install_appimage, appimage_path
            release=getattr(self,'_release',None)
            if not release: raise ValueError('Comprueba primero las actualizaciones.')
            target=appimage_path()
            if target is None: raise ValueError('La actualización integrada requiere el AppImage.')
            install_appimage(release,target)
            return 'Actualización instalada. Reinicia Estante.'
        self.submit(work)

    def shutdown(self):
        self.close()
        self._closed=True
        self.pool.cancel('management')
