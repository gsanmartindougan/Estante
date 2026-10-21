#!/usr/bin/env python3
"""A small GTK4 game shelf. Run with python3 estante.py."""
from i18n import tr
from i18n import set_language
from profiling import timed
import os
from pathlib import Path
import threading
import weakref
import time
import math
from datetime import datetime
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gsk', '4.0')
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Graphene, Gsk, Gtk, Pango
from image_cache import images, nearby_indices
from game_session import wait_for_game
from library import Library, SteamGridDB, launch, read_json
from controls import controller_hint, controller_buttons, Gamepad, neighbor, alphabet_target, alphabet_window
from metadata import GameMetadata
from steam_artwork import SteamArtwork
from igdb_artwork import IGDBArtwork
from settings_view import SettingsView, spatial_target, navigation_bounds
from updates import latest_release
from version import __version__
from backgrounds import initial_background_settings, background_assets, background_split_for, paint_hero_pair, paint_split, crop_bounds
from carousel import CarouselWheel, list_anchor
from appearance import grid_page, list_side_for, list_navigation, list_cover_size, VIEW_NAMES, ring_for, with_ring, cover_radius_for, hero_position_for, cover_format_for, cover_size_for


def blur_radius(radius):
    """Diagnostic A/B switch; normal rendering retains all existing effects."""
    return 0 if os.environ.get('ESTANTE_DISABLE_BLUR') == '1' else radius


def margins(widget, size=20):
    for edge in ('top', 'bottom', 'start', 'end'):
        getattr(widget, 'set_margin_' + edge)(size)
    return widget


def release_images(widget):
    """Release native image buffers immediately when a view is discarded."""
    if isinstance(widget, Gtk.Picture):
        ticket = getattr(widget, 'image_ticket', None)
        if ticket:
            ticket.cancelled = True
        widget.set_paintable(None)
    child = widget.get_first_child()
    while child:
        release_images(child)
        child = child.get_next_sibling()


def button(label, callback, css=None):
    widget = Gtk.Button(label=label)
    caption = widget.get_child()
    caption.set_wrap(True)
    caption.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    caption.set_max_width_chars(32)
    widget.connect('clicked', lambda *_: callback())
    focus = Gtk.EventControllerFocus()
    focus.connect('enter', lambda *_: widget.add_css_class('action-focused'))
    focus.connect('leave', lambda *_: widget.remove_css_class('action-focused'))
    widget.add_controller(focus)
    if css:
        widget.add_css_class(css)
    return widget


def duration(seconds):
    if seconds is None:
        return tr('Sin datos')
    seconds = max(0, int(seconds))
    hours, minutes = divmod(seconds // 60, 60)
    return f'{hours} h {minutes:02d} min' if hours else (f'{minutes} min' if minutes else f'{seconds} s')


def played_date(value):
    try:
        return datetime.fromisoformat(value).strftime('%d/%m/%Y · %H:%M')
    except (TypeError, ValueError):
        return tr('Todavía no registrado')


class RoundedPicture(Gtk.Picture):
    def __init__(self, texture, radius=12, **kwargs):
        self.corner_radius = radius
        super().__init__(paintable=texture, can_shrink=True, **kwargs)

    def do_snapshot(self, snapshot):
        texture = self.get_paintable()
        if texture is None:
            return
        width, height = self.get_width(), self.get_height()
        ratios = (width/texture.get_width(), height/texture.get_height())
        scale = min(ratios) if self.get_content_fit() == Gtk.ContentFit.CONTAIN else max(ratios)
        image_width, image_height = texture.get_width() * scale, texture.get_height() * scale
        image_bounds = Graphene.Rect().init((width-image_width)/2, (height-image_height)/2,
                                             image_width, image_height)
        contained = self.get_content_fit() == Gtk.ContentFit.CONTAIN
        bounds = image_bounds if contained else Graphene.Rect().init(0, 0, width, height)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(bounds, min(self.corner_radius, bounds.get_width()/2, bounds.get_height()/2))
        snapshot.push_rounded_clip(rounded)
        snapshot.append_texture(texture, image_bounds)
        snapshot.pop()


class SquarePicture(RoundedPicture):
    """Keep a fixed logical size while retaining pixels for focus zoom and HiDPI."""
    def __init__(self, texture, width, height, radius=12):
        self.cover_width, self.cover_height = width, height
        super().__init__(texture, radius=radius, content_fit=Gtk.ContentFit.CONTAIN)

    def do_measure(self, orientation, for_size):
        size = self.cover_width if orientation == Gtk.Orientation.HORIZONTAL else self.cover_height
        return size, size, -1, -1

    def do_snapshot(self, snapshot):
        RoundedPicture.do_snapshot(self, snapshot)


class GameTile(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

    def set_child(self, child):
        self.append(child)

    def get_child(self):
        return self.get_first_child()


class TopAlignedPicture(Gtk.Picture):
    position = 'top'
    secondary_texture = None
    split_mode = 'single'

    def image_bounds(self):
        texture = self.get_paintable()
        if texture is None:
            return None
        available_height = self.get_height()
        fit = max if self.position == 'full' else min
        scale = fit(self.get_width()/texture.get_width(), available_height/texture.get_height())
        width, height = texture.get_width() * scale, texture.get_height() * scale
        y = (self.get_height() - height) / 2 if self.position == 'full' else (self.get_height() - height if self.position == 'lower' else 0)
        return Graphene.Rect().init((self.get_width() - width)/2, y, width, height)

    def do_snapshot(self, snapshot):
        if self.get_paintable() is not None and self.secondary_texture is not None and self.split_mode != 'single':
            paint_hero_pair(snapshot, (self.get_paintable(), self.secondary_texture), self.get_width(),
                            self.get_height(), self.position, self.split_mode)
            return
        bounds = self.image_bounds()
        if bounds is not None:
            if self.position == 'full':
                snapshot.append_texture(self.get_paintable(), bounds)
                return
            stops = []
            fade = ((0, 1), (0.45, 1), (0.65, 0.85), (0.82, 0.35), (1, 0))
            if self.position == 'lower':
                fade = tuple((1 - offset, alpha) for offset, alpha in reversed(fade))
            for offset, alpha in fade:
                color = Gdk.RGBA()
                color.parse(f'rgba(255,255,255,{alpha})')
                stop = Gsk.ColorStop()
                stop.offset, stop.color = offset, color
                stops.append(stop)
            snapshot.push_mask(Gsk.MaskMode.ALPHA)
            snapshot.append_linear_gradient(bounds, Graphene.Point().init(0, bounds.get_y()),
                                             Graphene.Point().init(0, bounds.get_y() + bounds.get_height()), stops)
            snapshot.pop()
            snapshot.append_texture(self.get_paintable(), bounds)
            snapshot.pop()


class BlurredBackdrop(Gtk.Widget):
    """Fill unused space without cropping the sharp panoramic artwork."""
    def __init__(self):
        super().__init__(can_target=False, hexpand=True, vexpand=True)
        self.texture = None
        self.secondary_texture = None
        self.secondary_color = None
        self.split_mode = 'single'
        self.mode = 'blur'
        self.color = None
        self.colors = {}

    @staticmethod
    @timed('worker.dominant_color')
    def dominant_color(path, texture=None):
        # Quantize a small sample, then average the most frequent color cluster.
        from collections import defaultdict
        texture = texture if texture is not None else images.load(path, 64, 64)
        image = Gdk.pixbuf_get_from_texture(texture)
        scale = min(64 / image.get_width(), 64 / image.get_height())
        image = image.scale_simple(max(1, round(image.get_width() * scale)),
                                   max(1, round(image.get_height() * scale)),
                                   GdkPixbuf.InterpType.BILINEAR)
        pixels = image.get_pixels()
        channels, stride = image.get_n_channels(), image.get_rowstride()
        buckets = defaultdict(lambda: [0, 0, 0, 0])
        for y in range(image.get_height()):
            for x in range(image.get_width()):
                offset = y * stride + x * channels
                if channels == 4 and pixels[offset + 3] < 128:
                    continue
                red, green, blue = pixels[offset:offset + 3]
                bucket = buckets[(red // 32, green // 32, blue // 32)]
                bucket[0] += 1
                bucket[1] += red
                bucket[2] += green
                bucket[3] += blue
        color = Gdk.RGBA()
        if buckets:
            count, red, green, blue = max(buckets.values(), key=lambda item: item[0])
            color.parse(f'rgb({round(red/count)},{round(green/count)},{round(blue/count)})')
        else:
            color.parse('#202020')
        return color

    def set_texture(self, texture, path=None, secondary_texture=None, secondary_path=None):
        self.texture = texture
        self.secondary_texture = secondary_texture
        self.secondary_color = None
        self.color = None
        if texture is not None and path:
            if path not in self.colors:
                try:
                    self.colors[path] = self.dominant_color(path, texture)
                except GLib.Error:
                    # Color sampling must not discard a successfully decoded hero.
                    fallback = Gdk.RGBA()
                    fallback.parse('#202020')
                    self.colors[path] = fallback
            self.color = self.colors[path]
        if secondary_texture is not None and secondary_path:
            if secondary_path not in self.colors:
                try:
                    self.colors[secondary_path] = self.dominant_color(secondary_path, secondary_texture)
                except GLib.Error:
                    self.colors[secondary_path] = self.color
            self.secondary_color = self.colors[secondary_path]
        self.queue_draw()

    def do_snapshot(self, snapshot):
        if self.texture is None:
            return
        width, height = self.get_width(), self.get_height()
        if self.secondary_texture is not None and self.split_mode != 'single':
            def draw(index, region):
                texture = (self.texture, self.secondary_texture)[index]
                color = (self.color, self.secondary_color)[index]
                if self.mode == 'dominant' and color is not None:
                    snapshot.append_color(color, Graphene.Rect().init(*region))
                else:
                    snapshot.push_blur(blur_radius(38))
                    snapshot.append_texture(texture, crop_bounds(texture, region, 1.08))
                    snapshot.pop()
            paint_split(snapshot, width, height, self.split_mode, draw)
            return
        if self.mode == 'dominant' and self.color is not None:
            snapshot.append_color(self.color, Graphene.Rect().init(0, 0, width, height))
            return
        image_width, image_height = self.texture.get_width(), self.texture.get_height()
        # Overscan avoids transparent edges around the blurred image.
        scale = max((width + 96)/image_width, (height + 96)/image_height)
        rendered_width, rendered_height = image_width * scale, image_height * scale
        bounds = Graphene.Rect().init((width - rendered_width)/2, (height - rendered_height)/2,
                                       rendered_width, rendered_height)
        snapshot.push_blur(blur_radius(32))
        snapshot.append_texture(self.texture, bounds)
        snapshot.pop()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.estante.Launcher')
        self.window = None

    def do_activate(self):
        created = self.window is None
        if created:
            self.window = Shelf(self)
            if self.window.settings.get('start_fullscreen', False):
                self.window.fullscreen()
        self.window.present()
        if created:
            self.window.startup_update_check()


class Shelf(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Estante', default_width=980, default_height=720)
        self.library = Library(data_dir=os.environ.get('ESTANTE_DATA_DIR'))
        self.settings_path = self.library.root / 'settings.json'
        self.settings = initial_background_settings(read_json(self.settings_path, {}),
                                                    first_run=not self.settings_path.exists())
        set_language(self.settings.get('language', 'system'))
        self.view_mode = self.settings.get('layout', 'grid')
        if self.view_mode not in VIEW_NAMES:
            self.view_mode = 'grid'
        self.processes = {}
        self.running_sessions = set()
        self.hidden_game_sessions = set()
        self.game_window_hold = False
        self.session_window_closed = False
        self.panel_revision = 0
        self.focus_revision = 0
        self.focused_game = None
        self.focused_banner = ''
        self.focus_timer = None
        self.banner_requests = {}
        self.selected_game = None
        self.clicked_game = None
        self.panel_back = None
        self.square_queue = []
        self.square_active = 0
        self.scroll_animation = None
        self.active_tile = None
        self.carousel_recycling = False
        self.strip_geometry_pending = None
        provider = Gtk.CssProvider()
        provider.load_from_data(b'''
            flowboxchild { padding: 6px; border-radius: 14px; }
            .cover-placeholder { background: alpha(@accent_bg_color, 0.12); }
            .game-tile, .game-tile:hover, .game-tile:active, .game-tile:backdrop {
                padding: 0; border-radius: 12px;
                background: transparent; background-image: none;
                box-shadow: none; border-color: transparent;
            }
            .game-tile.selected-game { outline: 3px solid @accent_color; outline-offset: 3px; }
            button.action-focused {
                outline: 3px solid white;
                outline-offset: 3px;
                box-shadow: 0 0 0 6px alpha(black, 0.8);
                background: #fafafa;
                color: #141414;
            }
            .app-shade { background: alpha(@window_bg_color, 0.78); }
            .game-information-scroll:focus { outline: 2px solid alpha(@accent_color, 0.65); outline-offset: -3px; }
            .settings-control:focus-within { outline: 3px solid @accent_color; outline-offset: 3px; }
            checkbutton.category-choice { padding: 10px 12px; border-radius: 8px; }
            checkbutton.category-choice:focus-within {
                outline: 3px solid white; outline-offset: 2px;
                background: #fafafa; color: #141414;
            }
            .sidebar-panel { box-shadow: -8px 0 24px alpha(black, 0.3); }
            .settings-group { padding: 18px; border: 1px solid alpha(white, 0.10); border-radius: 14px; background: alpha(white, 0.035); }
            .background-preview { min-height: 90px; border: 1px solid alpha(white, 0.12); border-radius: 10px; background: alpha(white, 0.025); }
            .editor-group { padding: 12px; border: 1px solid alpha(white, 0.08); border-radius: 12px; background: alpha(white, 0.025); }
            .game-hero { border-radius: 12px; background: alpha(@accent_bg_color, 0.1); }
            .hero-shade { background: linear-gradient(to top, alpha(black, 0.65), alpha(black, 0.1)); }
            .carousel .game-tile { opacity: 0.6; transition: transform 160ms, opacity 160ms; }
            .carousel .game-tile.selected-game { opacity: 1; transform: scale(1.25); }
            .carousel.recycling .game-tile { transition: none; }
            .ps5 .game-tile {
                opacity: 0.65; border-radius: 18px;
                border: none; min-width: 0; min-height: 0;
                transform: scale(1);
                transition: transform 240ms ease-out, opacity 240ms ease-out;
            }
            .ps5 .game-tile.selected-game { opacity: 1; transform: scale(1.5); outline: none; }
            .ps5-selector { border: 3px solid white; border-radius: 18px; }
            .ps5 .app-shade { background: linear-gradient(to right, alpha(black, 0.75), alpha(black, 0.2)); }
            .carousel .app-shade { background: alpha(black, 0.6); }
            .spotlight-title { font-size: 32px; font-weight: 700; color: white; }
            .spotlight-caption { color: alpha(white, 0.7); }
            .stat-card { background: alpha(black, 0.35); border: 1px solid alpha(white, 0.1); border-radius: 14px; padding: 18px; }
            .stat-value { font-size: 24px; font-weight: 700; color: white; }
            .info-heading { color: white; font-size: 18px; font-weight: 600; }
            .alphabet-strip { min-height: 28px; padding: 2px 6px; border-radius: 8px; background: alpha(black, 0.2); }
            .alphabet-strip button { min-height: 0; min-width: 0; padding: 0; margin: 0; border: none; background: transparent; box-shadow: none; }
            .alphabet-current { font-weight: 800; font-size: 18px; color: @accent_color; padding: 1px 4px; }
            .game-overview { padding: 12px 20px; }
            .genre-chip { background: alpha(black, 0.4); border-radius: 12px; padding: 5px 10px; color: white; }
            .compact-info { padding: 12px; }
            .compact-info link { padding-top: 2px; padding-bottom: 2px; min-height: 0; }
            .info-text { color: alpha(white, 0.8); }
        ''')
        Gtk.StyleContext.add_provider_for_display(self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.appearance_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(self.get_display(), self.appearance_css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar = Gtk.Box(spacing=10)
        toolbar.append(button(tr('＋ Añadir'), lambda: self.edit()))
        self.search = Gtk.SearchEntry(placeholder_text=tr('Buscar juegos…'), hexpand=True)
        self.search.connect('search-changed', lambda *_: self.filter())
        toolbar.append(self.search)
        self.alphabet_strip = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER, css_classes=['alphabet-strip'])
        self.alphabet_labels = []
        for index in range(3):
            letter = Gtk.Label(label='—' if index == 1 else '', width_chars=2,
                               css_classes=['alphabet-current' if index == 1 else 'dim-label'])
            self.alphabet_labels.append(letter)
            self.alphabet_strip.append(letter)
        toolbar.append(self.alphabet_strip)
        self.active_category = self.library.primary_category()
        self.category_names = []
        self.category_picker = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER, css_classes=['alphabet-strip'])
        self.category_picker.set_tooltip_text(controller_buttons(self.settings)['triggers'])
        self.category_labels = []
        for index in range(3):
            label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, width_chars=2, max_width_chars=14,
                              css_classes=['alphabet-current' if index == 1 else 'dim-label'])
            self.category_labels.append(label)
            if index == 1:
                self.category_picker.append(label)
            else:
                direction = -1 if index == 0 else 1
                target = Gtk.Button(child=label, css_classes=['flat'],
                                    tooltip_text=tr('Categoría anterior') if index == 0 else tr('Categoría siguiente'))
                target.connect('clicked', lambda _, step=direction: self.change_category(step))
                self.category_picker.append(target)
        self.update_categories()
        toolbar.append(self.category_picker)

        prefs = Gtk.Button(icon_name='emblem-system-symbolic', tooltip_text=tr('Ajustes'))
        prefs.connect('clicked', lambda *_: self.preferences())
        toolbar.append(prefs)
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text=tr('Escaneo y scraping'))
        refresh.connect('clicked', lambda *_: self.preferences('scanning'))
        toolbar.append(refresh)
        toolbar.append(Gtk.WindowControls(side=Gtk.PackType.END))
        handle = Gtk.WindowHandle()
        handle.set_child(margins(toolbar, 12))
        layout.append(handle)
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1,
                                max_children_per_line=12, column_spacing=8, row_spacing=12,
                                valign=Gtk.Align.START, homogeneous=True)
        self.flow.set_filter_func(lambda child: self.matches_game(child.game))
        self.grid_flow = self.flow
        self.horizontal_flow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                                       valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
        self.carousel_flow = CarouselWheel()
        self.list_flow = CarouselWheel(vertical=True)
        self.list_flow.paint_focus_band = self.paint_list_focus_band
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.library_scroll = scroll
        scroll.get_vadjustment().connect('value-changed', lambda *_: self.schedule_image_window())
        scroll.get_vadjustment().connect('changed', lambda *_: self.schedule_image_window())
        scroll.get_hadjustment().connect('value-changed', lambda *_: self.schedule_image_window())
        scroll.get_hadjustment().connect('changed', lambda *_: self.schedule_image_window())
        self.library_viewport = Gtk.Viewport(scroll_to_focus=False)
        self.library_viewport.set_child(margins(self.flow, 16))
        scroll.set_child(self.library_viewport)
        list_scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL |
                                                   Gtk.EventControllerScrollFlags.DISCRETE)
        list_scroll.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        list_scroll.connect('scroll', lambda controller, dx, dy:
            self.navigate(list_navigation(self.settings)[0][1 if dy > 0 else 0]) if self.view_mode == 'list' and dy else False)
        scroll.add_controller(list_scroll)
        scroll.get_hadjustment().connect('changed', self.strip_geometry_changed)
        self.strip = Gtk.Overlay()
        self.strip.set_child(scroll)
        self.grid_pager = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.END,
                                  margin_bottom=8, css_classes=['toolbar'])
        self.grid_previous = button('‹', lambda: self.change_grid_page(-1))
        self.grid_page_label = Gtk.Label()
        self.grid_next = button('›', lambda: self.change_grid_page(1))
        self.grid_previous.set_tooltip_text(tr('Página anterior · Ctrl+RePág') + ' · L3')
        self.grid_next.set_tooltip_text(tr('Página siguiente · Ctrl+AvPág') + ' · R3')
        for item in (self.grid_previous, self.grid_page_label, self.grid_next):
            self.grid_pager.append(item)
        self.strip.add_overlay(self.grid_pager)
        self.ps5_selector = Gtk.Box(width_request=156, height_request=156,
            halign=Gtk.Align.START, valign=Gtk.Align.CENTER, margin_start=24,
            css_classes=['ps5-selector'], can_target=False)
        self.strip.add_overlay(self.ps5_selector)
        self.empty = Adw.StatusPage(title=tr('Tu próximo juego, a un clic'),
            description=tr('Importa los juegos de Steam o Faugus desde Ajustes → Escaneo y scraping.\nTambién puedes añadir scripts y AppImages.'),
            icon_name='applications-games-symbolic')
        self.empty_actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self.empty_scan = button(tr('Escanear Steam y Faugus'), lambda: self.preferences('scanning'), 'suggested-action')
        self.empty_add = button(tr('Añadir un juego local'), lambda: self.edit())
        self.empty_clear = button(tr('Mostrar todos los juegos'), self.clear_library_filters)
        self.empty_actions.append(self.empty_scan)
        self.empty_actions.append(self.empty_add)
        self.empty_actions.append(self.empty_clear)
        self.empty.set_child(self.empty_actions)
        self.stack = Gtk.Stack(vexpand=True)
        self.games_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.games_page.append(self.strip)
        self.details_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.games_page.append(self.details_column)
        self.spotlight = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), 32)
        self.spotlight_title = Gtk.Label(xalign=0, wrap=True, css_classes=['spotlight-title'])
        self.spotlight.append(self.spotlight_title)
        self.spotlight.append(Gtk.Label(label=tr('Tu biblioteca · Listo para jugar'), xalign=0,
                                        css_classes=['spotlight-caption']))
        actions = self.game_actions = Gtk.Box(spacing=10)
        actions.append(button(tr('▶ Jugar'), self.play_selected, 'suggested-action'))
        actions.append(button(tr('Editar'), self.open_selected))
        self.spotlight.append(actions)
        self.detail_header = Gtk.Box(spacing=0)
        self.list_cover = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                                  margin_start=0, margin_top=16, margin_bottom=8, visible=False)
        self.list_cover_requests = set()
        self.overview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                                hexpand=True, valign=Gtk.Align.CENTER, css_classes=['game-overview'])
        self.overview.append(Gtk.Label(label=tr('Sinopsis'), xalign=0, css_classes=['info-heading']))
        self.synopsis_label = Gtk.Label(xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                                       lines=5, ellipsize=Pango.EllipsizeMode.END, max_width_chars=64,
                                       css_classes=['info-text'])
        self.overview.append(self.synopsis_label)
        genres = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6,
                             homogeneous=False, max_children_per_line=4, can_target=False)
        self.genre_labels = []
        for _ in range(8):
            label = Gtk.Label(css_classes=['genre-chip'])
            genres.append(label)
            self.genre_labels.append(label)
        self.overview.append(genres)
        self.list_presentation = Gtk.Box(spacing=24, homogeneous=True)
        self.list_cover_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                                         halign=Gtk.Align.FILL, valign=Gtk.Align.CENTER)
        self.list_cover_column.append(self.list_cover)
        self.list_presentation.append(self.list_cover_column)
        self.detail_header.append(self.list_presentation)
        self.detail_header.append(self.spotlight)
        self.details_column.append(self.detail_header)
        self.info_scroll = Gtk.ScrolledWindow(vexpand=True, focusable=True, min_content_height=150,
            hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.EXTERNAL)
        self.info_scroll.add_css_class('game-information-scroll')
        self.game_information = margins(Gtk.Box(spacing=24, homogeneous=True), 24)
        self.info_scroll.set_child(self.game_information)
        self.details_column.append(self.info_scroll)
        self.stack.add_named(self.games_page, 'games')
        self.stack.add_named(self.empty, 'empty')
        layout.append(self.stack)
        self.count = Gtk.Label(css_classes=['dim-label'])
        layout.append(Gtk.Label(label='Estante ' + __version__, css_classes=['dim-label'],
                                halign=Gtk.Align.END, margin_end=16))
        layout.append(margins(self.count, 10))
        self.controller_legend = Gtk.Label(label=controller_hint(self.settings), wrap=True, css_classes=['dim-label'])
        layout.append(margins(self.controller_legend, 8))
        self.toast = Adw.ToastOverlay()
        self.scene = Gtk.Overlay()
        self.scene.set_child(Gtk.Box())
        self.backdrop_fill = BlurredBackdrop()
        self.scene.add_overlay(self.backdrop_fill)
        self.backdrop = TopAlignedPicture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                                    hexpand=True, vexpand=True, can_target=False)
        self.scene.add_overlay(self.backdrop)
        self.scene.add_overlay(Gtk.Box(css_classes=['app-shade'], can_target=False))
        self.scene.add_overlay(layout)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                               css_classes=['background', 'sidebar-panel'])
        panel_scroll = Gtk.ScrolledWindow(propagate_natural_width=False,
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER)
        panel_scroll.set_child(self.sidebar)
        self.drawer = Gtk.Revealer(halign=Gtk.Align.END, valign=Gtk.Align.FILL,
            transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT, transition_duration=180)
        self.drawer.set_child(panel_scroll)
        self.scene.add_overlay(self.drawer)
        def resize_panel(widget, clock):
            width = max(1, self.scene.get_width() // 2)
            if panel_scroll.get_size_request()[0] != width:
                panel_scroll.set_size_request(width, -1)
            return True
        self.scene.add_tick_callback(resize_panel)

        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.pages.add_named(self.scene, 'library')
        self.preferences_view = None
        self.toast.set_child(self.pages)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect('key-pressed', self.key_pressed)
        self.add_controller(keys)
        self.input_layer = Gtk.Overlay()
        self.input_layer.set_child(self.toast)
        self.pointer_shield = Gtk.Box(hexpand=True, vexpand=True, can_target=True,
                                      focusable=False, visible=False)
        self.input_layer.add_overlay(self.pointer_shield)
        self.set_content(self.input_layer)
        self.pointer_tooltips = weakref.WeakKeyDictionary()
        self.gamepad_cursor_hidden = False
        self.pointer_position = None
        pointer = Gtk.EventControllerMotion()
        pointer.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        pointer.connect('motion', self.pointer_moved)
        self.add_controller(pointer)
        pointer_click = Gtk.GestureClick(button=0)
        pointer_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        pointer_click.connect('pressed', lambda *_: self.show_pointer())
        self.add_controller(pointer_click)

        self.configure_view()
        if self.settings.get('background_source') == 'global':
            path = background_assets(self.settings, {})[0]
            if path and Path(path).is_file():
                try:
                    texture = self.background_texture(path)
                    self.backdrop.set_paintable(texture)
                    self.backdrop_fill.set_texture(texture, path)
                except GLib.Error:
                    pass
        self.reload()
        self.gamepad = None
        self.gamepad_timer = None
        try:
            self.gamepad = Gamepad(self.navigate, self.is_active)
            self.gamepad_timer = GLib.timeout_add(16, self.gamepad.poll)
        except (OSError, RuntimeError) as error:
            GLib.idle_add(self.error, str(error))
        self.connect('close-request', self.stop_controls)
        app.connect('shutdown', self.stop_controls)

    def stop_controls(self, *_):
        self.session_window_closed = True
        if self.game_window_hold:
            self.game_window_hold = False
            self.get_application().release()
        if self.gamepad_timer:
            GLib.source_remove(self.gamepad_timer)
            self.gamepad_timer = None
        if self.gamepad:
            self.gamepad.close()
            self.gamepad = None
        return False

    def key_pressed(self, controller, key, code, state):
        if self.pages.get_visible_child_name() == 'settings':
            if key in (Gdk.KEY_s, Gdk.KEY_S) and state & Gdk.ModifierType.CONTROL_MASK:
                return self.preferences_view.save_current()
            if key == Gdk.KEY_Escape:
                self.leave_preferences()
                return True
            return False
        if key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and state & Gdk.ModifierType.CONTROL_MASK:
            return self.navigate('cycle_view_previous' if state & Gdk.ModifierType.SHIFT_MASK else 'cycle_view')
        if key in (Gdk.KEY_f, Gdk.KEY_F) and state & Gdk.ModifierType.CONTROL_MASK:
            return self.navigate('search')
        if key == Gdk.KEY_Escape:
            return self.navigate('back')
        focus = self.get_focus()
        if isinstance(focus, (Gtk.Editable, Gtk.TextView)):
            return False
        if key == Gdk.KEY_slash:
            return self.navigate('search')
        if key in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down) and state & Gdk.ModifierType.CONTROL_MASK and self.view_mode == 'grid' and not self.drawer.get_reveal_child():
            return self.change_grid_page(-1 if key == Gdk.KEY_Page_Up else 1)
        if key in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            return self.navigate('category_previous' if key == Gdk.KEY_Page_Up else 'category_next')
        directions = {Gdk.KEY_Left: 'left', Gdk.KEY_Right: 'right',
                      Gdk.KEY_Up: 'up', Gdk.KEY_Down: 'down'}
        if key in directions:
            return self.navigate(directions[key])
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            if focus and (focus.is_ancestor(self.flow) or focus == self.info_scroll or
                          focus.is_ancestor(self.info_scroll) or focus.is_ancestor(self.game_actions) or
                          focus.is_ancestor(self.empty_actions)):
                return self.navigate('confirm')
        return False

    def tile_pressed(self, gesture, count, game):
        if count == 2:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.focus_game(game)
            self.play(game)

    def tiles(self):
        result = []
        child = self.flow.get_first_child()
        query = self.search.get_text().casefold()
        while child:
            if self.matches_game(child.game) and (self.view_mode == 'grid' or child.get_visible()):
                result.append(child)
            child = child.get_next_sibling()
        return result

    def select_tile(self, tile):
        self.active_tile = tile
        tile.button.grab_focus()
        # Entering focus already selects the game; do not rebuild it twice.
        if self.selected_game != tile.game['id']:
            self.focus_game(tile.game)
        if self.view_mode != 'grid':
            GLib.idle_add(self.center_tile, tile)
            return
        adjustment = self.library_scroll.get_vadjustment()
        allocation = tile.get_allocation()
        top = allocation.y + self.flow.get_margin_top()
        bottom = top + allocation.height
        value = adjustment.get_value()
        page = adjustment.get_page_size()
        if top < value:
            adjustment.set_value(top)
        elif bottom > value + page:
            adjustment.set_value(bottom - page)

    def center_tile(self, tile):
        if (tile.get_parent() != self.flow or tile.game['id'] != self.selected_game
                or self.view_mode == 'grid' or tile != self.selected_tile()):
            return False
        if self.view_mode in ('carousel', 'list'):
            (self.list_flow if self.view_mode == 'list' else self.carousel_flow).select(tile)
            return False
        adjustment = self.library_scroll.get_hadjustment()
        valid, bounds = tile.button.compute_bounds(self.flow)
        center = (bounds.get_x() + bounds.get_width()/2 if valid else
                  tile.get_allocation().x + tile.get_width()/2) + self.flow.get_margin_start()
        target = center - (24 + self.ps5_focus_size()/2) if self.view_mode == 'ps5' else center - adjustment.get_page_size()/2
        target = max(0, min(target, adjustment.get_upper() - adjustment.get_page_size()))
        if self.scroll_animation:
            self.library_scroll.remove_tick_callback(self.scroll_animation)
            self.scroll_animation = None
        start = adjustment.get_value()
        started = GLib.get_monotonic_time()
        def animate(widget, clock):
            progress = min(1, (GLib.get_monotonic_time() - started) / 240_000)
            eased = 1 - (1 - progress) ** 3
            adjustment.set_value(start + (target - start) * eased)
            if progress >= 1:
                self.scroll_animation = None
                if self.view_mode == 'carousel':
                    self.recycle_carousel(tile)
                return False
            return True
        self.scroll_animation = self.library_scroll.add_tick_callback(animate)
        return False

    def selected_tile(self):
        tiles = self.tiles()
        if self.active_tile in tiles and self.active_tile.game['id'] == self.selected_game:
            return self.active_tile
        matches = [tile for tile in tiles if tile.game['id'] == self.selected_game]
        return matches[len(matches)//2] if matches else (tiles[len(tiles)//2] if tiles else None)

    def tile_focused(self, target, game):
        if getattr(self, 'reloading', False) or self.drawer.get_reveal_child():
            return
        parent = target.get_parent()
        while parent and not isinstance(parent, (Gtk.FlowBoxChild, GameTile)):
            parent = parent.get_parent()
        self.active_tile = parent
        if self.selected_game != game['id']:
            self.focus_game(game)

    def recycle_carousel(self, tile):
        if self.view_mode == 'carousel':
            return
        matches = [row for row in self.tiles() if row.game['id'] == tile.game['id']]
        if not matches:
            return
        middle = matches[len(matches)//2]
        if tile == middle:
            return
        if self.scroll_animation:
            self.library_scroll.remove_tick_callback(self.scroll_animation)
            self.scroll_animation = None
        self.carousel_recycling = True
        self.scene.add_css_class('recycling')
        self.active_tile = middle
        middle.button.grab_focus()
        self.focus_game(middle.game)
        adjustment = self.library_scroll.get_hadjustment()
        valid, bounds = middle.button.compute_bounds(self.flow)
        center = (bounds.get_x() + bounds.get_width()/2 if valid else
                  middle.get_allocation().x + middle.get_width()/2) + self.flow.get_margin_start()
        adjustment.set_value(center - adjustment.get_page_size()/2)
        self.carousel_recycling = False
        GLib.timeout_add(20, lambda: self.scene.remove_css_class('recycling'))

    def strip_geometry_changed(self, adjustment):
        # Adjustment notifications can run during GTK allocation. Change margins later.
        if self.view_mode != 'grid' and self.strip_geometry_pending is None:
            self.strip_geometry_pending = GLib.idle_add(self.update_strip_geometry)

    def update_strip_geometry(self):
        self.strip_geometry_pending = None
        if self.view_mode in ('grid', 'carousel', 'list'):
            return False
        adjustment = self.library_scroll.get_hadjustment()
        if adjustment.get_page_size() <= 0:
            return False
        changed = False
        if self.view_mode == 'carousel':
            leading = max(16, round(adjustment.get_page_size()/2 - 102))
            if self.flow.get_margin_start() != leading:
                self.flow.set_margin_start(leading)
                changed = True
            trailing = leading
        else:
            # Leave room for the final game to reach the left anchor.
            margin = self.flow.get_margin_start()
            trailing = max(margin, int(adjustment.get_page_size()) - 104 - margin)
        if self.flow.get_margin_end() != trailing:
            self.flow.set_margin_end(trailing)
            changed = True
        if changed:
            self.flow.queue_resize()
            selected = self.selected_tile()
            if selected:
                GLib.timeout_add(40, self.center_tile, selected)
        return False

    def open_selected(self):
        tiles = self.tiles()
        if tiles:
            self.edit_game(next((tile.game for tile in tiles if tile.game['id'] == self.selected_game), tiles[0].game))

    def play_selected(self):
        tiles = self.tiles()
        if tiles:
            self.play(next((tile.game for tile in tiles if tile.game['id'] == self.selected_game), tiles[0].game))

    def save_settings(self, settings):
        import json
        import tempfile
        fd, name = tempfile.mkstemp(dir=self.library.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(settings, stream)
            os.replace(name, self.settings_path)
            self.settings = settings
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def refresh_controller_hints(self):
        self.controller_legend.set_text(controller_hint(self.settings))
        self.category_picker.set_tooltip_text(controller_buttons(self.settings)['triggers'])

    def change_view(self, mode):
        if mode not in VIEW_NAMES:
            return
        try:
            self.save_settings({**self.settings, 'layout': mode})
        except Exception as error:
            self.error(error)
            return
        self.view_mode = mode
        self.configure_view()
        self.reload()

    def configure_view(self):
        if self.scroll_animation:
            self.library_scroll.remove_tick_callback(self.scroll_animation)
            self.scroll_animation = None
        for mode in VIEW_NAMES:
            self.scene.remove_css_class(mode)
        self.scene.add_css_class(self.view_mode)
        desired_flow = {'grid': self.grid_flow, 'carousel': self.carousel_flow, 'ps5': self.horizontal_flow, 'list': self.list_flow}[self.view_mode]
        if self.flow != desired_flow:
            self.library_viewport.set_child(None)
            self.flow = desired_flow
            self.library_viewport.set_child(self.flow)
        self.list_flow.list_side = list_side_for(self.settings)
        self.list_flow.queue_resize()
        list_horizontal = self.view_mode == 'list' and self.list_flow.list_side in ('top', 'bottom')
        self.list_flow.focus_scale = max(1, min(2.5, float(self.settings.get('list_focus_zoom', 150)) / 100))
        focused_size = self.ps5_focus_size()
        margin = round((focused_size - 104)/2) + 18
        if self.view_mode == 'carousel':
            self.ps5_selector.set_halign(Gtk.Align.CENTER)
            self.ps5_selector.set_margin_start(0)
            self.ps5_selector.set_size_request(round(192 * self.carousel_zoom()), round(cover_size_for(self.settings, 'carousel')[1] * self.carousel_zoom()))
        else:
            self.ps5_selector.set_halign(Gtk.Align.START)
            self.ps5_selector.set_margin_start(24)
            self.ps5_selector.set_size_request(focused_size, round(focused_size * cover_size_for(self.settings, 'ps5')[1] / 104))
        self.ps5_selector.set_visible(self.view_mode == 'ps5' and ring_for(self.settings, self.view_mode)['focus_ring_enabled'])
        horizontal = self.view_mode not in ('grid', 'list') or list_horizontal
        self.games_page.set_orientation(Gtk.Orientation.VERTICAL if horizontal else Gtk.Orientation.HORIZONTAL)
        self.games_page.set_homogeneous(not horizontal)
        self.games_page.reorder_child_after(self.strip, self.details_column if (
            (self.view_mode == 'carousel' and self.settings.get('carousel_position', 'top') == 'bottom') or
            (self.view_mode == 'list' and self.list_flow.list_side in ('right', 'bottom'))) else None)
        self.detail_header.set_orientation(Gtk.Orientation.VERTICAL if self.view_mode == 'list' else Gtk.Orientation.HORIZONTAL)
        parent = self.overview.get_parent()
        if parent:
            parent.remove(self.overview)
        (self.list_presentation if self.view_mode == 'list' else self.spotlight).append(self.overview)
        self.list_presentation.set_visible(self.view_mode == 'list')
        self.list_cover.set_visible(self.view_mode == 'list')
        self.spotlight_title.set_visible(self.view_mode != 'list')
        self.spotlight_title.get_next_sibling().set_visible(self.view_mode != 'list')
        actions_parent = self.game_actions.get_parent()
        if actions_parent:
            actions_parent.remove(self.game_actions)
        if self.view_mode == 'list':
            self.list_cover_column.append(self.game_actions)
        else:
            self.spotlight.insert_child_after(self.game_actions, self.spotlight_title.get_next_sibling())
        self.game_actions.set_halign(Gtk.Align.CENTER if self.view_mode == 'list' else Gtk.Align.FILL)
        self.spotlight.set_margin_top(12 if self.view_mode == 'list' else 32)
        self.spotlight.set_margin_bottom(12 if self.view_mode == 'list' else 32)
        self.spotlight.set_valign(Gtk.Align.CENTER if self.view_mode == 'list' else Gtk.Align.FILL)
        self.spotlight.set_hexpand(True)
        self.spotlight.set_visible(self.view_mode != 'list')
        self.info_scroll.set_visible(True)
        self.strip.set_hexpand(not horizontal)
        self.library_scroll.set_policy(Gtk.PolicyType.EXTERNAL if horizontal else Gtk.PolicyType.NEVER,
                                       Gtk.PolicyType.NEVER if horizontal or self.view_mode == 'list' else Gtk.PolicyType.EXTERNAL)
        self.library_scroll.set_vexpand(self.view_mode == 'grid' or (self.view_mode == 'list' and not list_horizontal))
        self.strip.set_vexpand(self.view_mode == 'grid' or (self.view_mode == 'list' and not list_horizontal))
        self.library_scroll.set_size_request(-1, {'grid': -1, 'list': max(240, round(cover_size_for(self.settings, 'list')[1] * self.list_flow.focus_scale) + 80) if list_horizontal else -1, 'carousel': round(cover_size_for(self.settings, 'carousel')[1] * self.carousel_zoom()) + 64, 'ps5': round(focused_size * cover_size_for(self.settings, 'ps5')[1] / 104) + 74}[self.view_mode])
        self.games_page.set_valign(Gtk.Align.FILL)
        self.flow.set_valign(Gtk.Align.FILL if self.view_mode in ('carousel', 'list') else (
            Gtk.Align.CENTER if horizontal else Gtk.Align.START))
        if self.view_mode == 'carousel':
            self.flow.set_size_request(-1, round(cover_size_for(self.settings, 'carousel')[1] * self.carousel_zoom()) + 64)
        self.flow.set_homogeneous(self.view_mode in ('grid', 'list'))
        if horizontal:
            self.flow.set_spacing(12 if self.view_mode == 'ps5' else 24)
        elif self.view_mode == 'grid':
            self.flow.set_column_spacing(8)
        for edge in ('top', 'bottom'):
            getattr(self.flow, 'set_margin_' + edge)(margin if self.view_mode == 'ps5' else (0 if self.view_mode == 'carousel' else 16))
        for edge in ('start', 'end'):
            getattr(self.flow, 'set_margin_' + edge)(margin if self.view_mode == 'ps5' else (0 if self.view_mode == 'carousel' else 16))
        self.strip_geometry_changed(self.library_scroll.get_hadjustment())
        self.apply_appearance()
        self.update_focus_spacing()

    def carousel_zoom(self):
        return max(1, min(1.75, float(self.settings.get('carousel_zoom', 125)) / 100))

    def grid_zoom(self):
        return max(0.5, min(2, float(self.settings.get('grid_zoom', 100)) / 100))

    def ps5_focus_size(self):
        return max(104, min(320, round(self.settings.get('ps5_focus_size',
                   104 * float(self.settings.get('ps5_zoom', 150)) / 100))))

    def update_focus_spacing(self):
        child = self.flow.get_first_child()
        while child:
            space = round((self.ps5_focus_size() - 104)/2) if (
                self.view_mode == 'ps5' and child.game['id'] == self.selected_game) else 0
            child.get_child().set_margin_start(0)
            child.get_child().set_margin_end(space)
            child = child.get_next_sibling()

    def apply_appearance(self):
        child = self.flow.get_first_child()
        while child:
            image = child.button.get_child()
            if isinstance(image, RoundedPicture) and self.view_mode != 'list':
                image.corner_radius = cover_radius_for(self.settings, self.view_mode)
                image.queue_draw()
            child = child.get_next_sibling()
        self.backdrop.position = hero_position_for(self.settings, self.view_mode)
        self.backdrop.split_mode = background_split_for(self.settings, self.view_mode)
        self.backdrop_fill.split_mode = self.backdrop.split_mode
        self.backdrop.queue_draw()
        self.backdrop_fill.mode = self.settings.get('background_fill', 'blur')
        self.backdrop_fill.queue_draw()
        zoom = self.ps5_focus_size() / 104
        ring = ring_for(self.settings, self.view_mode)
        enabled = ring['focus_ring_enabled']
        color = Gdk.RGBA()
        if not color.parse(ring['focus_ring_color']):
            color.parse('#ffffff')
        width = int(ring['focus_ring_width']) if enabled else 0
        radius = int(ring['focus_ring_radius'])
        css = f'''
            @keyframes ps5-cover-drift {{
                0%, 100% {{ transform: translateY(1.5px) rotate(-0.3deg); }}
                50% {{ transform: translateY(-1.5px) rotate(0.3deg); }}
            }}
            .ps5 .game-tile.selected-game {{ transform: scale({zoom}); outline: none; }}
            .grid .game-tile.selected-game, .list .game-tile.selected-game {{
                outline: {width}px solid {color.to_string()}; outline-offset: 3px;
                border-radius: {radius}px;
            }}
            .carousel .game-tile.selected-game {{
                transform: scale({self.carousel_zoom()});
                outline: {width / self.carousel_zoom()}px solid {color.to_string()};
                outline-offset: 0; border-radius: {radius}px;
            }}
            .ps5-selector {{ border: {width}px solid {color.to_string()}; border-radius: {radius}px; }}
        '''
        motion = self.settings.get('ps5_motion', True) and Gtk.Settings.get_default().get_property('gtk-enable-animations')
        css += '.ps5 .game-tile.selected-game picture { animation: ' + (
            'ps5-cover-drift 4s ease-in-out infinite;' if motion else 'none;') + ' }'
        self.appearance_css.load_from_data(css.encode())

    def hide_pointer(self):
        if self.gamepad_cursor_hidden:
            return
        self.gamepad_cursor_hidden = True
        self.set_cursor_from_name('none')
        # Intercept pointer picking while leaving keyboard/gamepad focus untouched.
        self.pointer_shield.set_visible(True)
        def clear(widget):
            widget.unset_state_flags(Gtk.StateFlags.PRELIGHT)
            if widget.get_has_tooltip():
                self.pointer_tooltips[widget] = True
                widget.set_has_tooltip(False)
            child = widget.get_first_child()
            while child:
                clear(child)
                child = child.get_next_sibling()
        clear(self.toast)
        self.trigger_tooltip_query()

    def show_pointer(self):
        if self.gamepad_cursor_hidden:
            self.gamepad_cursor_hidden = False
            self.pointer_shield.set_visible(False)
            for widget in list(self.pointer_tooltips):
                widget.set_has_tooltip(True)
            self.pointer_tooltips.clear()
            self.set_cursor(None)

    def pointer_moved(self, controller, x, y):
        position = (x, y)
        if self.pointer_position is not None and position != self.pointer_position:
            self.show_pointer()
        self.pointer_position = position

    @timed('ui.navigate')
    def navigate(self, action, gamepad=False):
        if gamepad:
            self.hide_pointer()
        if action in ('grid_page_previous', 'grid_page_next'):
            if self.pages.get_visible_child_name() == 'library' and not self.drawer.get_reveal_child():
                self.change_grid_page(-1 if action == 'grid_page_previous' else 1)
            return True
        if action == 'appearance_settings':
            self.preferences(self.view_mode)
            return True
        if action in ('cycle_view', 'cycle_view_previous'):
            if self.pages.get_visible_child_name() == 'library' and not self.drawer.get_reveal_child():
                modes = tuple(VIEW_NAMES)
                step = -1 if action == 'cycle_view_previous' else 1
                self.change_view(modes[(modes.index(self.view_mode) + step) % len(modes)])
                self.focus_library()
            return True
        if action == 'save' and self.pages.get_visible_child_name() != 'settings':
            return True
        if action in ('category_previous', 'category_next'):
            if self.pages.get_visible_child_name() == 'library' and not self.drawer.get_reveal_child():
                step = 1 if action == 'category_next' else -1
                self.change_category(step)
                if self.tiles():
                    self.select_tile(self.tiles()[0])
            return True
        if action in ('page_previous', 'page_next'):
            if self.pages.get_visible_child_name() != 'library' or self.drawer.get_reveal_child():
                return True
            tiles = self.tiles()
            if not tiles:
                return True
            selected = self.selected_tile() or tiles[0]
            if self.view_mode == 'carousel':
                self.recycle_carousel(selected)
                selected = self.selected_tile()
            index = tiles.index(selected)
            games = ([game for game in self.library_games if self.matches_game(game)] if self.view_mode == 'grid'
                     else list({tile.game['id']: tile.game for tile in tiles}.values()))
            current = next(i for i, game in enumerate(games) if game['id'] == selected.game['id'])
            destination = alphabet_target([game['title'] for game in games], current, action == 'page_next')
            identity = games[destination]['id']
            if self.view_mode == 'grid' and identity not in [tile.game['id'] for tile in tiles]:
                self.selected_game = identity
                self.reload()
                self.focus_library()
                return True
            matches = [i for i, tile in enumerate(tiles) if tile.game['id'] == identity]
            if identity == selected.game['id']:
                return True
            directional = [i for i in matches if (i > index if action == 'page_next' else i < index)]
            target = min(directional) if action == 'page_next' and directional else (
                max(directional) if directional else matches[0])
            self.select_tile(tiles[target])
            return True
        if self.pages.get_visible_child_name() == 'settings':
            if action in ('back', 'menu'):
                self.leave_preferences()
            else:
                self.preferences_view.navigate(action)
            return True
        if action == 'back':
            if self.drawer.get_reveal_child():
                if self.panel_back:
                    self.panel_back()
                else:
                    self.close_panel()
            elif self.search.get_text():
                self.search.set_text('')
            else:
                self.focus_library()
            return True
        if action == 'search':
            self.close_panel()
            self.search.grab_focus()
            self.search.select_region(0, -1)
            return True
        if action == 'menu':
            self.preferences()
            return True
        focus = self.get_focus()
        if self.drawer.get_reveal_child():
            gallery = getattr(self, 'artwork_gallery', None)
            if gallery and focus and focus.is_ancestor(gallery) and action in ('up', 'down', 'left', 'right'):
                cards = []
                child = gallery.get_first_child()
                while child:
                    card = child.get_child()
                    if card.get_visible() and card.get_sensitive():
                        cards.append(card)
                    child = child.get_next_sibling()
                current = next((i for i, card in enumerate(cards)
                                if focus == card or focus.is_ancestor(card)), None)
                if current is not None:
                    points = []
                    for card in cards:
                        valid, bounds = card.compute_bounds(gallery)
                        points.append((bounds.get_x() + bounds.get_width()/2,
                                       bounds.get_y() + bounds.get_height()/2))
                    target = neighbor(points, current, action)
                    if target != current or action != 'up':
                        cards[target].grab_focus()
                        return True
            if action == 'confirm':
                if focus and focus.is_ancestor(self.sidebar):
                    owner = next((control for control in SettingsView.controls(self.sidebar)
                                  if focus == control or focus.is_ancestor(control)), focus)
                    if isinstance(owner, Gtk.Switch):
                        owner.set_active(not owner.get_active())
                    elif isinstance(owner, Gtk.CheckButton):
                        owner.emit('activate')
                    else:
                        owner.activate()
            else:
                self.navigate_panel_direction(action, focus)
            return True
        if self.stack.get_visible_child_name() == 'empty':
            if action == 'confirm' and focus and focus.is_ancestor(self.empty_actions):
                focus.activate()
            else:
                self.empty_actions.child_focus(Gtk.DirectionType.TAB_BACKWARD if action in ('up', 'left')
                                                else Gtk.DirectionType.TAB_FORWARD)
            return True
        if focus and (focus == self.info_scroll or focus.is_ancestor(self.info_scroll)):
            return self.navigate_information(action, focus)
        carousel_bottom = self.view_mode == 'carousel' and self.settings.get('carousel_position', 'top') == 'bottom'
        if focus and focus.is_ancestor(self.game_actions):
            if self.view_mode == 'list' and action == list_navigation(self.settings)[2]:
                self.focus_library()
            elif action == ('up' if carousel_bottom or (self.view_mode == 'list' and list_side_for(self.settings) == 'bottom') else 'down'):
                self.info_scroll.grab_focus()
            elif action == 'confirm':
                focus.activate()
            elif self.view_mode != 'list' and action == ('down' if carousel_bottom else 'up'):
                self.focus_library()
            else:
                self.game_actions.child_focus(Gtk.DirectionType.TAB_BACKWARD if action == 'left'
                                          else Gtk.DirectionType.TAB_FORWARD)
            return True
        if self.view_mode not in ('grid', 'list') and action == ('up' if carousel_bottom else 'down'):
            self.game_actions.child_focus(Gtk.DirectionType.TAB_FORWARD)
            return True
        tiles = self.tiles()
        if not tiles:
            return False
        selected = self.selected_tile()
        current = tiles.index(selected) if selected in tiles else None
        if self.view_mode == 'list' and current is not None:
            directions, enter, _ = list_navigation(self.settings)
            if action in directions:
                self.select_tile(tiles[(current + (1 if action == directions[1] else -1)) % len(tiles)])
                return True
            if action == enter:
                self.game_actions.get_first_child().grab_focus()
                return True
            if action in ('left', 'right', 'up', 'down'):
                return True
        if self.view_mode == 'carousel' and current is not None and action in ('left', 'right'):
            self.select_tile(tiles[(current + (1 if action == 'right' else -1)) % len(tiles)])
            return True
        if self.view_mode == 'carousel' and current is not None:
            section = len({tile.game['id'] for tile in tiles})
            if current < section or current >= len(tiles) - section:
                self.recycle_carousel(selected)
                tiles = self.tiles()
                current = tiles.index(self.selected_tile())
        if action == 'confirm':
            tile = tiles[current if current is not None else 0]
            self.select_game(tile.game)
            self.game_actions.get_first_child().grab_focus()
            return True
        points = [(tile.get_allocation().x + tile.get_width()/2,
                   tile.get_allocation().y + tile.get_height()/2) for tile in tiles]
        target = neighbor(points, current, action)
        if self.view_mode == 'grid' and current is not None and target == current:
            if action == 'right' and current + 1 < len(tiles):
                self.select_tile(tiles[current + 1])
                return True
            if action == 'left' and current > 0:
                self.select_tile(tiles[current - 1])
                return True
            if action in ('right', 'down') and self.change_grid_page(1):
                return True
            if action in ('left', 'up') and self.change_grid_page(-1):
                return True
        self.select_tile(tiles[target])
        return True

    def navigate_panel_direction(self, action, focus):
        controls, points = [], []
        for control in SettingsView.controls(self.sidebar):
            valid, bounds = navigation_bounds(control, self.sidebar)
            if valid and bounds.get_width() > 0 and bounds.get_height() > 0:
                controls.append(control)
                points.append((bounds.get_x() + bounds.get_width()/2,
                               bounds.get_y() + bounds.get_height()/2))
        if not controls:
            return
        current = next((index for index, control in enumerate(controls)
                        if focus == control or (focus and focus.is_ancestor(control))), None)
        if current is None:
            controls[0].grab_focus()
            return
        owner = controls[current]
        if action in ('left', 'right') and isinstance(owner, (Gtk.Range, Gtk.SpinButton)):
            step = owner.get_adjustment().get_step_increment()
            owner.set_value(owner.get_value() + (step if action == 'right' else -step))
            return
        controls[spatial_target(points, current, action)].grab_focus()

    def navigate_information(self, action, focus):
        adjustment = self.info_scroll.get_vadjustment()
        exit_direction = list_navigation(self.settings)[2] if getattr(self, 'view_mode', '') == 'list' else 'left'
        if focus == self.info_scroll and action == exit_direction:
            at_boundary = (action not in ('up', 'down') or
                           (action == 'up' and adjustment.get_value() <= 0) or
                           (action == 'down' and adjustment.get_value() >= max(0, adjustment.get_upper() - adjustment.get_page_size())))
            if at_boundary:
                self.focus_library()
                return True
        if action == 'confirm':
            if focus != self.info_scroll:
                focus.activate()
            else:
                self.game_information.child_focus(Gtk.DirectionType.TAB_FORWARD)
            return True
        if action == 'left':
            if focus != self.info_scroll:
                self.info_scroll.grab_focus()
            elif exit_direction == 'left':
                self.focus_library()
            return True
        if action == 'right':
            self.game_information.child_focus(Gtk.DirectionType.TAB_FORWARD)
            return True
        if action in ('up', 'down'):
            if focus != self.info_scroll:
                direction = Gtk.DirectionType.TAB_FORWARD if action == 'down' else Gtk.DirectionType.TAB_BACKWARD
                if self.game_information.child_focus(direction):
                    return True
                self.info_scroll.grab_focus()
            current = adjustment.get_value()
            if action == 'up' and current <= 0:
                self.game_actions.get_first_child().grab_focus()
                return True
            maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
            step = max(64, adjustment.get_page_size() * .2)
            adjustment.set_value(max(0, min(maximum, current + (step if action == 'down' else -step))))
            return True
        return True

    def focus_library(self):
        tiles = self.tiles()
        if tiles:
            self.select_tile(self.selected_tile() or tiles[0])
        else:
            self.empty_actions.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def error(self, error):
        self.toast.add_toast(Adw.Toast(title=str(error)))

    def background(self, work, done, on_error=None):
        def run():
            try:
                result = work()
            except Exception as error:
                GLib.idle_add(on_error or self.error, str(error))
            else:
                GLib.idle_add(done, result)
        threading.Thread(target=run, daemon=True).start()

    def startup_update_check(self):
        if not self.settings.get('check_updates_on_start', False):
            return
        def available(release):
            if release:
                toast = Adw.Toast(title=tr('Nueva versión disponible: ') + release['version'],
                                  button_label=tr('Ver actualización'), timeout=0)
                toast.connect('button-clicked', lambda *_: self.preferences('global'))
                self.toast.add_toast(toast)
        # Startup is never blocked by networking; offline failures remain silent.
        self.background(latest_release, available, lambda *_: None)

    def background_texture(self, path):
        # Keep HiDPI/fullscreen backgrounds sharp, without retaining 8K sources.
        scale = self.get_scale_factor()
        width = min(3840, max(1920, self.get_width() * scale))
        height = min(2160, max(1080, self.get_height() * scale))
        return images.load(path, width, height, kind='background')

    def request_picture(self, picture, path, width, height, priority=1, kind='cover'):
        scale = 2.5 * self.get_scale_factor()
        @timed('ui.apply_image')
        def ready(texture, error):
            if texture is not None:
                picture.set_paintable(texture)
        picture.image_ticket = images.request(path, width * scale, height * scale, ready, priority, kind=kind)
        return picture

    def cover(self, game, width=156, height=234, square=False, priority=1):
        path = Path(game.get('cover') or '')
        if path.is_file():
            try:
                radius = cover_radius_for(self.settings, self.view_mode)
                picture = SquarePicture(None, width, height, radius=radius)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN if square else Gtk.ContentFit.COVER)
                picture.set_size_request(width, height)
                return self.request_picture(picture, path, width, height, priority)
            except GLib.Error:
                pass
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.FILL,
                      halign=Gtk.Align.FILL, css_classes=['cover-placeholder'])
        box.set_size_request(width, height)
        icon = Gtk.Image(icon_name='applications-games-symbolic', pixel_size=48, vexpand=True)
        box.append(icon)
        return box

    def reload(self):
        try:
            games = self.library.games()
        except Exception as error:
            self.error(f"{tr('No se pudo leer la biblioteca: ')}{error}")
            return
        selection = self.selected_game
        mode = self.view_mode
        scroll_value = self.library_scroll.get_vadjustment().get_value()
        focus = self.get_focus()
        restore_focus = focus is not None and focus.is_ancestor(self.flow)
        self.reload_revision = getattr(self, 'reload_revision', 0) + 1
        revision = self.reload_revision
        self.reloading = True
        try:
            self.rebuild_library(games)
        finally:
            self.reloading = False
        selected = self.selected_tile()
        if restore_focus and selected and not self.drawer.get_reveal_child():
            selected.button.grab_focus()
        if mode == 'grid' and self.selected_game == selection:
            def restore_scroll():
                if revision == self.reload_revision and self.view_mode == mode and self.selected_game == selection:
                    adjustment = self.library_scroll.get_vadjustment()
                    adjustment.set_value(min(scroll_value, max(0, adjustment.get_upper() - adjustment.get_page_size())))
                return False
            GLib.timeout_add(50, restore_scroll)

    def rebuild_library(self, games):
        categories = self.library.categories()
        if categories != self.category_names:
            active = self.active_category
            self.category_names = categories
            self.active_category = active if active in categories else None
        self.update_categories()
        for container in (self.grid_flow, self.horizontal_flow, self.carousel_flow, self.list_flow):
            while child := container.get_first_child():
                release_images(child)
                container.remove(child)
        self.active_tile = None
        self.square_queue.clear()
        self.library_games = list(games)
        self.grid_filter_signature = (self.search.get_text(), self.active_category)
        render_games = games
        self.grid_pager.set_visible(False)
        if self.view_mode == 'grid':
            filtered = [game for game in games if self.matches_game(game)]
            render_games, page, pages = grid_page(filtered, self.selected_game)
            self.grid_pager.set_visible(pages > 1)
            self.grid_page_label.set_text(tr('Página {page} de {pages}').format(page=page + 1, pages=pages) + ' · L3 / R3')
            self.grid_previous.set_sensitive(page > 0)
            self.grid_next.set_sensitive(page + 1 < pages)
            self.flow.set_margin_bottom(48 if pages > 1 else 16)
        for game in render_games:
            width, height = cover_size_for(self.settings, self.view_mode)
            square = self.view_mode != 'list' and cover_format_for(self.settings, self.view_mode) == 'square'
            image = Gtk.Box(width_request=width, height_request=height)
            target = Gtk.Button(child=image, css_classes=['flat', 'game-tile'], tooltip_text=game['title'])
            target.set_overflow(Gtk.Overflow.VISIBLE)
            if self.view_mode == 'grid':
                target.set_halign(Gtk.Align.CENTER)
                target.set_valign(Gtk.Align.START)
            else:
                target.set_halign(Gtk.Align.START)
                target.set_valign(Gtk.Align.START)
            target.update_property([Gtk.AccessibleProperty.LABEL], [game['title']])
            focus = Gtk.EventControllerFocus()
            focus.connect('enter', lambda *args, g=game, t=target: self.tile_focused(t, g))
            target.add_controller(focus)
            target.connect('clicked', lambda _, g=game: self.select_game(g))
            double_click = Gtk.GestureClick(button=1)
            double_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            double_click.connect('pressed', lambda gesture, count, x, y, g=game:
                                 self.tile_pressed(gesture, count, g))
            target.add_controller(double_click)
            child = Gtk.FlowBoxChild() if self.view_mode == 'grid' else margins(GameTile(), 6)
            child.game = game
            child.image_loaded = False
            child.button = target
            wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            wrapper.append(target)
            child.set_child(wrapper)
            self.flow.append(child)
        self.filter()
        self.load_square_covers()
        tiles = self.tiles()
        if tiles:
            if self.selected_game not in [tile.game['id'] for tile in tiles]:
                self.selected_game = tiles[0].game['id']
            selected = self.selected_tile()
            self.active_tile = selected
            self.focus_game(selected.game)
            if self.view_mode != 'grid':
                GLib.timeout_add(50, self.center_tile, selected)

    def schedule_image_window(self):
        if not getattr(self, 'image_window_pending', False):
            self.image_window_pending = True
            def update():
                self.image_window_pending = False
                if not getattr(self, 'reloading', False):
                    self.update_image_window()
                return False
            GLib.idle_add(update)

    @timed('ui.image_window')
    def update_image_window(self):
        tiles = self.tiles()
        selected = next((i for i, tile in enumerate(tiles)
                         if tile.game['id'] == self.selected_game), 0)
        wanted = nearby_indices(len(tiles), selected, wrap=self.view_mode in ('carousel', 'list'))
        if self.view_mode in ('grid', 'ps5'):
            horizontal = self.view_mode == 'ps5'
            adjustment = (self.library_scroll.get_hadjustment() if horizontal
                          else self.library_scroll.get_vadjustment())
            offset, page = adjustment.get_value(), adjustment.get_page_size()
            visible = []
            margin = self.flow.get_margin_start() if horizontal else self.flow.get_margin_top()
            for i, tile in enumerate(tiles):
                rect = tile.get_allocation()
                position = (rect.x if horizontal else rect.y) + margin
                extent = rect.width if horizontal else rect.height
                if extent > 1 and page > 1 and position + extent > offset and position < offset + page:
                    visible.append(i)
            if visible:
                wanted = set(visible)
        retained = set()
        width, height = cover_size_for(self.settings, self.view_mode)
        square = self.view_mode != 'list' and cover_format_for(self.settings, self.view_mode) == 'square'
        field = 'logo' if self.view_mode == 'list' else ('square_cover' if square else 'cover')
        active = {id(tiles[i]) for i in wanted}
        child = self.flow.get_first_child()
        while child:
            needed = id(child) in active
            if needed:
                retained.add(child.game.get(field, ''))
            if needed != child.image_loaded:
                release_images(child.button)
                if needed:
                    picture = (self.logo_image(child.game, width, height, priority=0 if child.game['id'] == self.selected_game else 1) if self.view_mode == 'list'
                               else self.cover({'cover': child.game.get(field, '')}, width, height, square=square, priority=0 if child.game['id'] == self.selected_game else 1))
                else:
                    picture = Gtk.Box(width_request=width, height_request=height)
                child.button.set_child(picture)
                child.image_loaded = needed
            if self.view_mode == 'ps5':
                child.set_opacity(1 if needed else 0)
            child = child.get_next_sibling()
        current = next((tile.game for tile in tiles if tile.game['id'] == self.selected_game), {})
        retained.update(background_assets(self.settings, current))
        if self.view_mode == 'list':
            retained.add(current.get('square_cover' if cover_format_for(self.settings, 'list') == 'square' else 'cover', ''))
        images.retain_paths(retained)

    @timed('ui.selected_cover')
    def update_list_cover(self, game):
        while child := self.list_cover.get_first_child():
            release_images(child)
            self.list_cover.remove(child)
        square = cover_format_for(self.settings, 'list') == 'square'
        field = 'square_cover' if square else 'cover'
        width, height = list_cover_size(self.settings)
        self.list_cover.append(self.cover({'cover': game.get(field, '')}, width, height, square=square, priority=0))

    @timed('ui.logo_capsule')
    def paint_list_focus_band(self, snapshot):
        wheel = self.list_flow
        width, height = cover_size_for(self.settings, 'list')
        scale = wheel.focus_scale
        side = list_side_for(self.settings)
        band_height = height * scale + 32
        radius = band_height / 2
        anchor = list_anchor(wheel.get_width(), width, scale)
        right = min(wheel.get_width() - 8, anchor + width * scale / 2 + 32)
        if side == 'right':
            bounds = Graphene.Rect().init(wheel.get_width() - right, (wheel.get_height() - band_height) / 2,
                                          right + radius, band_height)
        elif side in ('top', 'bottom'):
            anchor_y = list_anchor(wheel.get_height(), height, scale)
            if side == 'bottom':
                anchor_y = wheel.get_height() - anchor_y
            band_width = min(wheel.get_width() - 16, width * scale + 48)
            bounds = Graphene.Rect().init((wheel.get_width() - band_width) / 2,
                                          anchor_y - band_height / 2, band_width, band_height)
        else:
            bounds = Graphene.Rect().init(-radius, (wheel.get_height() - band_height) / 2,
                                          right + radius, band_height)
        clip = Gsk.RoundedRect()
        clip.init_from_rect(bounds, radius)
        snapshot.push_rounded_clip(clip)
        valid, position = wheel.compute_bounds(self.scene)
        if valid:
            snapshot.save()
            snapshot.translate(Graphene.Point().init(-position.get_x(), -position.get_y()))
            snapshot.push_blur(blur_radius(18))
            self.scene.snapshot_child(self.backdrop_fill, snapshot)
            self.scene.snapshot_child(self.backdrop, snapshot)
            snapshot.pop()
            snapshot.restore()
        black = Gdk.RGBA()
        black.parse('rgba(0,0,0,0.68)')
        snapshot.append_color(black, bounds)
        snapshot.pop()

    def logo_image(self, game, width, height, priority=1):
        path = game.get('logo', '')
        if path and Path(path).is_file():
            try:
                picture = SquarePicture(None, width, height, radius=0)
                return self.request_picture(picture, path, width, height, priority, kind='logo')
            except GLib.Error:
                pass
        return Gtk.Label(label=game['title'], wrap=True, justify=Gtk.Justification.CENTER,
                         width_request=width, height_request=height, max_width_chars=24,
                         ellipsize=Pango.EllipsizeMode.END, css_classes=['title-1'])

    def load_square_covers(self):
        while self.square_queue and self.square_active < 3:
            game, card = self.square_queue.pop(0)
            self.square_active += 1
            client = SteamGridDB(self.settings.get('steamgriddb_key', ''), self.library.root / 'covers')
            mode = self.view_mode
            width, height = cover_size_for(self.settings, mode)
            field = 'logo' if mode == 'list' else 'square_cover'
            def finished(result, game=game, card=card, mode=mode, width=width, height=height, field=field):
                try:
                    if result:
                        latest = next((row for row in self.library.games() if row['id'] == game['id']), None)
                        if latest:
                            if not Path(latest.get(field) or '').is_file():
                                latest.update(result)
                                self.library.put(latest)
                            if self.view_mode == mode and card.get_parent():
                                card.set_child(self.logo_image(latest, width, height) if mode == 'list' else
                                               self.cover({'cover': latest['square_cover']}, width, height, square=True))
                except Exception as error:
                    self.error(error)
                finally:
                    self.square_active -= 1
                    self.load_square_covers()
            def failed(error, done=finished):
                done(None)
            self.background(lambda game=game, client=client, mode=mode: client.logo(game) if mode == 'list' else client.square_cover(game), finished, failed)

    def matches_game(self, game):
        return (self.search.get_text().casefold() in game['title'].casefold() and
                (self.active_category is None or self.active_category in game.get('categories', [])))

    def update_categories(self):
        names = [None] + self.category_names
        index = names.index(self.active_category) if self.active_category in names else 0
        for offset, label in zip((-1, 0, 1), self.category_labels):
            name = names[(index + offset) % len(names)]
            label.set_text((name or tr('Todos')) if offset == 0 or len(names) > 1 else '')
            label.set_tooltip_text(name or tr('Todos'))

    def clear_library_filters(self):
        self.active_category = None
        self.search.set_text('')
        self.update_categories()
        self.filter()
        self.focus_library()

    def change_category(self, step):
        names = [None] + self.category_names
        index = names.index(self.active_category) if self.active_category in names else 0
        self.active_category = names[(index + step) % len(names)]
        self.update_categories()
        self.filter()

    def change_grid_page(self, step):
        if self.view_mode != 'grid':
            return False
        games = [game for game in self.library_games if self.matches_game(game)]
        _, page, pages = grid_page(games, self.selected_game)
        target = page + step
        if not 0 <= target < pages:
            return False
        index = target * 12 if step > 0 else min(len(games), (target + 1) * 12) - 1
        self.selected_game = games[index]['id']
        self.library_scroll.get_vadjustment().set_value(0)
        self.reload()
        self.focus_library()
        revision = self.reload_revision
        def reveal():
            if revision == self.reload_revision:
                selected = self.selected_tile()
                if selected:
                    self.select_tile(selected)
            return False
        GLib.timeout_add(80, reveal)
        return True

    def filter(self):
        if self.view_mode == 'grid' and hasattr(self, 'library_games'):
            signature = (self.search.get_text(), self.active_category)
            if signature != self.grid_filter_signature:
                self.reload()
                return
        if self.view_mode == 'grid':
            self.flow.invalidate_filter()
        count = total = 0
        child = self.flow.get_first_child()
        while child:
            total += 1
            visible = self.matches_game(child.game)
            count += visible
            if self.view_mode != 'grid':
                child.set_visible(visible)
            child = child.get_next_sibling()
        unique_count = len({tile.game['id'] for tile in self.tiles()})
        if self.view_mode == 'grid' and hasattr(self, 'library_games'):
            total = len(self.library_games)
            unique_count = sum(self.matches_game(game) for game in self.library_games)
        self.count.set_text(f"{unique_count}{tr(' juegos')}")
        if self.view_mode == 'grid':
            self.flow.set_min_children_per_line(1)
            self.flow.set_max_children_per_line(12)
        self.empty.set_title(tr('Tu biblioteca está vacía') if total == 0 else tr('No hay coincidencias'))
        self.empty.set_description(tr('Empieza escaneando tus juegos de Steam o Faugus. También puedes añadir un script o una AppImage.')
                                   if total == 0 else tr('Prueba otra búsqueda o cambia de categoría.'))
        self.empty_scan.set_visible(total == 0)
        self.empty_add.set_visible(total == 0)
        self.empty_clear.set_visible(total > 0)
        self.stack.set_visible_child_name('games' if count else 'empty')
        self.ps5_selector.set_visible(self.view_mode == 'ps5' and count > 0 and
                                      ring_for(self.settings, self.view_mode)['focus_ring_enabled'])
        if count and self.selected_game not in [tile.game['id'] for tile in self.tiles()]:
            self.focus_game(self.tiles()[0].game)
        self.update_alphabet()
        self.update_image_window()
        self.schedule_image_window()
        if self.view_mode in ('carousel', 'list') and count:
            GLib.idle_add(self.center_tile, self.selected_tile())

    def request_banner(self, game, done, failed):
        identity = game['id']
        if identity in self.banner_requests:
            self.banner_requests[identity].append((done, failed))
            return
        self.banner_requests[identity] = [(done, failed)]
        client = SteamGridDB(self.settings.get('steamgriddb_key', ''), self.library.root / 'covers')
        def complete(result):
            if result:
                latest = next((row for row in self.library.games() if row['id'] == identity), None)
                if latest:
                    latest.update(result)
                    self.library.put(latest)
                game.update(result)
            callbacks = self.banner_requests.pop(identity, [])
            for success, _ in callbacks:
                success(result)
        def error(message):
            for _, failure in self.banner_requests.pop(identity, []):
                failure(message)
        def ready(result):
            try:
                complete(result)
            except Exception as exc:
                error(str(exc))
        self.background(lambda: client.banner(game), ready, error)

    def select_game(self, game):
        self.clicked_game = game['id']
        self.focus_game(game)

    def edit_game(self, game):
        if game['kind'] == 'local':
            self.edit(game)
        else:
            self.details(game)

    @timed('ui.alphabet')
    def update_alphabet(self):
        games = ([game for game in self.library_games if self.matches_game(game)] if self.view_mode == 'grid'
                 else [tile.game for tile in self.tiles()])
        current = next((game['title'] for game in games if game['id'] == self.selected_game), '')
        letters = alphabet_window([game['title'] for game in games], current)
        for label, letter in zip(self.alphabet_labels, letters):
            label.set_text(letter)
        self.alphabet_strip.set_tooltip_text(tr('LB/L1: letra anterior · ') + letters[1] + tr(' · RB/R1: letra siguiente'))

    def schedule_game_information(self, game):
        timer = getattr(self, 'information_timer', None)
        if timer:
            GLib.source_remove(timer)
            self.information_timer = None
        if getattr(self, '_information_widgets', None) is None:
            self.update_game_information(game)
            return
        self.information_revision = getattr(self, 'information_revision', 0) + 1
        revision = self.information_revision
        def update():
            if revision != self.information_revision:
                return False
            self.information_timer = None
            if self.selected_game == game['id']:
                self.update_game_information(game)
            return False
        self.information_timer = GLib.timeout_add(120, update)

    @timed('ui.focus_game')
    def focus_game(self, game):
        self.spotlight_title.set_text(game['title'])
        if self.view_mode == 'list':
            self.update_list_cover(game)
        if self.selected_game != game['id']:
            self.info_scroll.get_vadjustment().set_value(0)
        self.schedule_game_information(game)
        self.selected_game = game['id']
        self.update_image_window()
        self.update_alphabet()
        selected_tile = self.selected_tile()
        self.active_tile = selected_tile
        self.update_focus_spacing()
        child = self.flow.get_first_child()
        while child:
            target = child.button
            if child == selected_tile:
                target.add_css_class('selected-game')
            else:
                target.remove_css_class('selected-game')
            child = child.get_next_sibling()
        if self.view_mode != 'grid' and not self.carousel_recycling:
            selected = selected_tile
            if selected:
                GLib.timeout_add(40, self.center_tile, selected)
        banners = background_assets(self.settings, game)
        if self.focused_game == game['id'] and self.focused_banner == banners:
            return
        self.focused_banner = banners
        self.focused_game = game['id']
        self.focus_revision += 1
        revision = self.focus_revision
        if self.focus_timer:
            GLib.source_remove(self.focus_timer)
            self.focus_timer = None
        for ticket in getattr(self, 'background_tickets', []):
            ticket.cancelled = True
        self.background_tickets = []
        paths = background_assets(self.settings, game)
        scale = self.get_scale_factor()
        width = min(3840, max(1920, self.get_width() * scale))
        height = min(2160, max(1080, self.get_height() * scale))
        pending = {i for i, path in enumerate(paths) if path and Path(path).is_file()}
        results = {}
        # Keep the last frame until its replacements are ready to avoid a flash.
        if not pending:
            self.backdrop.set_paintable(None)
            self.backdrop.secondary_texture = None
            self.backdrop_fill.set_texture(None)
        def ready(index, path, result, error):
            if revision != self.focus_revision:
                return
            if result is not None:
                texture, color = result
                results[index] = texture
                self.backdrop_fill.colors[path] = color
            pending.discard(index)
            if pending:
                return
            texture, secondary = results.get(0), results.get(1)
            self.backdrop.set_paintable(texture)
            self.backdrop.secondary_texture = secondary
            self.backdrop_fill.set_texture(texture, paths[0], secondary, paths[1])
        for index in sorted(pending):
            path = paths[index]
            prepare = lambda texture, path=path: (texture, images.prepared(
                'dominant-color', path, lambda: BlurredBackdrop.dominant_color(path, texture)))
            done = lambda result, error, index=index, path=path: ready(index, path, result, error)
            self.background_tickets.append(images.request(path, width, height, done, priority=0, prepare=prepare, kind='background'))

    def information_widgets(self):
        if getattr(self, '_information_widgets', None) is not None:
            return self._information_widgets
        widgets = {}
        activity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                           hexpand=True, valign=Gtk.Align.START)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       hexpand=True, valign=Gtk.Align.START,
                       css_classes=['stat-card', 'compact-info'])
        self.game_information.append(activity)
        self.game_information.append(info)
        def label(parent, key, css='info-text', **kwargs):
            item = Gtk.Label(xalign=0, wrap=True, css_classes=[css], **kwargs)
            widgets[key] = item
            parent.append(item)
            return item
        heading = Gtk.Box(spacing=12)
        activity.append(heading)
        label(heading, 'activity_title', 'info-heading', hexpand=True).set_text(tr('Tu actividad'))
        label(heading, 'status')
        cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                            min_children_per_line=1, max_children_per_line=2,
                            column_spacing=8, row_spacing=8)
        activity.append(cards)
        for key, title in (('seconds', tr('Tiempo jugado')), ('sessions', tr('Sesiones en Estante')),
                           ('last_seconds', tr('Última sesión')), ('last_played', tr('Última vez'))):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=['stat-card'])
            card.append(Gtk.Label(label=title, xalign=0, css_classes=['info-text']))
            label(card, key, 'stat-value')
            cards.append(card)
        label(activity, 'note')
        label(info, 'info_title', 'info-heading').set_text(tr('Información del juego'))
        for key in ('description', 'developers', 'publishers', 'genres', 'platforms', 'release', 'missing'):
            label(info, key)
        link = Gtk.LinkButton(uri='https://www.wikidata.org', label=tr('Ficha en Wikidata'), halign=Gtk.Align.START)
        widgets['link'] = link
        info.append(link)
        widgets['technical_separator'] = Gtk.Separator()
        info.append(widgets['technical_separator'])
        for key in ('source', 'runner', 'path'):
            label(info, key)
        label(activity, 'history_title', 'info-heading').set_text(tr('Sesiones recientes'))
        label(activity, 'history_empty').set_text(tr('Las sesiones completadas desde Estante aparecerán aquí.'))
        widgets['history'] = []
        for _ in range(5):
            row = Gtk.Box(spacing=16)
            date = Gtk.Label(xalign=0, hexpand=True, css_classes=['info-text'])
            elapsed = Gtk.Label(css_classes=['info-text'])
            error = Gtk.Label(label=tr('Salida con error'), css_classes=['info-text'])
            for child in (date, elapsed, error):
                row.append(child)
            activity.append(row)
            widgets['history'].append((row, date, elapsed, error))
        self._information_widgets = widgets
        return widgets

    @timed('ui.information')
    def update_game_information(self, game):
        timer = getattr(self, 'information_timer', None)
        if timer:
            GLib.source_remove(timer)
            self.information_timer = None
        self.information_revision = getattr(self, 'information_revision', 0) + 1
        widgets = self.information_widgets()
        def text(key, value, visible=True):
            widgets[key].set_text(value)
            widgets[key].set_visible(visible)
        stats = self.library.game_stats(game)
        process = self.processes.get(game['id'])
        running = game['id'] in getattr(self, 'running_sessions', set()) or (process is not None and process.poll() is None)
        text('status', tr('En ejecución') if running else tr('Listo para jugar'))
        for key in ('seconds', 'last_seconds'):
            text(key, duration(stats[key]))
        text('sessions', str(stats['sessions']))
        text('last_played', played_date(stats['last_played']))
        text('note', tr('Tiempo importado de Faugus. Las sesiones cuentan solo las registradas en Estante.')
             if game['kind'] == 'faugus' else tr('Actividad registrada al finalizar cada sesión iniciada desde Estante.'))
        metadata = game.get('metadata') or {}
        if hasattr(self, 'synopsis_label'):
            synopsis = metadata.get('synopsis') or metadata.get('description') or tr('Añade una sinopsis desde Editar → Editar ficha a mano.')
            self.synopsis_label.set_text(synopsis)
            self.synopsis_label.set_tooltip_text(synopsis)
            for index, label in enumerate(self.genre_labels):
                values = metadata.get('genres', [])
                label.get_parent().set_visible(index < len(values))
                if index < len(values):
                    label.set_text(values[index])

        text('description', metadata.get('description', ''), bool(metadata.get('description')))
        for title, key in ((tr('Estudio'), 'developers'), (tr('Editora'), 'publishers'),
                            (tr('Géneros'), 'genres'), (tr('Plataformas'), 'platforms')):
            text(key, title + ': ' + (', '.join(metadata.get(key, [])) or tr('Sin datos')), bool(metadata))
        released = metadata.get('release_date') or tr('Sin datos')
        try:
            released = datetime.strptime(released, '%Y-%m-%d').strftime('%d/%m/%Y')
        except ValueError:
            pass
        text('release', tr('Primer lanzamiento registrado: ') + released, bool(metadata))
        text('missing', tr('Añade la ficha para ver estudio, editora, lanzamiento y géneros.'), not metadata)
        widgets['link'].set_visible(bool(metadata.get('source')))
        widgets['link'].set_uri(metadata.get('source') or 'https://www.wikidata.org')
        source = ('Steam' if game['kind'] == 'steam' else 'Faugus') + ' · ' + ('Flatpak' if game.get('install') == 'flatpak' else tr('Nativo')) if game['kind'] in ('steam', 'faugus') else (tr('Script de Linux') if game.get('path', '').endswith('.sh') else 'AppImage')
        technical = self.settings.get('show_launcher_details', {}).get(self.view_mode, True) if hasattr(self, 'settings') else True
        widgets['technical_separator'].set_visible(technical)
        text('source', source, technical)
        text('runner', tr('Perfil de ejecución: ') + str(game.get('runner', '')), technical and bool(game.get('runner')))
        text('path', tr('Archivo: ') + Path(game.get('path') or '').name, technical and bool(game.get('path')))
        widgets['path'].set_tooltip_text(game.get('path') or '')
        text('history_empty', tr('Las sesiones completadas desde Estante aparecerán aquí.'), not stats['history'])
        for index, (row, date, elapsed, error) in enumerate(widgets['history']):
            visible = index < len(stats['history'])
            row.set_visible(visible)
            if visible:
                session = stats['history'][index]
                date.set_text(played_date(session['started']))
                elapsed.set_text(duration(session['seconds']))
                error.set_visible(bool(session['exit_code']))

    def close_panel(self):
        self.panel_revision += 1
        self.drawer.set_reveal_child(False)
        release_images(self.sidebar)
        self.artwork_gallery = None
        self.panel_back = None
        self.focus_library()

    def panel(self, title, back=None):
        self.panel_revision += 1
        self.artwork_gallery = None
        self.panel_back = back
        while child := self.sidebar.get_first_child():
            release_images(child)
            self.sidebar.remove(child)
        header = Gtk.Box(spacing=8)
        if back:
            previous = Gtk.Button(icon_name='go-previous-symbolic', tooltip_text=tr('Volver'))
            previous.connect('clicked', lambda *_: back())
            header.append(previous)
        header.append(Gtk.Label(label=title, ellipsize=Pango.EllipsizeMode.END,
                                hexpand=True, xalign=0, css_classes=['heading']))
        close = Gtk.Button(icon_name='window-close-symbolic', tooltip_text=tr('Cerrar panel'))
        close.connect('clicked', lambda *_: self.close_panel())
        header.append(close)
        self.sidebar.append(margins(header, 12))
        self.sidebar.append(Gtk.Separator())
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14))
        scroll.set_child(content)
        self.sidebar.append(scroll)
        self.drawer.set_reveal_child(True)
        revision = self.panel_revision
        def focus_content():
            if revision == self.panel_revision and self.drawer.get_reveal_child():
                def first(widget):
                    child = widget.get_first_child()
                    while child:
                        if isinstance(child, (Gtk.Button, Gtk.CheckButton, Gtk.Entry, Gtk.PasswordEntry, Gtk.SearchEntry)) and child.get_sensitive():
                            return child
                        found = first(child)
                        if found:
                            return found
                        child = child.get_next_sibling()
                    return None
                target = first(content)
                if target:
                    target.grab_focus()
            return False
        GLib.idle_add(focus_content)
        return content

    def details(self, game):
        self.focus_game(game)
        box = self.panel(tr('Editar · ') + game['title'])
        revision = self.panel_revision
        hero = Gtk.Overlay(css_classes=['game-hero'])
        hero.set_overflow(Gtk.Overflow.HIDDEN)
        hero.set_child(Gtk.Box(height_request=160))
        backdrop = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER,
                               hexpand=True, vexpand=True)
        hero.add_overlay(backdrop)
        hero.add_overlay(Gtk.Box(css_classes=['hero-shade']))
        image = self.cover(game, 84, 126)
        # The frame constrains allocation even when the sidebar becomes wide.
        frame = Gtk.AspectFrame(ratio=2/3, obey_child=False,
                                halign=Gtk.Align.START, valign=Gtk.Align.END)
        frame.set_size_request(84, 126)
        frame.set_child(image)
        hero.add_overlay(margins(frame, 14))
        box.append(hero)
        banner_status = Gtk.Label(wrap=True, xalign=0, css_classes=['dim-label'])
        def show_banner(path):
            backdrop.set_paintable(images.load(path, 1280, 720))
        cached = game.get('banner', '')
        if cached and Path(cached).is_file():
            try:
                show_banner(cached)
            except GLib.Error:
                cached = ''
        else:
            cached = ''
        if not cached:
            banner_status.set_text(tr('Elige un fondo o usa el scraping desde Ajustes.'))
        self.game_editor_actions(box, game, banner_status)
        if game['kind'] == 'local':
            box.append(button(tr('Editar…'), lambda: self.edit(game)))
        else:
            explanation = (tr('Se inicia con Steam y utiliza la configuración del cliente.') if game['kind'] == 'steam' else
                           tr('Usa el runner, los parámetros y el prefijo\nconfigurados en Faugus.'))
            box.append(Gtk.Label(label=explanation, wrap=True, xalign=0, css_classes=['dim-label']))

    def edit_categories(self, game):
        latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
        box = self.panel(tr('Categorías'), lambda: self.edit_game(latest))
        box.append(Gtk.Label(label=tr('Selecciona las categorías del juego. Puedes crearlas y gestionarlas en Ajustes → Categorías.'),
                             wrap=True, xalign=0))
        choices = {}
        for name in self.library.categories():
            choice = Gtk.CheckButton(label=name, active=name in latest.get('categories', []),
                                     css_classes=['category-choice'])
            choices[name] = choice
            box.append(choice)
        def save():
            current = next((row for row in self.library.games() if row['id'] == game['id']), latest)
            categories = [name for name, choice in choices.items() if choice.get_active()]
            self.library.put(dict(current, categories=categories))
            self.close_panel()
            self.reload()
        box.append(button(tr('Guardar categorías'), save, 'suggested-action'))

    def wait_to_hide_for_game(self, identity, process):
        def check():
            if (self.session_window_closed or identity not in self.running_sessions or
                    self.processes.get(identity) is not process):
                return False
            # Wait for the game to take focus instead of hiding behind a loading screen.
            if not self.is_active():
                self.hide_for_game(identity)
                return False
            return True
        GLib.timeout_add(250, check)
        return False

    def hide_for_game(self, identity):
        self.hidden_game_sessions.add(identity)
        if not self.game_window_hold:
            self.get_application().hold()
            self.game_window_hold = True
        self.set_visible(False)

    def restore_after_game(self, identity):
        self.hidden_game_sessions.discard(identity)
        if self.hidden_game_sessions or not self.game_window_hold:
            return
        self.game_window_hold = False
        if not self.session_window_closed:
            self.present()
            self.focus_library()
        self.get_application().release()

    def play(self, game):
        previous = self.processes.get(game['id'])
        if game['id'] in self.running_sessions or (previous and previous.poll() is None):
            self.error(tr('Este juego ya está en ejecución.'))
            return
        try:
            process = launch(game, self.library.root)
        except Exception as error:
            self.error(error)
            return
        self.processes[game['id']] = process
        self.running_sessions.add(game['id'])
        started = datetime.now().isoformat()
        started_at = time.monotonic()
        self.close_panel()
        self.update_game_information(game)
        self.toast.add_toast(Adw.Toast(title=f"{tr('Iniciando ')}{game['title']}…"))
        hide = self.settings.get('hide_while_playing', False)
        def started():
            GLib.idle_add(self.wait_to_hide_for_game, game['id'], process)
        def finished(code):
            self.running_sessions.discard(game['id'])
            try:
                self.library.record_session(game, time.monotonic() - started_at, started, code)
                if self.selected_game == game['id']:
                    latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
                    self.update_game_information(latest)
            except Exception as error:
                self.error(error)
            if code:
                self.error(f"{tr('El lanzador terminó con código ')}{code}. Consulta {self.library.root / 'launch.log'}")
            self.restore_after_game(game['id'])
        def failed(message):
            self.running_sessions.discard(game['id'])
            self.restore_after_game(game['id'])
            self.error(tr(message))
        self.background(lambda: wait_for_game(game, process, on_started=started) if hide else process.wait(), finished, failed)

    def remove(self, game):
        box = self.panel(tr('¿Quitar este juego?'), back=lambda: self.edit_game(game))
        box.append(Gtk.Label(label=game['title'], wrap=True, xalign=0, css_classes=['title-3']))
        explanation = (tr('Solo se quita de Estante. El juego permanece instalado y no volverá a aparecer al escanear. Puedes restaurarlo desde Ajustes → Escaneo y scraping.')
                       if game['kind'] in ('faugus', 'steam') else tr('El archivo del juego se conserva en tu disco.'))
        box.append(Gtk.Label(label=explanation, wrap=True, xalign=0))
        def confirm():
            try:
                self.library.remove(game)
                self.close_panel()
                self.reload()
            except Exception as error:
                self.error(error)
        box.append(button(tr('Quitar de la biblioteca'), confirm, 'destructive-action'))
        box.append(button(tr('Cancelar'), lambda: self.edit_game(game)))

    def field(self, box, title, value='', secret=False):
        box.append(Gtk.Label(label=title, xalign=0, css_classes=['heading']))
        entry = Gtk.PasswordEntry(show_peek_icon=True) if secret else Gtk.Entry()
        entry.set_text(value)
        box.append(entry)
        return entry

    def edit(self, game=None, draft=None):
        box = self.panel(tr('Editar juego') if game else tr('Añadir juego'),
                         back=self.close_panel if game else None)
        row = draft or game or {}
        if game:
            self.game_editor_actions(box, game)
            box.append(Gtk.Label(label=tr('Ejecución'), xalign=0, css_classes=['title-3']))
        title = self.field(box, tr('Nombre'), row.get('title', ''))
        path = self.field(box, tr('Script o AppImage'), row.get('path', ''))
        def choose():
            draft = {**row, 'title': title.get_text(), 'path': path.get_text(),
                     'arguments': arguments.get_text(), 'cwd': cwd.get_text()}
            self.choose_file(draft, bool(game))
        box.append(button(tr('Seleccionar archivo…'), choose))
        arguments = self.field(box, tr('Parámetros'), row.get('arguments', ''))
        arguments.set_placeholder_text(tr('--fullscreen --profile "Mi perfil"'))
        cwd = self.field(box, tr('Directorio de trabajo (opcional)'), row.get('cwd', ''))
        cwd.set_placeholder_text(tr('Por defecto, la carpeta del juego'))
        feedback = Gtk.Label(wrap=True, xalign=0, css_classes=['error'])
        box.append(feedback)
        def save():
            try:
                result = self.library.local_game(title.get_text(), path.get_text(), arguments.get_text(),
                    cwd.get_text(), row.get('id'), row.get('cover', ''))
                result.update({key: row[key] for key in ('banner', 'banner_secondary', 'square_cover', 'logo', 'steamgriddb_id', 'metadata', 'categories') if key in row})
                self.library.put(result)
            except Exception as error:
                feedback.set_text(str(error))
                return
            self.close_panel()
            self.reload()
        box.append(button(tr('Guardar') if game else tr('Añadir'), save, 'suggested-action'))

    def choose_file(self, draft, editing):
        def back():
            self.edit(draft if editing else None, draft=draft)
        box = self.panel(tr('Seleccionar juego'), back=back)
        picker = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        picker.set_size_request(-1, 380)
        picker.set_hexpand(True)
        formats = Gtk.FileFilter()
        formats.set_name(tr('Scripts y AppImages'))
        for pattern in ('*.sh', '*.AppImage', '*.appimage'):
            formats.add_pattern(pattern)
        picker.add_filter(formats)
        if draft.get('path') and Path(draft['path']).is_file():
            picker.set_file(Gio.File.new_for_path(draft['path']))
        box.append(picker)
        feedback = Gtk.Label(wrap=True, xalign=0, css_classes=['error'])
        box.append(feedback)
        def selected():
            chosen = picker.get_file()
            filename = chosen.get_path() if chosen else None
            if not filename or not Path(filename).is_file():
                feedback.set_text(tr('Selecciona un archivo local .sh o .AppImage.'))
                return
            draft['path'] = filename
            if not draft.get('title'):
                draft['title'] = Path(filename).stem
            back()
        box.append(button(tr('Seleccionar'), selected, 'suggested-action'))
        box.append(button(tr('Cancelar'), back))

    def metadata_edit(self, game):
        latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
        metadata = dict(latest.get('metadata', {}))
        box = self.panel(tr('Editar ficha del juego'), back=lambda: self.edit_game(latest))
        title = self.field(box, tr('Título de la ficha'), metadata.get('title', latest['title']))
        entries = {}
        for label, field in ((tr('Estudios (separados por comas)'), 'developers'),
                             (tr('Editoras (separadas por comas)'), 'publishers'),
                             (tr('Géneros (separados por comas)'), 'genres'),
                             (tr('Plataformas (separadas por comas)'), 'platforms')):
            entries[field] = self.field(box, label, ', '.join(metadata.get(field, [])))
        released = self.field(box, tr('Fecha de lanzamiento (DD/MM/AAAA)'), metadata.get('release_date', ''))
        box.append(Gtk.Label(label=tr('Descripción'), xalign=0, css_classes=['heading']))
        description = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, height_request=130)
        description.get_buffer().set_text(metadata.get('description', ''))
        description_scroll = Gtk.ScrolledWindow(min_content_height=130,
            hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        description_scroll.set_child(description)
        box.append(description_scroll)
        box.append(Gtk.Label(label=tr('Sinopsis'), xalign=0, css_classes=['heading']))
        synopsis = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, height_request=130)
        synopsis.get_buffer().set_text(metadata.get('synopsis', ''))
        box.append(synopsis)
        box.append(button(tr('Buscar sinopsis en Steam'), lambda: self.synopsis_search(latest)))
        feedback = Gtk.Label(wrap=True, xalign=0, css_classes=['error'])
        box.append(feedback)
        def save():
            date = released.get_text().strip()
            if date:
                for pattern in ('%d/%m/%Y', '%Y-%m-%d'):
                    try:
                        date = datetime.strptime(date, pattern).strftime('%Y-%m-%d')
                        break
                    except ValueError:
                        continue
                else:
                    feedback.set_text(tr('Introduce una fecha válida en formato DD/MM/AAAA o deja el campo vacío.'))
                    return
            buffer = description.get_buffer()
            synopsis_buffer = synopsis.get_buffer()
            edited = {**metadata, 'title': title.get_text().strip(), 'release_date': date,
                      'description': buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True),
                      'synopsis': synopsis_buffer.get_text(synopsis_buffer.get_start_iter(), synopsis_buffer.get_end_iter(), True).strip(),
                      'manually_edited': True}
            edited.update({field: [value.strip() for value in entry.get_text().split(',') if value.strip()]
                           for field, entry in entries.items()})
            try:
                current = next((row for row in self.library.games() if row['id'] == game['id']), latest)
                updated = dict(current, metadata=edited)
                self.library.put(updated)
            except Exception as error:
                feedback.set_text(str(error))
                return
            self.close_panel()
            self.reload()
        box.append(button(tr('Guardar ficha'), save, 'suggested-action'))
        box.append(button(tr('Cancelar'), lambda: self.edit_game(latest)))

    def synopsis_search(self, game):
        box = self.panel(tr('Buscar sinopsis en Steam'), back=lambda: self.metadata_edit(game))
        revision = self.panel_revision
        query = Gtk.SearchEntry()
        query.set_text(game['title'])
        box.append(query)
        status = Gtk.Label(wrap=True, xalign=0)
        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        client = SteamArtwork()
        generation = [0]
        def choose(row):
            generation[0] += 1
            token = generation[0]
            def show(text):
                if revision != self.panel_revision or token != generation[0]:
                    return
                while child := results.get_first_child():
                    results.remove(child)
                results.append(Gtk.Label(label=row['name'], wrap=True, xalign=0, css_classes=['title-3']))
                results.append(Gtk.Label(label=text, wrap=True, xalign=0))
                def save():
                    latest = next((item for item in self.library.games() if item['id'] == game['id']), None)
                    if latest is None:
                        return
                    self.library.put(dict(latest, metadata={**latest.get('metadata', {}), 'synopsis': text}))
                    self.reload()
                    self.metadata_edit(latest)
                results.append(button(tr('Usar esta sinopsis'), save, 'suggested-action'))
            self.background(lambda: client.synopsis(row['id']), show, status.set_text)
        def search():
            generation[0] += 1
            token = generation[0]
            def show(rows):
                if revision != self.panel_revision or token != generation[0]:
                    return
                while child := results.get_first_child():
                    results.remove(child)
                status.set_text(tr('Elige el juego.'))
                for row in rows:
                    results.append(button(row['name'], lambda row=row: choose(row)))
            self.background(lambda: client.search(query.get_text().strip()), show, status.set_text)
        query.connect('activate', lambda *_: search())
        box.append(button(tr('Buscar'), search))
        box.append(status)
        box.append(results)

    def metadata_search(self, game):
        box = self.panel(tr('Ficha del juego'), back=lambda: self.edit_game(game))
        box.append(button(tr('Editar ficha a mano'), lambda: self.metadata_edit(game)))
        revision = self.panel_revision
        query = Gtk.SearchEntry(placeholder_text=tr('Título del juego…'))
        query.set_text(game['title'])
        box.append(query)
        status = Gtk.Label(label=tr('Busca el título y revisa la ficha antes de guardarla.'), wrap=True,
                           wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=36, xalign=0)
        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        client = GameMetadata(self.library.root / 'metadata')
        generation = [0]

        def clear():
            while child := results.get_first_child():
                release_images(child)
                results.remove(child)

        def choose(item):
            generation[0] += 1
            token = generation[0]
            clear()
            status.set_text(tr('Cargando ficha…'))
            def preview(metadata):
                if revision != self.panel_revision or token != generation[0]:
                    return
                status.set_text(tr('Revisa que corresponda a tu juego.'))
                results.append(Gtk.Label(label=metadata.get('title') or item['name'], wrap=True,
                                         wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=36,
                                         xalign=0, css_classes=['title-3']))
                if metadata.get('description'):
                    results.append(Gtk.Label(label=metadata['description'], wrap=True,
                        wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=36, xalign=0))
                for title, value in (
                        (tr('Estudio'), ', '.join(metadata['developers'])),
                        (tr('Editora'), ', '.join(metadata['publishers'])),
                        ('Lanzamiento', metadata['release_date']),
                        (tr('Géneros'), ', '.join(metadata['genres'])),
                        (tr('Plataformas'), ', '.join(metadata['platforms']))):
                    results.append(Gtk.Label(label=f'{title}: {value or tr('Sin datos')}', wrap=True,
                        wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=36, xalign=0))
                results.append(Gtk.LinkButton(uri=metadata['source'], label=tr('Ver fuente en Wikidata')))
                def save():
                    try:
                        latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
                        self.library.put(dict(latest, metadata={**metadata, **({'synopsis': latest.get('metadata', {})['synopsis']} if latest.get('metadata', {}).get('synopsis') else {})}))
                        self.close_panel()
                        self.reload()
                    except Exception as error:
                        self.error(error)
                results.append(button(tr('Usar esta ficha'), save, 'suggested-action'))
            self.background(lambda: client.fetch(item['id']), preview, status.set_text)

        def search():
            title = query.get_text().strip()
            if not title:
                return
            generation[0] += 1
            token = generation[0]
            clear()
            status.set_text(tr('Buscando en Wikidata…'))
            def show(rows):
                if revision != self.panel_revision or token != generation[0]:
                    return
                status.set_text(tr('Elige el resultado correcto.') if rows else tr('Sin resultados. Prueba con el título original.'))
                for row in rows:
                    results.append(button(row['name'], lambda item=row: choose(item)))
                    if row['description']:
                        results.append(Gtk.Label(label=row['description'], wrap=True,
                            wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=36, xalign=0, css_classes=['dim-label']))
            self.background(lambda: client.search(title), show, status.set_text)
        query.connect('activate', lambda *_: search())
        box.append(button(tr('Buscar en Wikidata'), search))
        box.append(status)
        box.append(results)

    def preferences(self, section='global'):
        self.close_panel()
        if self.preferences_view:
            self.pages.remove(self.preferences_view)
        self.preferences_view = SettingsView(self, button, margins, section)
        self.pages.add_named(self.preferences_view, 'settings')
        self.pages.set_visible_child_name('settings')
        GLib.idle_add(lambda: (self.preferences_view.child_focus(Gtk.DirectionType.TAB_FORWARD), False)[1])

    def leave_preferences(self):
        self.pages.set_visible_child_name('library')
        self.focus_library()
        selected = self.selected_tile()
        if selected and self.view_mode != 'grid':
            GLib.timeout_add(250, self.center_tile, selected)

    @staticmethod
    def gallery_cards(flow):
        child = flow.get_first_child()
        while child:
            card = child.get_child()
            if card.get_visible() and card.get_sensitive():
                yield card
            child = child.get_next_sibling()

    def focus_artwork_gallery(self, flow, revision):
        if revision == self.panel_revision and flow == getattr(self, 'artwork_gallery', None):
            if not (self.get_focus() and self.get_focus().is_ancestor(flow)):
                card = next(self.gallery_cards(flow), None)
                if card:
                    card.grab_focus()

    def game_editor_actions(self, box, game, banner_status=None):
        def group(title, actions):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=['editor-group'])
            card.append(Gtk.Label(label=title, xalign=0, css_classes=['heading']))
            row = Gtk.Box(spacing=10, homogeneous=True)
            for label, callback in actions:
                row.append(button(label, callback))
            card.append(row)
            box.append(card)
            return card

        group(tr('Carátulas'), ((tr('Vertical (2:3)'), lambda: self.artwork(game)),
                               (tr('Cuadrada (1:1)'), lambda: self.artwork(game, square=True)),
                               (tr('Logo'), lambda: self.artwork(game, logo=True))))
        backgrounds = group(tr('Fondos'), (
            (tr('Fondo principal…'), lambda: self.artwork(game, banner=True)),
            (tr('Segundo fondo…'), lambda: self.artwork(game, secondary=True))))
        previews = Gtk.Box(spacing=10, homogeneous=True)
        preview_images = []
        for field in ('banner', 'banner_secondary'):
            frame = Gtk.AspectFrame(ratio=16/9, obey_child=False,
                                    hexpand=True, css_classes=['background-preview'])
            frame.set_overflow(Gtk.Overflow.HIDDEN)
            picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.COVER)
            frame.set_child(picture)
            previews.append(frame)
            preview_images.append((field, picture))
        backgrounds.insert_child_after(previews, backgrounds.get_first_child())
        def refresh_previews(*_):
            for field, picture in preview_images:
                path = game.get(field, '')
                texture = None
                if path and Path(path).is_file():
                    try:
                        texture = images.load(path, 960, 540)
                    except GLib.Error:
                        pass
                picture.set_paintable(texture)
        refresh_previews()
        if banner_status is not None:
            banner_status.connect('notify::label', refresh_previews)
            banner_status.set_visible(bool(banner_status.get_text()))
            banner_status.connect('notify::label',
                                  lambda label, *_: label.set_visible(bool(label.get_text())))
            backgrounds.append(banner_status)
        options = Gtk.Box(spacing=12)
        options.append(Gtk.Label(label=tr('Configura la división en los ajustes de cada apariencia.'),
                                 wrap=True, xalign=0, hexpand=True, css_classes=['dim-label']))
        if game.get('banner') and game.get('banner_secondary'):
            options.append(button(tr('Intercambiar fondos'), lambda: self.swap_backgrounds(game)))
        if game.get('banner_secondary'):
            remove = button(tr('Quitar segundo fondo'), lambda: self.remove_secondary_background(game), 'flat')
            remove.set_valign(Gtk.Align.CENTER)
            options.append(remove)
        backgrounds.append(options)
        group(tr('Información del juego'), (
            (tr('Buscar ficha del juego'), lambda: self.metadata_search(game)),
            (tr('Editar ficha a mano'), lambda: self.metadata_edit(game))))
        organization = group(tr('Organización'), ((tr('Categorías…'), lambda: self.edit_categories(game)),))
        organization.append(button(tr('Quitar de la biblioteca'), lambda: self.remove(game), 'destructive-action'))

    def swap_backgrounds(self, game):
        latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
        if not latest.get('banner') or not latest.get('banner_secondary'):
            return
        updated = dict(latest, banner=latest['banner_secondary'], banner_secondary=latest['banner'])
        self.library.put(updated)
        self.reload()
        self.edit_game(updated)

    def remove_secondary_background(self, game):
        latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
        self.library.put(dict(latest, banner_secondary=''))
        self.reload()
        self.edit_game(next(row for row in self.library.games() if row['id'] == game['id']))

    def artwork(self, game, banner=False, square=False, secondary=False, logo=False):
        banner = banner or secondary
        title = (tr('Elegir logo') if logo else tr('Elegir segundo fondo') if secondary else
                 tr('Elegir banner') if banner else tr('Elegir carátula 1:1') if square else tr('Elegir carátula'))
        box = self.panel(title, back=lambda: self.edit_game(game))
        revision = self.panel_revision
        query = Gtk.SearchEntry(placeholder_text=tr('Nombre del juego…'))
        query.set_text(game['title'])
        box.append(query)
        status = Gtk.Label(label=tr('Busca el juego y selecciona una imagen.'), wrap=True)
        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        client = SteamGridDB(self.settings.get('steamgriddb_key', ''), self.library.root / 'covers')
        igdb_client = IGDBArtwork(self.settings.get('igdb_client_id', ''),
                                 self.settings.get('igdb_client_secret', ''))
        generation = [0]
        selected_id = [game.get('steamgriddb_id')]
        def clear():
            while child := results.get_first_child():
                release_images(child)
                results.remove(child)
        def save_cover(path):
            if revision != self.panel_revision:
                return
            try:
                # Validate downloaded image before committing the selection.
                images.load(path)
                field = 'logo' if logo else ('banner_secondary' if secondary else ('banner' if banner else ('square_cover' if square else 'cover')))
                latest = next((row for row in self.library.games() if row['id'] == game['id']), game)
                updated = dict(latest, **{field: path})
                if not secondary:
                    updated['steamgriddb_id'] = selected_id[0]
                if not banner and not logo and selected_id[0] != game.get('steamgriddb_id'):
                    updated.pop('banner', None)
                self.library.put(updated)
            except Exception as error:
                self.error(error)
                return
            self.close_panel()
            self.reload()
            self.edit_game(updated)
        def manual_saved(path):
            selected_id[0] = game.get('steamgriddb_id')
            save_cover(path)
        own_images = Gtk.Expander(label=tr('Desde mi equipo o una URL'))
        manual = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        own_images.set_child(manual)
        box.append(own_images)
        picker = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        picker.set_size_request(-1, 300)
        image_filter = Gtk.FileFilter()
        image_filter.set_name(tr('Imágenes'))
        image_filter.add_pixbuf_formats()
        picker.add_filter(image_filter)
        picker.set_visible(False)
        manual.append(button(tr('Desde mi equipo…'), lambda: picker.set_visible(not picker.get_visible())))
        manual.append(picker)
        def import_local():
            chosen = picker.get_file()
            if not chosen or not chosen.get_path():
                status.set_text(tr('Selecciona una imagen de tu equipo.'))
                return
            self.background(lambda: client.import_artwork(chosen.get_path()), manual_saved, status.set_text)
        use_local = button(tr('Usar archivo seleccionado'), import_local)
        picker.bind_property('visible', use_local, 'visible', GObject.BindingFlags.SYNC_CREATE)
        manual.append(use_local)
        url = Gtk.Entry(placeholder_text='https://… (URL directa de la imagen)')
        manual.append(url)
        def import_url():
            address = url.get_text().strip()
            if not address:
                status.set_text(tr('Escribe la URL directa de una imagen.'))
                return
            status.set_text(tr('Descargando imagen…'))
            self.background(lambda: client.download(address, custom=True), manual_saved, status.set_text)
        manual.append(button(tr('Usar imagen de URL'), import_url))
        box.append(Gtk.Separator())
        def grids(item, steam=False, igdb=False):
            external = steam or igdb
            selected_id[0] = game.get('steamgriddb_id') if external else item['id']
            generation[0] += 1
            token = generation[0]
            clear()
            status.set_text(tr('Cargando imágenes…'))
            def show(rows):
                if token != generation[0] or revision != self.panel_revision:
                    return
                status.set_text(tr('Selecciona una imagen.') if rows else tr('No hay imágenes de este tipo para este juego.'))
                flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                    min_children_per_line=2, max_children_per_line=2, homogeneous=True,
                    column_spacing=12, row_spacing=12)
                self.artwork_gallery = flow
                results.append(flow)
                for row in rows[:18]:
                    card = button(tr('Cargando…'), lambda: None)
                    card.set_sensitive(not external)
                    banner_height = round(320 * row.get('height', 620) / max(1, row.get('width', 1920)))
                    width, height = (180, 90) if logo else (160, max(1, banner_height // 2)) if banner else ((120, 120) if square else (120, 180))
                    card.set_size_request(width, -1)
                    card.connect('clicked', lambda _, url=row['url']: self.background(
                        lambda: client.download(url, custom=external), manual_saved if external else save_cover, status.set_text))
                    flow.append(card)
                    dimensions = f"{row['width']} × {row['height']} px" if row.get('width') and row.get('height') else tr('Resolución no disponible')
                    details = Gtk.Label(label=dimensions, wrap=True, css_classes=['dim-label'])
                    def show_size(size, label=details, dimensions=dimensions):
                        weight = (f'{size / 1_000_000:.2f} MB' if size >= 1_000_000 else f'{size / 1000:.0f} KB') if size else tr('Peso no disponible')
                        label.set_text(dimensions + ' · ' + weight)
                    if not external:
                        self.background(lambda url=row['url']: client.artwork_size(url), show_size, lambda _: None)
                    def preview(path, target=card, width=width, height=height, details=details):
                        if revision != self.panel_revision:
                            return
                        if external:
                            texture = images.load(path, 320, 320)
                            if abs(texture.get_width() / texture.get_height() - 16 / 9) > 0.025:
                                target.set_visible(False)
                                return
                            target.set_sensitive(True)
                        image = self.cover({'cover': path}, width, height, square=square)
                        image.set_content_fit(Gtk.ContentFit.CONTAIN)
                        frame = Gtk.AspectFrame(ratio=width / height, obey_child=False)
                        frame.set_child(image)
                        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                        content.append(frame)
                        content.append(details)
                        target.set_child(content)
                        if not any(card.has_focus() for card in self.gallery_cards(flow)):
                            current = self.get_focus()
                            if not current or not current.is_ancestor(flow):
                                GLib.idle_add(lambda: (self.focus_artwork_gallery(flow, revision), False)[1])
                    self.background(lambda url=row.get('thumb', row['url']): client.download(url, custom=external), preview, status.set_text)
            self.background(lambda: igdb_client.images(item['id']) if igdb else (
                SteamArtwork().screenshots(item['id']) if steam else (
                client.logos(item['id']) if logo else client.heroes(item['id']) if banner else client.grids(item['id'], square=square))), show, status.set_text)
        def search(steam=False, igdb=False):
            search_text = query.get_text().strip()
            if not search_text:
                return
            generation[0] += 1
            token = generation[0]
            clear()
            status.set_text(tr('Buscando…'))
            def show(rows):
                if token != generation[0] or revision != self.panel_revision:
                    return
                status.set_text(tr('Elige el juego.') if rows else tr('No se encontraron juegos.'))
                for row in rows:
                    results.append(button(row['name'], lambda item=row: grids(item, steam=steam, igdb=igdb)))
            self.background(lambda: igdb_client.search(search_text) if igdb else (
                SteamArtwork().search(search_text) if steam else client.search(search_text)), show, status.set_text)
        query.connect('activate', lambda *_: search())
        box.append(Gtk.Label(label=tr('Buscar imágenes del juego'), xalign=0, css_classes=['heading']))
        sources = Gtk.Box(spacing=10, homogeneous=True)
        box.append(sources)
        sources.append(button(tr('Buscar en SteamGridDB'), search))
        if banner:
            sources.append(button(tr('Buscar capturas 16:9 en Steam'), lambda: search(steam=True)))
            sources.append(button(tr('Buscar fondos 16:9 en IGDB'), lambda: search(igdb=True)))
        box.append(status)
        box.append(results)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--version']:
        from version import __version__
        print('Estante ' + __version__)
        raise SystemExit(0)
    raise SystemExit(App().run(sys.argv))
