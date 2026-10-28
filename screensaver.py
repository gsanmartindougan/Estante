"""Idle slideshow which suspends the library rather than covering live tiles."""
import time
import math
from pathlib import Path
from gi.repository import GLib, GObject, Gtk, Gdk, Graphene, GdkPixbuf
from image_cache import ImageCache, images, reclaim_unused_memory, memory_usage
from i18n import tr
from screensaver_config import time_seconds
from types import SimpleNamespace


def saver_size(width, height):
    """Bound decoded pixels without assuming a display aspect ratio or density."""
    width, height = max(1, width), max(1, height)
    ratio = min(1, math.sqrt(2_073_600 / (width * height)))
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def saver_bounds(width, height, image_width, image_height, source_width=None):
    # The enlargement limit applies to original pixels, not our reduced decode.
    maximum = 1.5 * (source_width or image_width) / image_width
    scale = min(maximum, width / image_width, height / image_height)
    w, h = image_width * scale, image_height * scale
    return (width - w) / 2, (height - h) / 2, w, h


def prepare_slide(texture, path):
    # Tiny colour wash fills letterboxing without a full-resolution blur surface.
    pixbuf = Gdk.pixbuf_get_from_texture(texture)
    ambient = pixbuf.scale_simple(16, 9, GdkPixbuf.InterpType.BILINEAR)
    try:
        info = GdkPixbuf.Pixbuf.get_file_info(str(path))
        source_width = info[1] if info and info[0] is not None else texture.get_width()
    except (GLib.Error, OSError):
        source_width = texture.get_width()
    return texture, Gdk.Texture.new_for_pixbuf(ambient), source_width


class SaverPicture(Gtk.Picture):
    ambient = None
    dim = .35
    source_width = None

    def do_snapshot(self, snapshot):
        texture = self.get_paintable()
        if texture is None:
            return
        width, height = self.get_width(), self.get_height()
        bounds = Graphene.Rect().init(0, 0, width, height)
        if self.ambient is not None:
            snapshot.append_texture(self.ambient, bounds)
        # Preserve panoramic compositions and limit enlargement of small assets.
        image_bounds = saver_bounds(width, height, texture.get_width(), texture.get_height(), self.source_width)
        snapshot.append_texture(texture, Graphene.Rect().init(*image_bounds))
        shade = Gdk.RGBA()
        shade.parse('black')
        shade.alpha = self.dim
        snapshot.append_color(shade, bounds)


def background_paths(games):
    return list(dict.fromkeys(str(Path(game[key]).resolve()) for game in games
                             for key in ('banner', 'banner_secondary')
                             if game.get(key) and Path(game[key]).is_file()))


def slideshow_paths(games, settings):
    if settings.get('screensaver_source', 'games') == 'application':
        from backgrounds import resolve_background, DEFAULT_BACKGROUND
        path = resolve_background(settings.get('screensaver_background', DEFAULT_BACKGROUND))
        return [path] if path and Path(path).is_file() else []
    return background_paths(games)


class Slideshow:
    """Only the current slide, a transient outgoing slide and bounded decoder."""
    def __init__(self, shelf):
        self.shelf = shelf
        self.active = False
        self.paths = []
        self.ticket = None
        self.slide_timer = None
        self.revision = 0
        self.slot = 1
        self.retire_timer = None
        self.reclaim_timer = None
        self.cache = ImageCache(max_bytes=0, disk_dir=images.disk_dir)
        self.view = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                              transition_duration=1400, hexpand=True, vexpand=True)
        self.pictures = [SaverPicture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
                         for _ in range(2)]
        for i, picture in enumerate(self.pictures):
            self.view.add_named(picture, str(i))

    def start(self, paths):
        self.paths = list(paths)
        if not self.paths:
            return False
        self.cache.resume()
        self.view.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.active = True
        self.revision += 1
        self.index = -1
        self.slot = 1
        interval = time_seconds(self.shelf.settings, 'slide')
        self.transition_ms = min(1400, interval * 400)
        self.view.set_transition_duration(self.transition_ms)
        self.advance()
        if len(self.paths) > 1:
            self.slide_timer = GLib.timeout_add_seconds(interval, self.advance)
        return True

    def advance(self):
        if not self.active:
            return False
        if self.ticket:
            return True
        self.index = (self.index + 1) % len(self.paths)
        path = self.paths[self.index]
        revision = self.revision
        width, height = saver_size(self.shelf.get_width() * self.shelf.get_scale_factor(),
                                  self.shelf.get_height() * self.shelf.get_scale_factor())
        def loaded(result, error):
            if not self.active or revision != self.revision:
                return
            self.ticket = None
            if error is None:
                self.slot = 1 - self.slot
                texture, ambient, source_width = result
                picture = self.pictures[self.slot]
                picture.ambient = ambient
                picture.source_width = source_width
                picture.dim = max(0, min(.85, self.shelf.settings.get('screensaver_dim', 35) / 100))
                picture.set_paintable(texture)
                self.view.set_visible_child_name(str(self.slot))
                if self.retire_timer:
                    GLib.source_remove(self.retire_timer)
                def retire():
                    self.retire_timer = None
                    if self.active and revision == self.revision:
                        previous = self.pictures[1 - self.slot]
                        previous.set_paintable(None)
                        previous.ambient = None
                    return False
                self.retire_timer = GLib.timeout_add(getattr(self, 'transition_ms', 1400) + 100, retire)
        self.ticket = self.cache.request(path, width, height, loaded, prepare=lambda texture: prepare_slide(texture, path), kind='background')
        return True

    def clear(self):
        self.revision += 1
        for name in ('retire_timer', 'reclaim_timer'):
            timer = getattr(self, name, None)
            if timer:
                GLib.source_remove(timer)
                setattr(self, name, None)
        if self.slide_timer:
            GLib.source_remove(self.slide_timer)
            self.slide_timer = None
        if self.ticket:
            self.ticket.cancelled = True
            self.ticket = None
        self.view.set_transition_type(Gtk.StackTransitionType.NONE)
        self.view.set_visible_child_name(str(1 - self.slot))
        for picture in self.pictures:
            picture.set_paintable(None)
            picture.ambient = None
        self.cache.suspend()
        self.paths = []

    def close(self):
        self.active = False
        self.clear()


class Screensaver:
    """Suspend library artwork behind an overlay, preserving the current page."""
    def __init__(self, shelf, release_images):
        self.shelf = shelf
        self.release_images = release_images
        self.slide_host = SimpleNamespace(settings=shelf.settings, get_width=shelf.get_width,
                                          get_height=shelf.get_height, get_scale_factor=shelf.get_scale_factor)
        self.slides = Slideshow(self.slide_host)
        self.slides.view.add_css_class('screensaver')
        self.slides.view.set_can_target(False)
        self.slides.view.set_visible(False)
        shelf.input_layer.add_overlay(self.slides.view)
        self.active = False
        self.last_activity = time.monotonic()
        self.playing_sessions = set()
        self.timer = GLib.timeout_add_seconds(1, self.check)

    def activity(self):
        self.last_activity = time.monotonic()
        if self.active:
            if not self.__dict__.get('playing_sessions'):
                self.stop()
            return True
        return False

    def game_started(self, identity):
        if identity in self.playing_sessions:
            return
        if not self.active:
            settings = self.shelf.settings
            if not slideshow_paths(self.shelf.library_games, settings):
                from backgrounds import DEFAULT_BACKGROUND
                settings = dict(settings, screensaver_source='application', screensaver_background=DEFAULT_BACKGROUND)
            if not self.start(settings):
                return
        self.playing_sessions.add(identity)

    def game_finished(self, identity):
        if identity not in self.playing_sessions:
            return
        self.playing_sessions.discard(identity)
        if not self.playing_sessions and self.active:
            self.stop()

    def preview(self, settings=None):
        if self.shelf.running_sessions:
            return False
        if (self.shelf.__dict__.get('scrape_running', False) or
                self.shelf.__dict__.get('square_active', 0)):
            self.shelf.error(tr('Espera a que terminen las tareas de la biblioteca.'))
            return False
        try:
            started = self.start(settings) if settings is not None else self.start()
            if not started:
                self.shelf.error(tr('No hay fondos disponibles para el salvapantallas.'))
        except Exception as error:
            # Restore the original page if suspending its artwork failed.
            if self.active:
                self.stop()
            self.shelf.error(tr('No se pudo iniciar el salvapantallas: ') + str(error))
        return False

    def check(self):
        shelf = self.shelf
        if self.active:
            return True
        eligible = (shelf.settings.get('screensaver_enabled', False) and shelf.get_visible() and shelf.pages.get_visible_child_name() in ('library', 'settings')
                    and not shelf.drawer.get_reveal_child() and not shelf.running_sessions
                    and not getattr(shelf, 'scrape_running', False)
                    and not shelf.square_active)
        if not eligible:
            self.last_activity = time.monotonic()
        elif time.monotonic() - self.last_activity >= time_seconds(shelf.settings, 'idle'):
            self.preview()
        return True

    def suspend_for_game(self, identity):
        if not self.active:
            self.start(suspend_only=True)
        self.playing_sessions.add(identity)

    def start(self, settings=None, suspend_only=False):
        config = self.shelf.settings if settings is None else settings
        paths = slideshow_paths(self.shelf.library_games, config)
        if not paths and not suspend_only:
            self.last_activity = time.monotonic()
            return False
        memory_before = memory_usage()
        self.selection = self.shelf.selected_game
        self.scroll = tuple(adj.get_value() for adj in
                            (self.shelf.library_scroll.get_hadjustment(), self.shelf.library_scroll.get_vadjustment()))
        # Library focus is restored from the selected game, never from a retired tile.
        self.focus = (self.shelf.get_focus()
                      if self.shelf.pages.get_visible_child_name() == 'settings' else None)
        self.pages_visible = self.shelf.pages.get_visible()
        self.slide_host.settings = config
        self.active = True
        self.slides.view.set_visible(not suspend_only)
        if not suspend_only:
            self.slides.start(paths)
        shelf = self.shelf
        shelf.library_suspended = True
        shelf.focus_revision += 1
        shelf.information_revision = getattr(shelf, 'information_revision', 0) + 1
        shelf.reload_revision = getattr(shelf, 'reload_revision', 0) + 1
        for name in ('focus_timer', 'information_timer'):
            timer = getattr(shelf, name, None)
            if timer:
                GLib.source_remove(timer)
                setattr(shelf, name, None)
        for ticket in getattr(shelf, 'background_tickets', []):
            ticket.cancelled = True
        shelf.background_tickets = []
        if shelf.scroll_animation:
            shelf.library_scroll.remove_tick_callback(shelf.scroll_animation)
            shelf.scroll_animation = None
        shelf.set_focus(None)
        shelf.pages.set_visible(False)
        self.release_images(shelf.scene)
        shelf._list_cover_signature = None
        shelf.backdrop.secondary_texture = None
        shelf.backdrop_fill.set_texture(None)
        for wheel in (shelf.carousel_flow, shelf.list_flow):
            wheel.stop_animation()
        for container in (shelf.grid_flow, shelf.horizontal_flow, shelf.carousel_flow, shelf.list_flow):
            while child := container.get_first_child():
                discard_tile(child)
                container.remove(child)
                child.game = None
        shelf.active_tile = None
        shelf.focused_game = None
        shelf.focused_banner = None
        shelf.library_games = []
        shelf.presentation_games = []
        shelf.square_queue.clear()
        while child := shelf.game_information.get_first_child():
            discard_tile(child)
            shelf.game_information.remove(child)
        shelf._information_widgets = None
        shelf.library.release_state()
        images.suspend()
        if suspend_only:
            # The focused tile can retain signal closures and its old artwork.
            self.focus = None
        # Let GTK discard old render nodes and outstanding decodes finish first.
        revision = shelf.reload_revision
        def reclaim():
            if self.active and shelf.library_suspended and shelf.reload_revision == revision:
                report = shelf.memory_release_report = reclaim_unused_memory()
                after = memory_usage()
                report['library_before'] = memory_before
                report['suspended_after'] = after
                print(f"Estante: biblioteca abierta → suspendida: "
                      f"{memory_before.get('Rss', '?')} → {after.get('Rss', '?')} MiB RSS; "
                      f"PSS {memory_before.get('Pss', '?')} → {after.get('Pss', '?')} MiB; "
                      f"anónima {memory_before.get('Anonymous', '?')} → {after.get('Anonymous', '?')} MiB. "
                      f"Solo limpieza final: {report['before_mib']} → {report['after_mib']} MiB", flush=True)
            return False
        GLib.timeout_add(1000, reclaim)
        shelf.hide_pointer()
        return True

    def stop(self):
        self.active = False
        self.slides.close()
        self.slides.view.set_visible(False)
        images.resume()
        shelf = self.shelf
        shelf.library_suspended = False
        shelf.pages.set_visible(self.pages_visible)
        shelf.selected_game = self.selection
        shelf.reload()
        revision = shelf.reload_revision
        def reclaim():
            if not self.active and shelf.reload_revision == revision:
                reclaim_unused_memory()
            return False
        GLib.timeout_add(750, reclaim)
        def restore():
            if not self.active and shelf.reload_revision == revision:
                if shelf.pages.get_visible_child_name() == 'library':
                    selected = shelf.selected_tile()
                    if selected:
                        selected.button.grab_focus()
                elif self.focus is not None:
                    self.focus.grab_focus()
                for adj, value in zip((shelf.library_scroll.get_hadjustment(), shelf.library_scroll.get_vadjustment()), self.scroll):
                    adj.set_value(value)
            self.focus = None
            return False
        GLib.timeout_add(80, restore)

    def close(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        self.active = False
        self.slides.close()
        images.resume()


def discard_tile(widget):
    """Release per-game closures without disconnecting persistent settings controls."""
    child = widget.get_first_child()
    while child:
        discard_tile(child)
        child = child.get_next_sibling()
    controllers = widget.observe_controllers()
    for i in range(controllers.get_n_items()):
        GObject.signal_handlers_destroy(controllers.get_item(i))
    GObject.signal_handlers_destroy(widget)
