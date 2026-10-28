"""Linux-first Qt frontend: library browsing, launch and session supervision."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from native_memory import configure_native_allocator
configure_native_allocator()
from game_session import playing_behavior
from qt_app.session import run_session
from appearance import background_effects_for
from library import Library
from i18n import set_language, tr
from qt_app.catalog import Catalog
from qt_app.editing import draft_for, save_draft
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QUrl, QEvent, QLockFile, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine


class LibraryController(QObject):
    changed = Signal()
    selectionChanged = Signal()
    sessionChanged = Signal()
    sessionEvent = Signal(object)
    quitRequested = Signal()
    editorChanged = Signal()
    inputAction = Signal(str)
    appearanceChanged = Signal()
    saverChanged = Signal()

    @Property(QObject, constant=True)
    def launchers(self):
        return self._launchers

    def __init__(self, games, settings, root=None, allow_launch=True, allow_edit=True):
        super().__init__()
        self.catalog = Catalog(games)
        self.settings = settings
        self._entries_cache=None
        self._entries_provider=None
        self.changed.connect(self.invalidateEntries)
        self.root = root
        self.allow_launch = allow_launch
        self.allow_edit = allow_edit
        self._editing = False
        self._draft = {}
        self._edit_identity = None
        self._editor_error = ''
        self._busy = False
        self._loading = False
        self._status = ''
        from qt_app.launcher_status import LauncherStatus
        self._launchers = LauncherStatus(self)
        self._launch_game = None
        self._transferred = False
        self.sessionEvent.connect(self.handle_session)
        from qt_app.management import Manager
        self.management = Manager(self)
        from qt_app.system_keyboard import SystemKeyboard
        self._native_keyboard = SystemKeyboard(self)
        self._saver_active=False
        self._saver_paths=[]
        self._saver_index=0
        self._in_tray=False
        self._last_activity=time.monotonic()
        self._last_slide=0
        self.window=None
        self._cursor_hidden=False
        self.inputAction.connect(self.gamepadUsed)
        app=QGuiApplication.instance()
        if app:
            app.applicationStateChanged.connect(self.applicationStateChanged)
            app.aboutToQuit.connect(self.restoreCursor)
        self.tray=None
        self.idle_timer=QTimer(self)
        self.idle_timer.timeout.connect(self.checkIdle)
        self.idle_timer.start(1000)
        self.activity = {}
        self.category_names = list(self.catalog.categories)
        self.category_icons={}
        if root and (Path(root)/'library.json').is_file():
            state=json.loads((Path(root)/'library.json').read_text())
            self.activity=state.get('activity', {})
            self.category_icons=state.get('category_icons',{})
            names=set(state.get('categories',[])) | set(self.catalog.categories)
            ordered=[n for n in state.get('category_order',[]) if n in names]
            self.category_names=ordered+sorted(names-set(ordered), key=str.casefold)
            primary=state.get('primary_category')
            if primary in self.category_names: self.catalog.filter(category=primary)
        self.view_mode = settings.get('layout', settings.get('view_mode', 'list'))
        if self.view_mode not in ('list','grid','ps5','carousel'): self.view_mode='list'

    @Property(QObject, constant=True)
    def nativeKeyboard(self): return self._native_keyboard

    @Slot()
    @Slot(str)
    def gamepadUsed(self, action=''):
        if self.window is not None and not self._cursor_hidden:
            QGuiApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self._cursor_hidden=True

    @Slot()
    def restoreCursor(self):
        if self._cursor_hidden:
            QGuiApplication.restoreOverrideCursor()
            self._cursor_hidden=False

    def applicationStateChanged(self, state):
        if state!=Qt.ApplicationState.ApplicationActive:
            self.restoreCursor()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.Wheel):
            if not hasattr(event,'source') or event.source()==Qt.MouseEventSource.MouseEventNotSynthesized:
                self.restoreCursor()
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.TouchBegin):
            waking=self._saver_active
            self.recordActivity()
            return waking
        return False

    @Property(bool, notify=saverChanged)
    def screensaverActive(self): return self._saver_active

    @Property(bool, notify=saverChanged)
    def suspended(self): return self._saver_active or self._in_tray

    @Property(str, notify=saverChanged)
    def screensaverImage(self):
        return self.artwork({'image':self._saver_paths[self._saver_index]},'image') if self._saver_paths else ''

    @Slot()
    def recordActivity(self):
        self._last_activity=time.monotonic()
        if self._saver_active:
            self._saver_active=False
            self._saver_paths=[]
            self.changed.emit(); self.selectionChanged.emit(); self.saverChanged.emit()

    @Slot()
    def previewScreensaver(self):
        self.activateScreensaver()

    def activateScreensaver(self):
        if self.management.busy: return
        settings=self.settings
        if settings.get('screensaver_source')=='application':
            path=settings.get('screensaver_background','bundled:6.png')
            if path.startswith('bundled:'): path=str(ROOT/'assets/backgrounds'/path.removeprefix('bundled:'))
            paths=[path]
        else: paths=[g.get('banner') or g.get('cover') for g in self.catalog.games]
        self._saver_paths=list(dict.fromkeys(p for p in paths if p and Path(p).is_file()))
        if not self._saver_paths: return
        self._saver_index=0
        self._saver_active=True
        self._last_slide=time.monotonic()
        self.changed.emit(); self.selectionChanged.emit(); self.saverChanged.emit()

    def checkIdle(self):
        from screensaver_config import time_seconds
        now=time.monotonic()
        if self._saver_active:
            if now-self._last_slide >= time_seconds(self.settings,'slide'):
                self._saver_index=(self._saver_index+1)%len(self._saver_paths)
                self._last_slide=now; self.saverChanged.emit()
        elif self.settings.get('screensaver_enabled') and not self._busy and not self._in_tray and now-self._last_activity >= time_seconds(self.settings,'idle'):
            self.activateScreensaver()

    @Slot()
    def restoreWindow(self):
        self._in_tray=False
        self.recordActivity()
        self.changed.emit(); self.selectionChanged.emit(); self.saverChanged.emit()
        if self.window:
            self.window.showFullScreen() if self.settings.get('start_fullscreen',True) else self.window.show()
            self.window.requestActivate()
        if self.tray: self.tray.hide()

    @Slot()
    def toTray(self):
        if not self.window: return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._status='No hay bandeja del sistema disponible. Estante seguirá abierto.'
            self.sessionChanged.emit(); return
        if self.tray is None:
            self.tray=QSystemTrayIcon(QIcon(str(ROOT/'packaging/io.github.estante.Launcher.svg')),self)
            self.tray.setToolTip('Estante')
            menu=QMenu()
            menu.addAction('Abrir Estante',self.restoreWindow)
            menu.addAction('Salir',lambda: self.quitRequested.emit() if self.requestClose() else None)
            self.tray.setContextMenu(menu)
            self.tray_menu=menu
            self.tray.activated.connect(lambda reason: self.restoreWindow() if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()
        self._in_tray=True
        self.changed.emit(); self.selectionChanged.emit(); self.saverChanged.emit()
        self.window.hide()
        QTimer.singleShot(250,lambda: self.window.releaseResources() if not self.window.isVisible() else None)

    @Property(QObject, constant=True)
    def manager(self): return self.management

    @Slot()
    def refresh(self):
        library=Library(data_dir=self.root)
        self.catalog.games=library.games()
        self.activity=library.state.get('activity', {})
        self.category_names=library.categories()
        self.category_icons=library.state.get('category_icons',{})
        self.catalog.filter()
        if self.catalog.category and self.catalog.category not in self.category_names:
            self.catalog.filter(category='')
        self.changed.emit(); self.selectionChanged.emit()

    @Property('QVariantMap', notify=appearanceChanged)
    def settingsMap(self): return self.settings

    @Property(str, notify=appearanceChanged)
    def controllerHints(self):
        from controls import controller_hint, controller_buttons
        buttons = controller_buttons(self.settings)
        menu = {"sony": "Options", "nintendo": "+"}.get(self.settings.get("controller_type"), "Menu")
        hint = controller_hint(self.settings)
        if self.view_mode == 'grid':
            hint = hint.replace(tr('{bumpers}: letra').format(**buttons), tr('{bumpers}: página').format(**buttons))
            hint += tr(' · L3: página anterior · R3: página siguiente')
        return hint + f" · {buttons['save']}: editar · {menu}: ajustes"

    @Property('QVariantMap', notify=appearanceChanged)
    def controllerButtons(self):
        from controls import controller_buttons
        return controller_buttons(self.settings)

    @Property(str, notify=appearanceChanged)
    def editorSaveHint(self):
        from controls import controller_save_hint
        return controller_save_hint(self.settings)

    @Property(str, notify=appearanceChanged)
    def viewMode(self): return self.view_mode

    @Slot(str)
    def changeView(self, mode):
        if mode in ('list','grid','ps5','carousel'):
            self.view_mode=mode
            if self.allow_edit:
                from qt_app.operations import save_settings
                self.settings=save_settings(self.root, {'layout':mode})
            self.appearanceChanged.emit()

    @Property('QVariantMap', notify=appearanceChanged)
    def appearance(self):
        from appearance import minimal_for, cover_format_for, ring_for
        mode=self.view_mode
        effects=background_effects_for(self.settings,mode)
        return dict(dim=effects['dim']/100, blur=effects['blur']/40, fillMode=self.settings.get('background_fill','blur'),
                    minimal=minimal_for(self.settings,mode), format=cover_format_for(self.settings,mode),
                    split=self.settings.get('background_splits',{}).get(mode,'single'),
                    hero='full' if minimal_for(self.settings,mode) else self.settings.get('hero_positions',{}).get(mode,'full'),
                    fillBlur=effects['blur']/40 if mode in self.settings.get('background_blur',{}) else 0.8,
                    radius=self.settings.get('cover_radii',{}).get(mode,12),
                    ring=ring_for(self.settings,mode),
                    zoom=self.settings.get('grid_zoom' if mode=='grid' else 'carousel_zoom',100)/100,
                    side=self.settings.get('list_side','bottom'),
                    bottom=self.settings.get('carousel_position','top') == 'bottom')

    @Property('QVariantMap', constant=True)
    def desktopPalette(self):
        palette = QGuiApplication.palette()
        return {name: palette.color(getattr(QPalette, role)).name() for name, role in
                [('window','Window'),('windowText','WindowText'),('base','Base'),('text','Text'),
                 ('button','Button'),('buttonText','ButtonText'),('highlight','Highlight'),
                 ('highlightedText','HighlightedText'),('mid','Mid'),('accent','Accent'),
                 ('placeholderText','PlaceholderText'),('alternateBase','AlternateBase')]}

    @Property(bool, constant=True)
    def canEdit(self):
        return self.allow_edit

    @Property(bool, notify=editorChanged)
    def editing(self):
        return self._editing

    @Property('QVariantMap', notify=editorChanged)
    def draft(self):
        return self._draft

    @Property(str, notify=editorChanged)
    def editorError(self):
        return self._editor_error

    @Slot()
    def edit(self):
        game = self.catalog.selected
        if not self.allow_edit or self._busy or not game:
            return
        try:
            latest = next((g for g in Library(data_dir=self.root).games() if g['id'] == game['id']), None)
            if latest is None:
                raise ValueError('El juego ya no está en la biblioteca.')
            self._draft = draft_for(latest)
            self._edit_identity = latest['id']
            self._editing = True
            self._editor_error = ''
            self.editorChanged.emit()
        except Exception as error:
            self._status = str(error)
            self.sessionChanged.emit()

    @Slot()
    def cancelEdit(self):
        self._editing = False
        self._draft = {}
        self._editor_error = ''
        self.editorChanged.emit()

    @Slot('QVariantMap', result=bool)
    def saveEdit(self, values):
        if not self._editing or not self.allow_edit:
            return False
        try:
            games = save_draft(self.root, self._edit_identity, self._draft, values)
            self.catalog.games = games
            self.category_names=Library(data_dir=self.root).categories()
            self.catalog.filter()
            if self.catalog.category and self.catalog.category not in self.category_names:
                self.catalog.filter(category='')
            self.changed.emit()
            self.selectionChanged.emit()
            self.cancelEdit()
            self._status = 'Ficha guardada'
            self.sessionChanged.emit()
            return True
        except Exception as error:
            self._editor_error = str(error)
            self.editorChanged.emit()
            return False

    @Property(bool, notify=sessionChanged)
    def busy(self):
        return self._busy

    @Property(bool, notify=sessionChanged)
    def loading(self):
        return self._loading

    @Property(str, notify=sessionChanged)
    def status(self):
        return self._status

    @Property(bool, constant=True)
    def canLaunch(self):
        return self.allow_launch

    @Property('QVariantMap', notify=sessionChanged)
    def launchGame(self):
        return self.entry(self._launch_game)

    @Slot()
    def play(self):
        game = self.catalog.selected
        if self._busy or self._editing or self.management.busy or not game or not self.allow_launch:
            return
        self._busy = self._loading = True
        self._launch_game = dict(game)
        self._status = 'Iniciando ' + game['title'] + '…'
        self.sessionChanged.emit()
        restore = dict(selected_game=game['id'], active_category=self.catalog.category,
                       query=self.catalog.query, view_mode=self.view_mode)
        reopen = ([os.environ['APPIMAGE']] if os.environ.get('APPIMAGE') else [str(Path(os.environ['ESTANTE_APPDIR'])/'AppRun')]) if os.environ.get('ESTANTE_APPDIR') else [sys.executable, str(Path(__file__).resolve())]
        # Tray/screensaver are not migrated yet: keep the UI rather than silently close it.
        hide = playing_behavior(self.settings) == 'hide'
        self.worker = Thread(target=run_session,
                             args=(dict(game), self.root, restore, reopen, hide, self.sessionEvent.emit),
                             daemon=True, name='estante-qt-session')
        self.worker.start()

    @Slot(object)
    def handle_session(self, event):
        kind, value = event
        if kind == 'handoff':
            folder, acknowledged = value
            try:
                (folder/'handoff').touch()
            except OSError as error:
                (folder/'cancel').touch()
                self._status = str(error)
            else:
                self._transferred = True
                acknowledged.set()
                self.quitRequested.emit()
        elif kind == 'started':
            behavior=playing_behavior(self.settings)
            if behavior=='screensaver': self.activateScreensaver()
            elif behavior=='tray': self.toTray()
            self._loading = False
            self._status = 'Juego en ejecución'
        elif kind == 'warning':
            self._status = value
        elif kind in ('finished', 'error'):
            self._busy = self._loading = False
            self._status = (value if kind == 'error' else
                            ('Partida finalizada' if not value else f'El juego terminó con código {value}. Consulta launch.log.'))
            self.restoreWindow()
            self.refresh()
        self.sessionChanged.emit()

    @Slot()
    def reclaimPlayingMemory(self):
        if not self._busy or self._loading:
            return
        self.invalidateEntries()
        if self.window:
            self.window.releaseResources()
        import gc
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL(None).malloc_trim(0)
        except (AttributeError, OSError):
            pass

    @Slot(result=bool)
    def requestClose(self):
        if self._busy and not self._transferred:
            self._status = 'Hay una partida en ejecución. Estante debe completar su supervisión antes de cerrar.'
            self.sessionChanged.emit()
            return False
        return True

    @Slot(str,result=str)
    def backgroundPreview(self, value):
        path=ROOT/'assets/backgrounds'/Path(value.removeprefix('bundled:')).name if value.startswith('bundled:') else Path(value)
        return self.artwork({'background':str(path)},'background')

    def artwork(self, game, field, dominant=False):
        path = Path(game.get(field) or '')
        if not path.is_file(): return ''
        if getattr(self,'use_image_provider',False):
            from urllib.parse import quote
            return 'image://artwork/'+('@dominant/' if dominant else '@logo/' if field=='logo' else '')+quote(str(path.resolve()),safe='')
        return QUrl.fromLocalFile(str(path.resolve())).toString()

    def entry(self, game):
        if game is None:
            return dict(title='', cover='', squareCover='', logo='', banner='', secondary='', description='', genres=[], details='', activity='',history=[])
        metadata = game.get('metadata') or {}
        background = game.get('banner', '')
        if self.settings.get('background_source') == 'global':
            background = self.settings.get('global_background', '')
            if background.startswith('bundled:'):
                background = str(ROOT/'assets/backgrounds'/background.removeprefix('bundled:'))
        lines = []
        for field, label in (('developers', 'Estudio'), ('publishers', 'Editora'),
                             ('platforms', 'Plataformas'), ('release_date', 'Lanzamiento')):
            value = metadata.get(field)
            if value:
                lines.append(label + ': ' + (', '.join(map(str, value)) if isinstance(value, list) else str(value)))
        if self.settings.get('show_launcher_details',{}).get(self.view_mode,True):
            lines.extend([str(game.get('kind','')),str(game.get('path',''))])
        stats=self.activity.get(game['id'], {})
        seconds=game.get('playtime',0) if game.get('kind')=='faugus' else stats.get('seconds',0)
        activity=f"Tiempo jugado: {int(seconds or 0)//60} min · Sesiones: {stats.get('sessions',0)} · Última vez: {stats.get('last_played') or game.get('last_played') or 'Sin datos'}"
        return dict(id=game['id'], title=metadata.get('title') or game['title'],
                    cover=self.artwork(game, 'cover') or self.artwork(game, 'square_cover'),
                    fillPrimary=self.artwork({'image':background},'image',True), fillSecondary=self.artwork(game,'banner_secondary',True),
                    squareCover=self.artwork(game, 'square_cover'), secondary=self.artwork(game,'banner_secondary') if self.settings.get('background_source')!='global' else '',
                    logo=self.artwork(game, 'logo'), banner=self.artwork({'banner': background}, 'banner'),
                    description=str(metadata.get('synopsis') or metadata.get('description') or tr('Sin sinopsis disponible.')),
                    genres=metadata.get('genres') or [], details='\n'.join(lines),
                    activity=activity, kind=game.get('kind',''), history=stats.get('history',[]) if self.settings.get('show_session_history',True) else [], metadata=metadata)

    @Slot()
    def invalidateEntries(self):
        self._entries_cache=None

    @Property('QVariantList', notify=changed)
    def entries(self):
        if self.suspended: return []
        use_provider=bool(getattr(self,'use_image_provider',False))
        if self._entries_cache is None or self._entries_provider!=use_provider:
            self._entries_cache=[dict(id=game['id'],title=(game.get('metadata') or {}).get('title') or game['title'],
                cover=self.artwork(game,'cover') or self.artwork(game,'square_cover'),
                squareCover=self.artwork(game,'square_cover'),logo=self.artwork(game,'logo'))
                for game in self.catalog.visible]
            self._entries_provider=use_provider
        return self._entries_cache

    @Property(str, constant=True)
    def initialQuery(self):
        return self.catalog.query

    @Property(str, notify=changed)
    def categoryImage(self):
        path=self.category_icons.get(self.catalog.category or '')
        return self.artwork({'icon':str(Path(self.root)/'category-icons'/path)},'icon') if path else ''

    @Property('QStringList', notify=changed)
    def letters(self): return self.catalog.letters

    @Property(int, notify=selectionChanged)
    def letterIndex(self): return self.catalog.letter_index

    @Slot(int)
    def letter(self, step):
        index=self.catalog.letter_target(step)
        if index is not None: self.select(index)

    @Property(int, notify=changed)
    def categoryIndex(self):
        return self.categories.index(self.catalog.category) if self.catalog.category in self.categories else 0

    @Property('QStringList', notify=changed)
    def categories(self):
        names = list(dict.fromkeys([*self.category_names, *self.catalog.categories]))
        return ['Todos', *names]

    @Property(int, notify=selectionChanged)
    def selected(self):
        return self.catalog.index

    @Property('QVariantMap', notify=selectionChanged)
    def game(self):
        return self.entry(None if self.suspended else self.catalog.selected)

    @Property('QVariantMap', notify=selectionChanged)
    def editorImages(self):
        game = self.catalog.selected or {}
        return {name: self.artwork(game, field) for name, field in (
            ('cover', 'cover'), ('banner', 'banner'), ('secondary', 'banner_secondary'))}

    @Slot(str)
    def search(self, text):
        self.catalog.filter(query=text)
        self.changed.emit()
        self.selectionChanged.emit()

    @Slot(int)
    def category(self, index):
        names = self.categories
        if 0 <= index < len(names):
            self.catalog.filter(category=names[index] if index else '')
            self.changed.emit()
            self.selectionChanged.emit()

    @Slot(int)
    def select(self, index):
        self.catalog.select(index)
        self.selectionChanged.emit()

    @Slot(int)
    def move(self, delta):
        self.catalog.move(delta)
        self.selectionChanged.emit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--games', type=int, help='Use an isolated synthetic library of N games')
    parser.add_argument('--windowed', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='Exercise navigation and close automatically')
    parser.add_argument('--screenshot', help='Save the smoke-test window as PNG')
    args = parser.parse_args()
    if args.games is not None and args.games < 1:
        parser.error('--games must be positive')
    source = Path(os.environ.get('ESTANTE_DATA_DIR', Path.home()/'.local/share/estante'))
    instance_lock=None
    if not args.games and not args.smoke:
        source.mkdir(parents=True,exist_ok=True)
        instance_lock=QLockFile(str(source/'qt-instance.lock'))
        instance_lock.setStaleLockTime(0)
        if not instance_lock.tryLock(100): parser.exit(1,'Estante Qt ya está abierto para esta biblioteca.\n')
    with tempfile.TemporaryDirectory(prefix='estante-qt-library-') as temporary:
        data = Path(temporary)
        if (source/'library.json').is_file():
            (data/'library.json').write_bytes((source/'library.json').read_bytes())
        library = Library(data_dir=data)
        if args.games:
            from tools.memory_fixture import populate_test_games
            populate_test_games(library, args.games)
        settings = json.loads((source/'settings.json').read_text()) if (source/'settings.json').exists() else {}
        set_language(settings.get('language','system'))
        app = QApplication(sys.argv[:1])
        if args.games or args.smoke: app.setDesktopFileName("io.github.estante.Test")
        from qt_app.theme import apply_system_palette
        apply_system_palette(app)
        from qt_app.translation import Translator
        translator=Translator(app)
        app.installTranslator(translator)
        app.setApplicationName('Estante Qt')
        controller = LibraryController(library.games(), settings, data if args.games else source,
                                       allow_launch=not (args.games or args.smoke), allow_edit=not args.smoke)
        resume_path = os.environ.pop('ESTANTE_RESUME_FILE', '')
        if resume_path:
            path = Path(resume_path)
            try:
                if path.resolve().parent == source.resolve() and path.name.startswith('resume-'):
                    restored = json.loads(path.read_text())
                    controller.view_mode=restored.get('view_mode',controller.view_mode)
                    controller.catalog.filter(query=restored.get('query', ''),
                                              category=restored.get('active_category') or '')
                    selected = restored.get('selected_game')
                    if any(g['id'] == selected for g in controller.catalog.visible):
                        controller.catalog.selected_id = selected
                    path.unlink()
            except (OSError, ValueError) as error:
                controller._status = 'No se pudo restaurar la selección: ' + str(error)
        controller.quitRequested.connect(app.quit)
        engine = QQmlApplicationEngine()
        from qt_app.images import ArtworkProvider
        cache=Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'estante'/'qt-thumbnails'
        if args.games or args.smoke: cache=Path(library.root)/'qt-thumbnails'
        engine.addImageProvider('artwork',ArtworkProvider(cache))
        controller.use_image_provider=True
        controller.appearanceChanged.connect(engine.retranslate)
        engine.rootContext().setContextProperty('libraryController', controller)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name('Library.qml'))))
        if not engine.rootObjects():
            return 1
        window = engine.rootObjects()[0]
        controller.window=window
        app.installEventFilter(controller)
        if not args.windowed and settings.get('start_fullscreen',True):
            window.showFullScreen()
        if not args.smoke and not args.games:
            controller.launchers.start(settings)
        if settings.get('check_updates_on_start') and not args.smoke and not args.games:
            QTimer.singleShot(1500,controller.management.checkUpdates)
        timer = QTimer()
        gamepad = None
        if not args.smoke:
            from controls import Gamepad
            def dispatch(action, *_):
                controller.gamepadUsed(action)
                if controller.screensaverActive:
                    controller.recordActivity()
                    return
                controller.recordActivity()
                controller.inputAction.emit(action)
            try:
                gamepad = Gamepad(dispatch, window.isActive)
                timer.timeout.connect(gamepad.poll)
                timer.start(16)
            except RuntimeError as error:
                print(error, file=sys.stderr)
        else:
            def exercise():
                controller.search('zzzz-no-matches')
                assert controller.selected == -1
                controller.move(1)
                controller.search('')
                for _ in range(len(controller.catalog.games)+1):
                    controller.move(1)
                controller.category(0)
            QTimer.singleShot(1500, exercise)
            def finish():
                if args.screenshot:
                    window.grabWindow().save(args.screenshot)
                print('QT_LIBRARY_SMOKE_OK', len(controller.catalog.visible), flush=True)
                app.quit()
            QTimer.singleShot(5000, finish)
        diagnostics=QTimer()
        if os.environ.get('ESTANTE_MEMORY_DIAGNOSTICS') == '1':
            def report_memory():
                values={}
                for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
                    key,_,value=line.partition(':')
                    if key in ('Rss','Pss','Anonymous','Private_Dirty'): values[key]=round(int(value.split()[0])/1024,1)
                values.update(renderer=str(window.rendererInterface().graphicsApi()),games=len(controller.catalog.games),visible_model=len(controller.entries),panel_jobs=controller.manager.busy)
                print('Estante Qt memoria: '+json.dumps(values),flush=True)
            diagnostics.timeout.connect(report_memory)
            diagnostics.start(10000)
            QTimer.singleShot(3000,report_memory)
        result = app.exec()
        controller.launchers.stop()
        if not args.smoke and not args.games:
            from qt_app.launcher_processes import close_on_exit
            for client, error in close_on_exit(controller.settings, controller._transferred).items():
                print(f'Estante: no se pudo cerrar {client}: {error}', file=sys.stderr)
        diagnostics.stop()
        timer.stop()
        controller.idle_timer.stop()
        if controller.tray: controller.tray.hide()
        controller.management.shutdown()
        if gamepad:
            gamepad.close()
        del engine
        if instance_lock: instance_lock.unlock()
        return result


if __name__ == '__main__':
    sys.exit(main())
