"""Dedicated in-window settings, split into global and per-view pages."""
from pathlib import Path
from library import SteamGridDB
from controls import controller_save_hint
from metadata import GameMetadata
from scraping import scrape_game, apply_scrape_patch
from i18n import tr
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gtk
from appearance import list_side_for, VIEW_NAMES, ring_for, with_ring, cover_radius_for, hero_position_for, cover_format_for
from version import __version__
from backgrounds import BUNDLED_BACKGROUNDS, resolve_background, background_split_for
from updates import latest_release, appimage_path, update_available, install_appimage, RELEASES_URL


def spatial_target(points, current, action):
    """Choose the nearest control in the requested screen direction."""
    if action not in ('left', 'right', 'up', 'down') or not points:
        return current
    x, y = points[current]
    dx, dy = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}[action]
    candidates = []
    for index, (px, py) in enumerate(points):
        forward = (px - x) * dx + (py - y) * dy
        cross = abs(py - y) if dx else abs(px - x)
        if forward > 1:
            candidates.append((forward + 2 * cross, cross, index))
    return min(candidates)[2] if candidates else current


class SettingsView(Gtk.Box):
    def __init__(self, shelf, button, margins, section='global'):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=['background'])
        self.shelf, self.button, self.margins = shelf, button, margins
        self.footers = {}
        self.save_buttons = {}
        self.save_hints = []
        header = Gtk.Box(spacing=14)
        header.append(button(tr('← Biblioteca'), shelf.leave_preferences))
        header.append(Gtk.Label(label=tr('Ajustes'), xalign=0, hexpand=True, css_classes=['title-2']))
        header.append(Gtk.WindowControls(side=Gtk.PackType.END))
        handle = Gtk.WindowHandle()
        handle.set_child(margins(header, 16))
        self.append(handle)
        self.append(Gtk.Separator())
        body = Gtk.Box(vexpand=True)
        self.append(body)
        nav = self.navigation = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, width_request=160), 16)
        body.append(nav)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.sections = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        body.append(self.sections)
        nav.append(button(tr('Globales'), lambda: self.show_section('global')))
        nav.append(button(tr('Escaneo y scraping'), lambda: self.show_section('scanning')))
        nav.append(button(tr('Categorías'), lambda: self.show_section('categories')))
        nav.append(margins(Gtk.Label(label=tr('APARIENCIA'), xalign=0, css_classes=['dim-label']), 8))
        for mode, name in VIEW_NAMES.items():
            nav.append(button(tr(name), lambda mode=mode: self.show_section(mode)))
        self.global_page()
        self.categories_page()
        self.scanning_page()
        for mode in VIEW_NAMES:
            self.appearance_page(mode)
        self.show_section(section)
        for control in self.controls(self):
            control.add_css_class('settings-control')

    @staticmethod
    def controls(root):
        types = (Gtk.Button, Gtk.CheckButton, Gtk.Switch, Gtk.Range, Gtk.SpinButton,
                 Gtk.Entry, Gtk.PasswordEntry)
        child = root.get_first_child()
        while child:
            if child.get_visible():
                if isinstance(child, types):
                    if child.get_sensitive():
                        yield child
                elif not isinstance(child, Gtk.Revealer) or child.get_reveal_child():
                    yield from SettingsView.controls(child)
            child = child.get_next_sibling()

    def navigate(self, action):
        if action == 'save':
            return self.save_current()
        focus = self.shelf.get_focus()
        navigation = list(self.controls(self.navigation))
        page = list(self.controls(self.sections.get_visible_child()))
        controls = navigation + page
        owner = next((control for control in controls
                      if focus == control or (focus and focus.is_ancestor(control))), None)
        if owner is None:
            navigation[0].grab_focus()
            return True
        if action == 'confirm':
            if isinstance(owner, Gtk.Switch):
                owner.set_active(not owner.get_active())
            elif isinstance(owner, Gtk.CheckButton):
                owner.set_active(True)
            elif isinstance(owner, Gtk.Button):
                owner.emit('clicked')
            return True
        if action in ('left', 'right'):
            direction = 1 if action == 'right' else -1
            if isinstance(owner, Gtk.Range):
                owner.set_value(owner.get_value() + direction * owner.get_adjustment().get_step_increment())
                return True
            if isinstance(owner, Gtk.SpinButton):
                owner.set_value(owner.get_value() + direction * owner.get_adjustment().get_step_increment())
                return True
        positioned = []
        points = []
        for control in controls:
            valid, bounds = control.compute_bounds(self)
            if valid and bounds.get_width() > 0 and bounds.get_height() > 0:
                positioned.append(control)
                points.append((bounds.get_x() + bounds.get_width() / 2,
                               bounds.get_y() + bounds.get_height() / 2))
        if owner in positioned:
            target = spatial_target(points, positioned.index(owner), action)
            positioned[target].grab_focus()
        return True

    def show_section(self, section):
        self.sections.set_visible_child_name(section if section in ('global', 'categories', 'scanning', *VIEW_NAMES) else 'global')

    def save_current(self):
        target = self.save_buttons.get(self.sections.get_visible_child_name())
        if target is not None and target.get_sensitive():
            target.emit('clicked')
        return True

    def save_footer(self, key, label, callback, feedback):
        footer = self.footers[key]
        footer.append(feedback)
        actions = Gtk.Box(spacing=16)
        hint = Gtk.Label(label=controller_save_hint(self.shelf.settings), xalign=0, hexpand=True,
                         css_classes=['dim-label'])
        self.save_hints.append(hint)
        actions.append(hint)
        target = self.button(label, callback, 'suggested-action')
        target.add_css_class('settings-control')
        self.save_buttons[key] = target
        actions.append(target)
        footer.append(actions)

    def scanning_page(self):
        shelf = self.shelf
        page = self.page('scanning', tr('Escaneo y scraping'),
            tr('Importa juegos de Steam o Faugus y descarga imágenes e información cuando tú decidas.'))
        left, right = self.columns(page)
        scan_box = self.group(left, tr('Escaneo de Faugus'))
        scan_box.append(Gtk.Label(label=tr('Importa juegos nuevos y actualiza los ya importados. No elimina juegos ni modifica Faugus.'),
                                  wrap=True, xalign=0))
        status = Gtk.Label(wrap=True, xalign=0)
        def scan(source='faugus'):
            if getattr(shelf, 'scrape_running', False):
                status.set_text(tr('Ya hay un scraping en curso.'))
                return
            try:
                added, found = shelf.library.scan_steam() if source == 'steam' else shelf.library.scan_faugus()
                shelf.reload()
                status.set_text(('Steam · ' if source == 'steam' else 'Faugus · ') + tr('Escaneo completado: {found} juegos encontrados, {added} nuevos.').format(found=found, added=added))
            except Exception as error:
                status.set_text(str(error))
        scan_button = self.button(tr('Escanear Faugus'), lambda: scan('faugus'), 'suggested-action')
        scan_box.append(scan_button)
        scan_box.append(Gtk.Label(label=tr('Se asignan a Faugus. Se omiten las entradas que se ejecutan con Steam.'),
                                  wrap=True, xalign=0, css_classes=['dim-label']))
        steam_box = self.group(left, tr('Escaneo de Steam'))
        steam_box.append(Gtk.Label(label=tr('Importa juegos instalados de Steam nativo y Flatpak, incluidas bibliotecas en otros discos. Se asignan a Steam.'),
                                   wrap=True, xalign=0))
        steam_scan_button = self.button(tr('Escanear Steam'), lambda: scan('steam'), 'suggested-action')
        steam_box.append(steam_scan_button)
        removed_box = self.group(left, tr('Juegos quitados'))
        removed_box.append(Gtk.Label(label=tr('Restaura los juegos de Steam y Faugus quitados de Estante, conservando sus personalizaciones.'),
                                     wrap=True, xalign=0))
        def restore():
            count = shelf.library.restore_excluded_imports()
            shelf.reload()
            status.set_text(tr('Juegos restaurados: {count}.').format(count=count))
            restore_button.set_sensitive(False)
        restore_button = self.button(tr('Restaurar juegos quitados'), restore)
        restore_button.set_sensitive(bool(shelf.library.state.get('excluded_imports')))
        removed_box.append(restore_button)
        scrape_box = self.group(right, tr('Scraping'))
        missing = Gtk.CheckButton(label=tr('Completar datos faltantes'), active=True)
        replace = Gtk.CheckButton(label=tr('Reemplazar existentes'))
        replace.set_group(missing)
        scrape_box.append(missing)
        scrape_box.append(replace)
        scrape_box.append(Gtk.Label(label='SteamGridDB', xalign=0, css_classes=['heading']))
        image_choices = {}
        for field, label in (('cover', tr('Carátula 2:3')), ('square_cover', tr('Carátula 1:1')),
                             ('logo', tr('Logo')), ('banner', tr('Fondo principal')),
                             ('banner_secondary', tr('Fondo secundario'))):
            choice = Gtk.CheckButton(label=label, active=True)
            image_choices[field] = choice
            scrape_box.append(choice)
        information = Gtk.CheckButton(label=tr('Información del juego · Wikidata'), active=True)
        scrape_box.append(information)
        scrape_box.append(Gtk.Label(label=tr('Se aplica a toda la biblioteca. Solo se usan coincidencias inequívocas; si no hay resultados, se conserva lo existente.'),
                                    wrap=True, xalign=0, css_classes=['dim-label']))
        progress = Gtk.ProgressBar(show_text=True)
        scrape_box.append(progress)
        def run():
            if getattr(shelf, 'scrape_running', False):
                status.set_text(tr('Ya hay un scraping en curso.'))
                return
            selected_fields = {field for field, choice in image_choices.items() if choice.get_active()}
            if not selected_fields and not information.get_active():
                return
            if selected_fields and not shelf.settings.get('steamgriddb_key'):
                status.set_text(tr('Añade tu clave de SteamGridDB en Preferencias.'))
                return
            games = shelf.library.games()
            if not games:
                status.set_text(tr('No hay juegos para procesar.'))
                return
            from gi.repository import GLib
            artwork = SteamGridDB(shelf.settings.get('steamgriddb_key', ''), shelf.library.root / 'covers') if selected_fields else None
            def waiting(seconds):
                GLib.idle_add(status.set_text, tr('Wikidata ha pedido una pausa. Reintentando en {seconds} s…').format(seconds=round(seconds)))
            metadata = GameMetadata(shelf.library.root / 'metadata', on_wait=waiting) if information.get_active() else None
            overwrite = replace.get_active()
            shelf.scrape_running = True
            progress.set_fraction(0)
            status.set_text(tr('Procesando la biblioteca…'))
            for control in (start, scan_button, steam_scan_button, missing, replace, information, *image_choices.values()):
                control.set_sensitive(False)
            def advance(number, title):
                status.set_text(tr('Procesando la biblioteca…'))
                progress.set_fraction(number / len(games))
                progress.set_text(f'{number}/{len(games)} · {title}')
                return False
            def work():
                results = []
                for number, game in enumerate(games, 1):
                    patch, errors = scrape_game(game, artwork, metadata, overwrite, Gdk.Texture.new_from_filename, fields=selected_fields)
                    results.append((game, patch, errors))
                    GLib.idle_add(advance, number, game['title'])
                return results
            def finished(results):
                try:
                    changed = failures = 0
                    messages = []
                    for original, patch, errors in results:
                        failures += len(errors)
                        messages.extend(original['title'] + ': ' + error for error in errors)
                        current = next((game for game in shelf.library.games() if game['id'] == original['id']), None)
                        if current is not None:
                            updated = apply_scrape_patch(current, original, patch)
                            if updated != current:
                                shelf.library.put(updated)
                                changed += 1
                    shelf.reload()
                    status.set_text(tr('Scraping completado: {changed} juegos actualizados, {errors} errores.').format(changed=changed, errors=failures))
                    if messages:
                        status.set_text(status.get_text() + '\n' + '\n'.join(messages[:5]))
                except Exception as error:
                    status.set_text(str(error))
                finally:
                    enable()
            def enable():
                shelf.scrape_running = False
                for control in (start, scan_button, steam_scan_button, missing, replace, information, *image_choices.values()):
                    control.set_sensitive(True)
            def failed(error):
                status.set_text(str(error))
                enable()
            shelf.background(work, finished, failed)
        start = self.button(tr('Iniciar scraping'), run, 'suggested-action')
        scrape_box.append(start)
        self.footers['scanning'].append(status)

    def categories_page(self):
        shelf = self.shelf
        page = self.page('categories', tr('Categorías'),
                         tr('Gestiona los juegos, el orden y la categoría principal.'))
        creation, categories = self.columns(page)
        box = self.group(creation, tr('Nueva categoría'))
        entry = shelf.field(box, tr('Nueva categoría'))
        primary = self.group(creation, tr('Categoría principal'))
        primary.append(Gtk.Label(label=tr('Se abre al iniciar Estante. Si no eliges otra, se usa Todos.'),
                                 wrap=True, xalign=0, css_classes=['dim-label']))
        primary_choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        primary.append(primary_choices)
        rows = self.group(categories, tr('Categorías'))
        feedback = Gtk.Label(xalign=0, wrap=True)

        def execute(work, rebuild=False):
            try:
                work()
                shelf.reload()
                feedback.set_text(tr('Categorías guardadas.'))
                if rebuild:
                    refresh()
            except Exception as error:
                feedback.set_text(str(error))

        def change(name, previous=None, delete=False):
            def work():
                shelf.library.manage_category(name, previous, delete)
                if previous is not None and previous == shelf.active_category:
                    shelf.active_category = None if delete else name.strip()
                entry.set_text('')
            execute(work, True)

        def assign(name, identity, enabled):
            selected = {game['id'] for game in shelf.library.games() if name in game.get('categories', [])}
            if enabled:
                selected.add(identity)
            else:
                selected.discard(identity)
            execute(lambda: shelf.library.set_category_games(name, selected))

        def refresh():
            for container in (rows, primary_choices):
                while child := container.get_first_child():
                    container.remove(child)
            previous = None
            for name in (None, *shelf.library.categories()):
                choice = Gtk.CheckButton(label=name or tr('Todos'))
                if previous:
                    choice.set_group(previous)
                previous = choice
                choice.set_active(shelf.library.primary_category() == name)
                choice.connect('toggled', lambda control, name=name:
                    execute(lambda: shelf.library.set_primary_category(name)) if control.get_active() else None)
                primary_choices.append(choice)
            names = shelf.library.categories()
            games = shelf.library.games()
            for index, name in enumerate(names):
                card = self.group(rows, name)
                value = Gtk.Entry(text=name, hexpand=True)
                card.append(value)
                actions = Gtk.Box(spacing=8, homogeneous=True)
                actions.append(self.button(tr('Renombrar'), lambda name=name, value=value: change(value.get_text(), name)))
                actions.append(self.button(tr('Eliminar'), lambda name=name: change('', name, True)))
                card.append(actions)
                order = Gtk.Box(spacing=8, homogeneous=True)
                up = self.button(tr('Subir'), lambda name=name: execute(lambda: shelf.library.move_category(name, -1), True))
                down = self.button(tr('Bajar'), lambda name=name: execute(lambda: shelf.library.move_category(name, 1), True))
                up.set_sensitive(index > 0)
                down.set_sensitive(index < len(names) - 1)
                order.append(up)
                order.append(down)
                card.append(order)
                card.append(Gtk.Label(label=tr('Juegos de la categoría'), xalign=0, css_classes=['heading']))
                search = Gtk.SearchEntry(placeholder_text=tr('Buscar juegos…'))
                card.append(search)
                choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                game_choices = []
                for game in games:
                    choice = Gtk.CheckButton(label=game['title'], active=name in game.get('categories', []))
                    choice.connect('toggled', lambda control, name=name, identity=game['id']:
                                   assign(name, identity, control.get_active()))
                    choices.append(choice)
                    game_choices.append((game['title'].casefold(), choice))
                search.connect('search-changed', lambda field, items=game_choices:
                    [choice.set_visible(field.get_text().casefold() in title) for title, choice in items])
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                    min_content_height=140, max_content_height=300, propagate_natural_height=True)
                scroll.set_child(choices)
                card.append(scroll)
            for root in (rows, primary_choices):
                for control in self.controls(root):
                    control.add_css_class('settings-control')

        box.append(self.button(tr('Crear categoría'), lambda: change(entry.get_text()), 'suggested-action'))
        self.footers['categories'].append(feedback)
        self.footers['categories'].append(Gtk.Label(
            label=tr('Los cambios de categorías se guardan automáticamente.'),
            wrap=True, xalign=0, css_classes=['dim-label']))
        refresh()

    def page(self, key, title, description):
        box = self.margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16), 32)
        box.append(Gtk.Label(label=title, xalign=0, css_classes=['title-1']))
        box.append(Gtk.Label(label=description, xalign=0, wrap=True, css_classes=['dim-label']))
        clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=1000)
        clamp.set_child(box)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(clamp)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(scroll)
        footer = self.margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), 16)
        self.footers[key] = footer
        footer_clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=1000)
        footer_clamp.set_child(footer)
        page.append(Gtk.Separator())
        page.append(footer_clamp)
        self.sections.add_named(page, key)
        return box

    def group(self, parent, title):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                       css_classes=['settings-group'])
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=12)
        reveal = Gtk.Revealer(reveal_child=False, transition_duration=180,
                              transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        reveal.set_child(content)
        def toggle():
            expanded = not reveal.get_reveal_child()
            reveal.set_reveal_child(expanded)
            arrow.set_from_icon_name('pan-down-symbolic' if expanded else 'pan-end-symbolic')
            for control in self.controls(content):
                control.add_css_class('settings-control')
        header = self.button(title, toggle, 'flat')
        caption = Gtk.Box(spacing=12)
        caption.append(Gtk.Label(label=title, xalign=0, wrap=True,
                                 hexpand=True, css_classes=['title-3']))
        arrow = Gtk.Image(icon_name='pan-end-symbolic')
        caption.append(arrow)
        header.set_child(caption)
        card.append(header)
        card.append(reveal)
        parent.append(card)
        return content

    @staticmethod
    def columns(box):
        row = Gtk.Box(spacing=32, homogeneous=True, valign=Gtk.Align.START)
        columns = tuple(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                                hexpand=True, valign=Gtk.Align.START) for _ in range(2))
        for column in columns:
            row.append(column)
        box.append(row)
        return columns

    def switch(self, box, title, active):
        row = Gtk.Box(spacing=16)
        row.append(Gtk.Label(label=title, wrap=True, xalign=0, hexpand=True))
        switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        row.append(switch)
        box.append(row)
        return switch

    def scale(self, box, title, value, minimum, maximum, step=1):
        box.append(Gtk.Label(label=title, xalign=0, wrap=True))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum, maximum, step)
        scale.set_value(value)
        scale.set_digits(0)
        scale.set_draw_value(True)
        box.append(scale)
        return scale

    def global_page(self):
        shelf = self.shelf
        box = self.page('global', tr('Ajustes globales'), tr('Biblioteca, fondo e integraciones compartidas entre los aspectos.'))
        general, integrations = self.columns(box)
        box = general
        box.append(Gtk.Label(label='Estante ' + __version__, xalign=0, css_classes=['dim-label']))
        box = self.group(general, tr('Idioma'))
        languages = {}
        previous = None
        preference = shelf.settings.get('language', 'system')
        if preference not in ('system', 'es', 'en'):
            preference = 'system'
        for code, name in (('system', tr('Idioma del sistema')), ('es', 'Español'), ('en', 'English')):
            choice = Gtk.CheckButton(label=tr(name))
            if previous:
                choice.set_group(previous)
            previous = choice
            languages[code] = choice
            box.append(choice)
        languages[preference].set_active(True)
        box.append(Gtk.Label(label=tr('El idioma se aplicará al volver a abrir Estante.'), wrap=True, xalign=0,
                             css_classes=['dim-label']))
        box = self.group(general, tr('Tipo de mando'))
        controllers = {}
        previous = None
        selected_controller = shelf.settings.get('controller_type', 'xbox')
        if selected_controller not in ('sony', 'xbox', 'nintendo'):
            selected_controller = 'xbox'
        for code, name in (('sony', 'Sony'), ('xbox', 'Xbox'), ('nintendo', 'Nintendo')):
            choice = Gtk.CheckButton(label=tr(name))
            if previous:
                choice.set_group(previous)
            previous = choice
            controllers[code] = choice
            box.append(choice)
        controllers[selected_controller].set_active(True)
        self.updates_section(self.group(integrations, tr('Actualizaciones')))
        box = self.group(general, tr('Aspecto de la biblioteca'))
        views = {}
        previous = None
        for mode, name in VIEW_NAMES.items():
            choice = Gtk.CheckButton(label=tr(name))
            if previous:
                choice.set_group(previous)
            previous = choice
            choice.set_active(shelf.view_mode == mode)
            views[mode] = choice
            box.append(choice)
        box = self.group(general, tr('Origen del fondo'))
        per_game = Gtk.CheckButton(label=tr('Personalizado por juego'))
        global_bg = Gtk.CheckButton(label=tr('Fondo global'))
        global_bg.set_group(per_game)
        global_bg.set_active(shelf.settings.get('background_source', 'game') == 'global')
        per_game.set_active(not global_bg.get_active())
        box.append(per_game)
        box.append(global_bg)
        global_path = [shelf.settings.get('global_background', '')]
        image_status = Gtk.Label(wrap=True, xalign=0, visible=False)
        image_status.connect('notify::label',
                             lambda label, *_: label.set_visible(bool(label.get_text())))
        defaults = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                               min_children_per_line=2, max_children_per_line=2,
                               column_spacing=8, row_spacing=8)
        def choose_default(path):
            global_path[0] = 'bundled:' + path.name
            image_status.set_text('')
            global_bg.set_active(True)
            for child in defaults:
                child.get_child().set_has_frame(child.get_child().get_tooltip_text() == path.stem)
        for path in BUNDLED_BACKGROUNDS:
            preview = Gtk.Picture.new_for_filename(str(path))
            preview.set_content_fit(Gtk.ContentFit.COVER)
            preview.set_size_request(120, 68)
            target = self.button(path.stem, lambda path=path: choose_default(path))
            target.set_child(preview)
            target.set_tooltip_text(path.stem)
            defaults.append(target)
        box.append(defaults)
        picker = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        picker.set_size_request(-1, 240)
        image_filter = Gtk.FileFilter()
        image_filter.set_name(tr('Imágenes'))
        image_filter.add_pixbuf_formats()
        picker.add_filter(image_filter)
        picker.set_visible(False)
        box.append(self.button(tr('Desde mi equipo…'), lambda: picker.set_visible(not picker.get_visible())))
        box.append(picker)
        client = SteamGridDB('', shelf.library.root / 'covers')
        def selected(path):
            try:
                Gdk.Texture.new_from_filename(path)
                global_path[0] = path
                image_status.set_text('')
                picker.set_visible(False)
            except Exception as error:
                image_status.set_text(str(error))
        def import_local():
            chosen = picker.get_file()
            if chosen and chosen.get_path():
                shelf.background(lambda: client.import_artwork(chosen.get_path()), selected, image_status.set_text)
            else:
                image_status.set_text(tr('Selecciona una imagen de tu equipo.'))
        box.append(self.button(tr('Usar archivo seleccionado'), import_local))
        address = Gtk.Entry(placeholder_text='https://…')
        box.append(address)
        box.append(self.button(tr('Usar imagen de URL'), lambda: shelf.background(
            lambda: client.download(address.get_text().strip(), custom=True), selected, image_status.set_text)))
        box.append(image_status)
        box = self.group(general, tr('Relleno del fondo'))
        blurred = Gtk.CheckButton(label=tr('Hero desenfocado'))
        dominant = Gtk.CheckButton(label=tr('Color predominante del hero'))
        dominant.set_group(blurred)
        dominant.set_active(shelf.settings.get('background_fill', 'blur') == 'dominant')
        blurred.set_active(not dominant.get_active())
        box.append(blurred)
        box.append(dominant)
        box = self.group(integrations, 'SteamGridDB')
        key = shelf.field(box, tr('Clave API'), shelf.settings.get('steamgriddb_key', ''), True)
        box.append(Gtk.LinkButton(uri='https://www.steamgriddb.com/profile/preferences/api', label=tr('Obtener mi clave API')))
        box = self.group(integrations, tr('IGDB · fondos 16:9'))
        igdb_id = shelf.field(box, tr('Client ID de Twitch'), shelf.settings.get('igdb_client_id', ''))
        igdb_secret = shelf.field(box, tr('Client Secret de Twitch'), shelf.settings.get('igdb_client_secret', ''), True)
        box.append(Gtk.LinkButton(uri='https://dev.twitch.tv/console/apps', label=tr('Crear credenciales de Twitch')))
        box.append(Gtk.LinkButton(uri='https://api-docs.igdb.com/#account-creation', label=tr('Instrucciones de IGDB')))
        feedback = Gtk.Label(xalign=0, wrap=True)
        def save():
            try:
                if global_bg.get_active() and not Path(resolve_background(global_path[0])).is_file():
                    feedback.set_text(tr('Selecciona una imagen para el fondo global.'))
                    return
                selected = next(mode for mode, choice in views.items() if choice.get_active())
                language = next(code for code, choice in languages.items() if choice.get_active())
                language_changed = language != shelf.settings.get('language', 'system')
                shelf.save_settings({**shelf.settings, 'steamgriddb_key': key.get_text().strip(),
                    'igdb_client_id': igdb_id.get_text().strip(), 'igdb_client_secret': igdb_secret.get_text().strip(),
                    'background_fill': 'dominant' if dominant.get_active() else 'blur',
                    'layout': selected, 'language': language,
                    'controller_type': next(code for code, choice in controllers.items() if choice.get_active()),
                    'background_source': 'global' if global_bg.get_active() else 'game',
                    'global_background': global_path[0]})
                changed = shelf.view_mode != selected
                shelf.refresh_controller_hints()
                for hint in self.save_hints:
                    hint.set_text(controller_save_hint(shelf.settings))
                shelf.view_mode = selected
                shelf.configure_view()
                shelf.focused_banner = None
                shelf.reload()
                feedback.set_text(tr('Ajustes globales guardados. Reinicia Estante para aplicar el idioma.') if language_changed
                                  else tr('Ajustes globales guardados.'))
            except Exception as error:
                feedback.set_text(str(error))
        self.save_footer('global', tr('Guardar globales'), save, feedback)

    def updates_section(self, box):
        shelf = self.shelf
        status = Gtk.Label(label=tr('Busca nuevas versiones publicadas en GitHub.'), wrap=True, xalign=0)
        box.append(status)
        release = [None]
        target = appimage_path()
        def failed(error):
            status.set_text(tr('No se pudo completar: ') + str(error))
            check.set_sensitive(True)
            install.set_sensitive(release[0] is not None and not update_available(release[0], target))
        def checked(result):
            check.set_sensitive(True)
            release[0] = result
            if not result:
                status.set_text(tr('Ya tienes la última versión publicada: ') + __version__ + '.')
                install.set_visible(False)
                return
            reason = update_available(result, target)
            status.set_text(tr('Disponible Estante ') + result['version'] + '. ' + (reason or tr('Puedes descargar e instalar la actualización.')))
            install.set_visible(not reason)
            install.set_sensitive(not reason)
        def search():
            check.set_sensitive(False)
            install.set_sensitive(False)
            status.set_text(tr('Buscando actualizaciones…'))
            shelf.background(latest_release, checked, failed)
        def installed(version):
            status.set_text('Estante ' + version + tr(' instalado. Cierra y vuelve a abrir la aplicación para usarlo. Tus datos se conservan.'))
            check.set_sensitive(False)
            install.set_visible(False)
            close.set_visible(True)
        def update():
            check.set_sensitive(False)
            install.set_sensitive(False)
            status.set_text(tr('Descargando y verificando la actualización…'))
            shelf.background(lambda: install_appimage(release[0], target), installed, failed)
        check = self.button(tr('Buscar actualizaciones'), search)
        install = self.button(tr('Descargar e instalar'), update, 'suggested-action')
        install.set_visible(False)
        close = self.button(tr('Cerrar Estante'), shelf.close)
        close.set_visible(False)
        box.append(check)
        box.append(install)
        box.append(close)
        box.append(Gtk.LinkButton(uri=RELEASES_URL, label=tr('Ver versiones en GitHub')))

    def appearance_page(self, mode):
        shelf = self.shelf
        ring = ring_for(shelf.settings, mode)
        box = self.page(mode, tr(VIEW_NAMES[mode]), tr('Estos ajustes se aplican solo a ') + tr(VIEW_NAMES[mode]) + '.')
        backgrounds, cover_options = self.columns(box)
        list_positions = {}
        if mode == 'list':
            position_box = self.group(backgrounds, tr('Posición de la lista'))
            previous = None
            for side, label in (('left', tr('Izquierda')), ('right', tr('Derecha')),
                                ('top', tr('Arriba')), ('bottom', tr('Abajo'))):
                choice = Gtk.CheckButton(label=label)
                if previous:
                    choice.set_group(previous)
                previous = choice
                choice.set_active(list_side_for(shelf.settings) == side)
                list_positions[side] = choice
                position_box.append(choice)
        box = self.group(backgrounds, tr('Posición del hero'))
        hero_top = Gtk.CheckButton(label=tr('Parte superior'))
        hero_lower = Gtk.CheckButton(label=tr('Mitad inferior'))
        hero_lower.set_group(hero_top)
        hero_lower.set_active(hero_position_for(shelf.settings, mode) == 'lower')
        hero_full = Gtk.CheckButton(label=tr('Pantalla completa'))
        hero_full.set_group(hero_top)
        hero_full.set_active(hero_position_for(shelf.settings, mode) == 'full')
        hero_top.set_active(hero_position_for(shelf.settings, mode) == 'top')
        box.append(hero_top)
        box.append(hero_lower)
        box.append(hero_full)
        box = self.group(backgrounds, tr('División de los fondos'))
        split_choices = {}
        previous = None
        for key, label in (('single', tr('Un solo fondo')), ('horizontal', tr('Horizontal (arriba y abajo)')),
                           ('vertical', tr('Vertical (izquierda y derecha)')), ('diagonal', tr('Diagonal'))):
            choice = Gtk.CheckButton(label=label)
            if previous:
                choice.set_group(previous)
            previous = choice
            split_choices[key] = choice
            box.append(choice)
        split_choices[background_split_for(shelf.settings, mode)].set_active(True)
        box.append(Gtk.Label(label=tr('El segundo fondo se elige en Editar. Si falta, se muestra solo el primero.'),
                             wrap=True, xalign=0, css_classes=['dim-label']))
        box = self.group(backgrounds, tr('Logos') if mode == 'list' else tr('Carátulas'))
        carousel_zoom = carousel_bottom = None
        grid_zoom = list_zoom = list_focus_zoom = None
        if mode == 'list':
            list_focus_zoom = self.scale(box, tr('Tamaño del logo con foco (%)'), shelf.settings.get('list_focus_zoom', 150), 100, 250, 5)
            list_zoom = self.scale(box, tr('Tamaño de los logos (%)'), shelf.settings.get('list_zoom', 100), 50, 200, 5)
        if mode == 'grid':
            grid_zoom = self.scale(box, tr('Zoom de las carátulas (%)'), shelf.grid_zoom() * 100, 50, 200, 5)
        if mode == 'carousel':
            carousel_bottom = self.switch(box, tr('Mostrar los juegos en la parte inferior'),
                                          shelf.settings.get('carousel_position', 'top') == 'bottom')
            carousel_zoom = self.scale(box, tr('Zoom del juego con foco (%)'), shelf.carousel_zoom() * 100, 100, 175, 5)
        zoom = motion = None
        if mode == 'ps5':
            zoom = self.scale(box, tr('Tamaño del juego con foco (px)'), shelf.ps5_focus_size(), 104, 320, 4)
            motion = self.switch(box, tr('Animación suave de la carátula'), shelf.settings.get('ps5_motion', True))
        box = self.group(cover_options, tr('Carátulas'))
        square = Gtk.CheckButton(label=tr('Cuadrada (1:1)'))
        portrait = Gtk.CheckButton(label=tr('Vertical (2:3)'))
        portrait.set_group(square)
        square.set_active(cover_format_for(shelf.settings, mode) == 'square')
        portrait.set_active(not square.get_active())
        box.append(square)
        box.append(portrait)
        list_cover_zoom = None
        if mode == 'list':
            list_cover_zoom = self.scale(box, tr('Tamaño de la carátula (%)'),
                                         shelf.settings.get('list_cover_zoom', 100), 50, 175, 5)
        corners = self.scale(box, tr('Redondeado de las esquinas (px; 0 = rectas)'), cover_radius_for(shelf.settings, mode), 0, 40)
        box = self.group(cover_options, tr('Anillo de selección'))
        enabled = self.switch(box, tr('Mostrar anillo de selección'), ring['focus_ring_enabled'])
        color = shelf.field(box, tr('Color del anillo'), ring['focus_ring_color'])
        samples = Gtk.Box(spacing=8)
        for name, value in ((tr('Blanco'), '#ffffff'), (tr('Ámbar'), '#ffb077'), (tr('Azul'), '#75baff')):
            samples.append(self.button(name, lambda value=value: color.set_text(value)))
        box.append(samples)
        box.append(Gtk.Label(label=tr('Grosor del anillo (px)'), xalign=0))
        thickness = Gtk.SpinButton.new_with_range(1, 8, 1)
        thickness.set_value(ring['focus_ring_width'])
        box.append(thickness)
        box.append(Gtk.Label(label=tr('Redondeado del anillo (px)'), xalign=0))
        radius = Gtk.SpinButton.new_with_range(0, 40, 1)
        radius.set_value(ring['focus_ring_radius'])
        box.append(radius)
        feedback = Gtk.Label(wrap=True, xalign=0)
        def save():
            parsed = Gdk.RGBA()
            if not parsed.parse(color.get_text().strip()):
                feedback.set_text(tr('Escribe un color válido, por ejemplo #ffffff.'))
                return
            try:
                settings = with_ring(shelf.settings, mode, {'focus_ring_enabled': enabled.get_active(),
                    'focus_ring_color': parsed.to_string(), 'focus_ring_width': thickness.get_value_as_int(),
                    'focus_ring_radius': radius.get_value_as_int()})
                settings['hero_positions'] = {view: hero_position_for(shelf.settings, view) for view in VIEW_NAMES}
                settings['hero_positions'][mode] = 'full' if hero_full.get_active() else ('lower' if hero_lower.get_active() else 'top')
                settings['background_splits'] = {**shelf.settings.get('background_splits', {}),
                    mode: next(key for key, choice in split_choices.items() if choice.get_active())}
                if list_zoom is not None:
                    settings['list_side'] = next(side for side, choice in list_positions.items() if choice.get_active())
                    settings['list_zoom'] = round(list_zoom.get_value())
                    settings['list_focus_zoom'] = round(list_focus_zoom.get_value())
                    settings['list_cover_zoom'] = round(list_cover_zoom.get_value())
                settings['cover_radii'] = {**shelf.settings.get('cover_radii', {}), mode: round(corners.get_value())}
                settings['cover_formats'] = {**shelf.settings.get('cover_formats', {}),
                                             mode: 'square' if square.get_active() else 'portrait'}
                if grid_zoom is not None:
                    settings['grid_zoom'] = round(grid_zoom.get_value())
                if carousel_zoom is not None:
                    settings['carousel_zoom'] = round(carousel_zoom.get_value())
                    settings['carousel_position'] = 'bottom' if carousel_bottom.get_active() else 'top'
                if zoom is not None:
                    settings.update(ps5_focus_size=round(zoom.get_value()), ps5_zoom=round(zoom.get_value()/104*100),
                                    ps5_motion=motion.get_active())
                shelf.save_settings(settings)
                shelf.configure_view()
                if shelf.view_mode == mode:
                    shelf.reload()
                if shelf.view_mode != 'grid' and shelf.selected_tile():
                    from gi.repository import GLib
                    GLib.timeout_add(50, shelf.center_tile, shelf.selected_tile())
                feedback.set_text(tr('Aspecto ') + tr(VIEW_NAMES[mode]) + tr(' guardado.'))
            except Exception as error:
                feedback.set_text(str(error))
        self.save_footer(mode, tr('Guardar aspecto'), save, feedback)
