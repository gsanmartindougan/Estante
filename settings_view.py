"""Dedicated in-window settings, split into global and per-view pages."""
from pathlib import Path
from library import SteamGridDB
from controls import controller_save_hint
from metadata import GameMetadata, CategoryIcons, IconifyIcons
from scraping import scrape_game, apply_scrape_results
from image_cache import images, validate_image
from i18n import tr
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gtk, GLib, Gio, GObject
from appearance import background_effects_for, minimal_for, list_side_for, VIEW_NAMES, ring_for, with_ring, cover_radius_for, hero_position_for, cover_format_for
from version import __version__
from screensaver_config import time_choice
from game_session import playing_behavior
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


def navigation_bounds(control, root):
    # A trailing switch belongs to its labelled row, not to a separate column.
    target = control
    if isinstance(control, Gtk.Switch):
        parent = control.get_parent()
        if isinstance(parent, Gtk.Box):
            target = parent
    return target.compute_bounds(root)


def descendant(widget, kind):
    child = widget.get_first_child()
    while child:
        if isinstance(child, kind):
            return child
        found = descendant(child, kind)
        if found is not None:
            return found
        child = child.get_next_sibling()
    return None


def dropdown_input(owner, action):
    """Use the native popup selection; do not commit values on initial confirm."""
    popup = descendant(owner, Gtk.Popover)
    if popup is not None and popup.get_visible():
        if action in ('back', 'menu'):
            popup.popdown()
            owner.grab_focus()
            return True
        listing = descendant(popup, Gtk.ListView)
        if listing is None:
            return True
        model = listing.get_model()
        count = model.get_n_items()
        if not count:
            return True
        selected = model.get_selection().get_nth(0)
        if selected >= count:
            selected = min(owner.get_selected(), count - 1)
        if action in ('up', 'down'):
            selected = max(0, min(count - 1, selected + (1 if action == 'down' else -1)))
            model.select_item(selected, True)
            if hasattr(listing, 'scroll_to'):
                listing.scroll_to(selected, Gtk.ListScrollFlags.FOCUS, None)
        elif action == 'confirm':
            listing.emit('activate', selected)
        return True
    if action == 'confirm':
        owner.emit('activate')
        return True
    return False


class SettingsView(Gtk.Box):
    def __init__(self, shelf, button, margins, section='global'):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=['background', 'glass-settings'])
        self.shelf, self.button, self.margins = shelf, button, margins
        self.footers = {}
        self.save_buttons = {}
        self.save_hints = []
        header = Gtk.Box(spacing=14, css_classes=['glass-settings-header'])
        header.append(button(tr('← Biblioteca'), shelf.leave_preferences))
        header.append(Gtk.Label(label=tr('Ajustes'), xalign=0, hexpand=True, css_classes=['title-2']))
        window_controls = Gtk.WindowControls(side=Gtk.PackType.END)
        shelf.bind_property('fullscreened', window_controls, 'visible',
                            GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.INVERT_BOOLEAN)
        header.append(window_controls)
        handle = Gtk.WindowHandle()
        handle.set_child(margins(header, 16))
        self.append(handle)
        self.append(Gtk.Separator())
        body = Gtk.Box(vexpand=True)
        self.append(body)
        nav = self.navigation = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, width_request=160), 16)
        nav.add_css_class('glass-navigation')
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
        self.show_section(section)
        for control in self.controls(self):
            control.add_css_class('settings-control')

    @staticmethod
    def controls(root):
        types = (Gtk.Button, Gtk.CheckButton, Gtk.Switch, Gtk.Range, Gtk.SpinButton,
                 Gtk.Entry, Gtk.PasswordEntry, Gtk.DropDown)
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
        popup_owner = next((control for control in controls if isinstance(control, Gtk.DropDown)
                            and (popup := descendant(control, Gtk.Popover)) is not None and popup.get_visible()), None)
        if popup_owner is not None:
            return dropdown_input(popup_owner, action)
        owner = next((control for control in controls
                      if focus == control or (focus and focus.is_ancestor(control))), None)
        if owner is None:
            navigation[0].grab_focus()
            return True
        if isinstance(owner, Gtk.DropDown) and dropdown_input(owner, action):
            return True
        if action == 'confirm':
            if isinstance(owner, Gtk.Switch):
                owner.set_active(not owner.get_active())
            elif isinstance(owner, Gtk.CheckButton):
                owner.emit('activate')
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
            valid, bounds = navigation_bounds(control, self)
            if valid and bounds.get_width() > 0 and bounds.get_height() > 0:
                positioned.append(control)
                points.append((bounds.get_x() + bounds.get_width() / 2,
                               bounds.get_y() + bounds.get_height() / 2))
        if owner in positioned:
            target = spatial_target(points, positioned.index(owner), action)
            positioned[target].grab_focus()
        return True

    def dismiss_popup(self):
        for control in self.controls(self.sections.get_visible_child()):
            if isinstance(control, Gtk.DropDown):
                popup = descendant(control, Gtk.Popover)
                if popup is not None and popup.get_visible():
                    popup.popdown()
                    control.grab_focus()
                    return True
        return False

    def show_section(self, section):
        section = section if section in ('global', 'categories', 'scanning', *VIEW_NAMES) else 'global'
        if self.sections.get_child_by_name(section) is None:
            if section == 'global':
                self.global_page()
            elif section == 'categories':
                self.categories_page()
            elif section == 'scanning':
                self.scanning_page()
            else:
                self.appearance_page(section)
            for control in self.controls(self.sections.get_child_by_name(section)):
                control.add_css_class('settings-control')
        self.sections.set_visible_child_name(section)

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
                    patch, errors = scrape_game(game, artwork, metadata, overwrite, validate_image, fields=selected_fields)
                    results.append((game, patch, errors))
                    GLib.idle_add(advance, number, game['title'])
                return results
            def finished(results):
                try:
                    changed, failures, messages = apply_scrape_results(shelf.library, results)
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

    def category_icon_search(self, card, name, save):
        shelf = self.shelf
        clients = (CategoryIcons(shelf.library.root / 'category-icons'),
                   IconifyIcons(shelf.library.root / 'category-icons'))
        search_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
        card.append(search_box)
        sources = Gtk.Box(spacing=12)
        bootstrap = Gtk.CheckButton(label='Bootstrap Icons', active=True)
        iconify = Gtk.CheckButton(label='Iconify', group=bootstrap)
        sources.append(bootstrap)
        sources.append(iconify)
        search_box.append(sources)
        query = Gtk.Entry(text=name or '', hexpand=True)
        search_box.append(query)
        search_box.append(Gtk.Label(label=tr('Busca en inglés: controller, heart, steam…'),
                                    wrap=True, xalign=0, css_classes=['dim-label']))
        status = Gtk.Label(wrap=True, xalign=0)
        results = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                              min_children_per_line=1, max_children_per_line=3,
                              column_spacing=8, row_spacing=8)
        generation = [0]
        previews = []
        state = {'rows': [], 'page': 0, 'client': clients[0], 'more': False}

        def clear():
            for picture in previews:
                picture.set_paintable(None)
            previews.clear()
            while child := results.get_first_child():
                results.remove(child)

        def render():
            generation[0] += 1
            token = generation[0]
            clear()
            rows = state['rows']
            pages = max(1, (len(rows) + 11) // 12)
            state['page'] = max(0, min(state['page'], pages - 1))
            previous.set_sensitive(state['page'] > 0)
            following.set_sensitive(state['page'] + 1 < pages)
            more.set_visible(state['more'])
            status.set_text(tr('{count} iconos · Página {page} de {pages}').format(
                count=len(rows), page=state['page'] + 1, pages=pages) if rows else
                tr('Sin resultados. Prueba con otro nombre.'))
            client = state['client']
            def active():
                return (generation[0] == token and shelf.preferences_view is self
                        and search_box.get_visible())
            failed_load = [False]
            def failed(error):
                if active():
                    failed_load[0] = True
                    status.set_text(str(error))
            def waiting(seconds):
                if active():
                    status.set_text(tr('Iconify solicita una pausa. Reintentando en {seconds} s…').format(seconds=round(seconds)))
            if isinstance(client, IconifyIcons):
                client.on_wait = lambda seconds: GLib.idle_add(waiting, seconds)
            page_rows = rows[state['page'] * 12:(state['page'] + 1) * 12]
            jobs = []
            for row in page_rows:
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                picture = Gtk.Picture(width_request=64, height_request=64,
                                      can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
                previews.append(picture)
                loaded = [None]
                def choose(loaded=loaded, row=row):
                    if loaded[0]:
                        save(loaded[0], row)
                        generation[0] += 1
                        search_box.set_visible(False)
                        clear()
                target = self.button(row['name'], choose)
                target.set_sensitive(False)
                content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                content.append(picture)
                content.append(Gtk.Label(label=row['name'], wrap=True, max_width_chars=16))
                target.set_child(content)
                box.append(target)
                credit = ' · '.join(value for value in (row['author'], row['license']) if value)
                source = Gtk.LinkButton(uri=row['source'], label=tr('Fuente y licencia'))
                source.set_tooltip_text(credit)
                box.append(source)
                results.append(box)
                def load(row=row):
                    if token != generation[0] or shelf.preferences_view is not self:
                        return None
                    path = client.download(row['url'])
                    if token != generation[0] or shelf.preferences_view is not self:
                        return None
                    return path, images.load(path, 96, 96, kind='category')
                def ready(result, picture=picture, target=target, loaded=loaded):
                    if result is not None and active():
                        loaded[0], texture = result
                        picture.set_paintable(texture)
                        target.set_sensitive(True)
                jobs.append((load, ready))
            def load_page():
                cancelled = lambda: token != generation[0] or shelf.preferences_view is not self
                if cancelled():
                    return
                if isinstance(client, IconifyIcons):
                    client.prepare(page_rows, cancelled=cancelled)
                for load, ready in jobs:
                    if cancelled():
                        return
                    try:
                        result = load()
                    except Exception as error:
                        GLib.idle_add(failed, str(error))
                    else:
                        GLib.idle_add(ready, result)
            def finished(_):
                if active() and not failed_load[0]:
                    status.set_text(tr('{count} iconos · Página {page} de {pages}').format(
                        count=len(rows), page=state['page'] + 1, pages=pages))
            shelf.background(load_page, finished, failed)

        def run(expand=False):
            generation[0] += 1
            token = generation[0]
            clear()
            more.set_visible(False)
            previous.set_sensitive(False)
            following.set_sensitive(False)
            status.set_text(tr('Buscando iconos…'))
            client = clients[1 if iconify.get_active() else 0]
            text = query.get_text()
            if client is clients[1] and not text.strip():
                text = 'game'
                query.set_text(text)
            def active():
                return (generation[0] == token and shelf.preferences_view is self
                        and search_box.get_visible())
            def failed(error):
                if active():
                    status.set_text(str(error))
            def show(rows):
                if active():
                    state.update(rows=rows, page=state['page'] if expand else 0, client=client,
                                 more=client is clients[1] and not expand and len(rows) == 64)
                    render()
            def waiting(seconds):
                if active():
                    status.set_text(tr('Iconify solicita una pausa. Reintentando en {seconds} s…').format(seconds=round(seconds)))
            if isinstance(client, IconifyIcons):
                client.on_wait = lambda seconds: GLib.idle_add(waiting, seconds)
            shelf.background(lambda: client.search(text, full=expand) if client is clients[1]
                             else client.search(text), show, failed)

        query.connect('activate', lambda *_: run())
        search_box.append(self.button(tr('Buscar'), run))
        def browse():
            query.set_text('game' if iconify.get_active() else '')
            run()
        search_box.append(self.button(tr('Explorar iconos'), browse))
        search_box.append(status)
        search_box.append(results)
        pagination = Gtk.Box(spacing=8, homogeneous=True)
        def move(step):
            state['page'] += step
            render()
        previous = self.button(tr('Anterior'), lambda: move(-1))
        following = self.button(tr('Siguiente'), lambda: move(1))
        pagination.append(previous)
        pagination.append(following)
        search_box.append(pagination)
        more = self.button(tr('Más resultados'), lambda: run(True))
        more.set_visible(False)
        search_box.append(more)
        def source_changed(control):
            if control.get_active() and search_box.get_visible():
                run()
        bootstrap.connect('toggled', source_changed)
        iconify.connect('toggled', source_changed)
        def toggle():
            search_box.set_visible(not search_box.get_visible())
            if search_box.get_visible():
                run()
            else:
                generation[0] += 1
                clear()
        return self.button(tr('Buscar icono…'), toggle)

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

        def icon_controls(card, name):
            preview = Gtk.Picture(width_request=32, height_request=32,
                                  content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
            path = shelf.library.category_icon(name)
            if path:
                try:
                    images.request_picture(preview, path, 64, 64, kind='category')
                except (GLib.Error, OSError, ValueError):
                    pass
            card.append(preview)
            source = Gtk.LinkButton(uri='https://icons.getbootstrap.com/', label=tr('Fuente y licencia'))
            credit_label = Gtk.Label(wrap=True, xalign=0)
            card.append(source)
            card.append(credit_label)
            def update_credit():
                credit = shelf.library.state.get('category_icon_sources', {}).get(name or '', {})
                source.set_visible(bool(credit.get('source')))
                if credit.get('source'):
                    source.set_uri(credit['source'])
                text = ' · '.join(value for value in (credit.get('author'), credit.get('license')) if value)
                credit_label.set_text(text)
                credit_label.set_visible(bool(text))
            update_credit()
            def apply_icon(path, credit=None):
                execute(lambda: shelf.library.set_category_icon(name, path, credit))
                stored = shelf.library.category_icon(name)
                if stored:
                    images.request_picture(preview, stored, 64, 64, kind='category')
                update_credit()
            def select_icon():
                dialog = Gtk.FileDialog(title=tr('Elegir icono de categoría'))
                image_filter = Gtk.FileFilter(name=tr('Imágenes'))
                image_filter.add_pixbuf_formats()
                filters = Gio.ListStore.new(Gtk.FileFilter)
                filters.append(image_filter)
                dialog.set_filters(filters)
                dialog.set_default_filter(image_filter)
                def selected(dialog, result):
                    try:
                        selected_file = dialog.open_finish(result)
                    except GLib.Error:
                        return
                    path = selected_file.get_path()
                    if path:
                        def validate():
                            images.load(path, 64, 64, kind='category')
                            return path
                        shelf.background(validate, apply_icon, feedback.set_text)
                dialog.open(shelf, None, selected)
            card.append(self.category_icon_search(card, name, apply_icon))
            actions = Gtk.Box(spacing=8, homogeneous=True)
            actions.append(self.button(tr('Elegir icono…'), select_icon))
            def remove_icon():
                execute(lambda: shelf.library.set_category_icon(name))
                preview.set_paintable(None)
                update_credit()
            actions.append(self.button(tr('Usar texto'), remove_icon))
            card.append(actions)

        icon_controls(self.group(creation, tr('Icono de Todos')), None)

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
            for index, name in enumerate(names):
                card = self.group(rows, name)
                value = Gtk.Entry(text=name, hexpand=True)
                card.append(value)
                actions = Gtk.Box(spacing=8, homogeneous=True)
                actions.append(self.button(tr('Renombrar'), lambda name=name, value=value: change(value.get_text(), name)))
                actions.append(self.button(tr('Eliminar'), lambda name=name: change('', name, True)))
                card.append(actions)
                icon_controls(card, name)
                order = Gtk.Box(spacing=8, homogeneous=True)
                up = self.button(tr('Subir'), lambda name=name: execute(lambda: shelf.library.move_category(name, -1), True))
                down = self.button(tr('Bajar'), lambda name=name: execute(lambda: shelf.library.move_category(name, 1), True))
                up.set_sensitive(index > 0)
                down.set_sensitive(index < len(names) - 1)
                order.append(up)
                order.append(down)
                card.append(order)
                self.group(card, tr('Juegos de la categoría'),
                           on_open=lambda content, name=name: self.category_game_choices(content, name, assign))
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

    @staticmethod
    def load_group_once(content, build):
        loaded = False
        def revealed(reveal, *_):
            nonlocal loaded
            if reveal.get_reveal_child() and not loaded:
                build(content)
                loaded = True
        return revealed

    def category_game_choices(self, card, name, assign):
        search = Gtk.SearchEntry(placeholder_text=tr('Buscar juegos…'))
        card.append(search)
        choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        game_choices = []
        for game in self.shelf.library.games():
            choice = Gtk.CheckButton(label=game['title'], active=name in game.get('categories', []))
            choice.connect('toggled', lambda control, identity=game['id']:
                           assign(name, identity, control.get_active()))
            choices.append(choice)
            game_choices.append((game['title'].casefold(), choice))
        search.connect('search-changed', lambda field:
            [choice.set_visible(field.get_text().casefold() in title) for title, choice in game_choices])
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
            min_content_height=140, max_content_height=300, propagate_natural_height=True)
        scroll.set_child(choices)
        card.append(scroll)
        for control in self.controls(card):
            control.add_css_class('settings-control')

    def group(self, parent, title, on_open=None):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                       css_classes=['settings-group'])
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=12)
        reveal = Gtk.Revealer(reveal_child=False, transition_duration=180,
                              transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        reveal.set_child(content)
        if on_open is not None:
            reveal.connect('notify::reveal-child', self.load_group_once(content, on_open))
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
        box.append(Gtk.Label(label='Estante ' + __version__, xalign=0, css_classes=['dim-label']))
        general, appearance = self.columns(box)
        general.append(Gtk.Label(label=tr('Preferencias'), xalign=0, css_classes=['title-3']))
        appearance.append(Gtk.Label(label=tr('Biblioteca y servicios'), xalign=0, css_classes=['title-3']))
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
        startup = self.group(general, tr('Inicio'))
        fullscreen = self.switch(startup, tr('Abrir a pantalla completa'), shelf.settings.get('start_fullscreen', False))
        auto_updates = self.switch(startup, tr('Comprobar actualizaciones al iniciar'), shelf.settings.get('check_updates_on_start', False))
        activity = self.group(appearance, tr('Actividad'))
        session_history = self.switch(activity, tr('Mostrar historial de sesiones'), shelf.settings.get('show_session_history', True))
        playing = self.group(general, tr('Mientras juegas'))
        playing.append(Gtk.Label(label=tr('Al abrir el juego'), xalign=0))
        playing_modes = ('none', 'hide', 'screensaver', 'tray')
        playing_choice = Gtk.DropDown.new_from_strings([
            tr('Mantener Estante abierto'), tr('Cerrar Estante y reabrirlo al salir'),
            tr('Mostrar salvapantallas hasta cerrar el juego'), tr('Minimizar a la bandeja del sistema')])
        playing_choice.set_selected(playing_modes.index(playing_behavior(shelf.settings)))
        playing.append(playing_choice)
        playing.append(Gtk.Label(label=tr('Se aplica cuando el juego ya está abierto. Al terminar, Estante recupera su estado. Pulsa el icono de la bandeja para mostrarlo durante la partida.'), wrap=True, xalign=0,
                                 css_classes=['dim-label']))
        saver = self.group(general, tr('Salvapantallas'))
        saver_enabled = self.switch(saver, tr('Activar tras un periodo de inactividad'), shelf.settings.get('screensaver_enabled', False))
        def time_selector(title, kind):
            saver.append(Gtk.Label(label=title, xalign=0))
            row = Gtk.Box(spacing=12)
            value, unit = time_choice(shelf.settings, kind)
            number = Gtk.SpinButton.new_with_range(1, 60, 1)
            number.set_numeric(True)
            number.set_value(value)
            units = Gtk.DropDown.new_from_strings([tr('Segundos'), tr('Minutos')])
            units.set_selected(1 if unit == 'minutes' else 0)
            units.set_hexpand(True)
            row.append(number)
            row.append(units)
            saver.append(row)
            return number, units
        saver_idle, saver_idle_unit = time_selector(tr('Activar después de'), 'idle')
        saver_interval, saver_interval_unit = time_selector(tr('Cambiar fondo cada'), 'slide')
        saver.append(Gtk.Label(label=tr('Origen de las imágenes'), xalign=0))
        saver_source = Gtk.DropDown.new_from_strings([tr('Fondos de los juegos'), tr('Fondo de la aplicación')])
        saver_source.set_selected(1 if shelf.settings.get('screensaver_source') == 'application' else 0)
        saver.append(saver_source)
        application_bg = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        application_bg.set_visible(saver_source.get_selected() == 1)
        saver.append(application_bg)
        application_bg.append(Gtk.Label(label=tr('Seleccionar fondo'), xalign=0))
        saver_background = Gtk.DropDown.new_from_strings([
            tr('Fondo {number}').format(number=i + 1) for i in range(len(BUNDLED_BACKGROUNDS))])
        current_bg = shelf.settings.get('screensaver_background', 'bundled:6.png')
        saver_background.set_selected(next((i for i, path in enumerate(BUNDLED_BACKGROUNDS)
                                            if current_bg == 'bundled:' + path.name), 0))
        application_bg.append(saver_background)
        saver_preview = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN, height_request=140)
        application_bg.append(saver_preview)
        def show_saver_preview(*_):
            if not saver_preview.get_mapped() or not BUNDLED_BACKGROUNDS:
                return
            previous = getattr(saver_preview, 'image_ticket', None)
            if previous:
                previous.cancelled = True
            path = BUNDLED_BACKGROUNDS[saver_background.get_selected()]
            def loaded(texture, error):
                if error is None:
                    saver_preview.set_paintable(texture)
            saver_preview.image_ticket = images.request(path, 480, 270, loaded, kind='settings')
        saver_preview.connect('map', show_saver_preview)
        saver_background.connect('notify::selected', show_saver_preview)
        saver_source.connect('notify::selected', lambda *_: application_bg.set_visible(saver_source.get_selected() == 1))
        saver_dim = self.scale(saver, tr('Oscurecimiento del salvapantallas (%)'), shelf.settings.get('screensaver_dim', 35), 0, 85, 5)
        saver.append(Gtk.Label(label=tr('Libera la biblioteca de la memoria y recupera tu selección al volver. No se activa durante una partida.'), wrap=True, xalign=0))
        def saver_settings():
            return {
                'screensaver_enabled': saver_enabled.get_active(),
                'screensaver_idle_value': saver_idle.get_value_as_int(),
                'screensaver_idle_unit': 'minutes' if saver_idle_unit.get_selected() else 'seconds',
                'screensaver_slide_value': saver_interval.get_value_as_int(),
                'screensaver_slide_unit': 'minutes' if saver_interval_unit.get_selected() else 'seconds',
                'screensaver_source': 'application' if saver_source.get_selected() else 'games',
                'screensaver_background': ('bundled:' + BUNDLED_BACKGROUNDS[saver_background.get_selected()].name
                                            if BUNDLED_BACKGROUNDS else ''),
                'screensaver_dim': int(saver_dim.get_value()),
            }
        def preview_screensaver():
            config = {**shelf.settings, **saver_settings()}
            GLib.idle_add(lambda: shelf.screensaver.preview(config))
        saver.append(self.button(tr('Probar salvapantallas'), preview_screensaver))
        box = self.group(appearance, tr('Aspecto de la biblioteca'))
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
        box = self.group(appearance, tr('Origen del fondo'))
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
        previews = []
        for path in BUNDLED_BACKGROUNDS:
            preview = Gtk.Picture(can_shrink=True)
            previews.append((preview, path))
            preview.set_content_fit(Gtk.ContentFit.COVER)
            preview.set_size_request(120, 68)
            target = self.button(path.stem, lambda path=path: choose_default(path))
            target.set_child(preview)
            target.set_tooltip_text(path.stem)
            defaults.append(target)
        box.append(defaults)
        def load_previews(_):
            for preview, path in previews:
                images.request_picture(preview, path, 480, 270)
        box.get_parent().connect('notify::reveal-child', self.load_group_once(box, load_previews))
        picker = None
        picker_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        def toggle_picker():
            nonlocal picker
            if picker is None:
                picker = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
                picker.set_size_request(-1, 240)
                image_filter = Gtk.FileFilter()
                image_filter.set_name(tr('Imágenes'))
                image_filter.add_pixbuf_formats()
                picker.add_filter(image_filter)
                picker_host.append(picker)
                for control in self.controls(picker_host):
                    control.add_css_class('settings-control')
            else:
                picker.set_visible(not picker.get_visible())
        box.append(self.button(tr('Desde mi equipo…'), toggle_picker))
        box.append(picker_host)
        client = SteamGridDB('', shelf.library.root / 'covers')
        def selected(path):
            try:
                global_path[0] = path
                image_status.set_text('')
                if picker is not None:
                    picker.set_visible(False)
            except Exception as error:
                image_status.set_text(str(error))
        def import_local():
            chosen = picker.get_file() if picker is not None else None
            if chosen and chosen.get_path():
                shelf.background(lambda: validate_image(client.import_artwork(chosen.get_path())), selected, image_status.set_text)
            else:
                image_status.set_text(tr('Selecciona una imagen de tu equipo.'))
        box.append(self.button(tr('Usar archivo seleccionado'), import_local))
        address = Gtk.Entry(placeholder_text='https://…')
        box.append(address)
        def import_url():
            url = address.get_text().strip()
            shelf.background(lambda: validate_image(client.download(url, custom=True)), selected, image_status.set_text)
        box.append(self.button(tr('Usar imagen de URL'), import_url))
        box.append(image_status)
        box = self.group(appearance, tr('Relleno del fondo'))
        blurred = Gtk.CheckButton(label=tr('Hero desenfocado'))
        dominant = Gtk.CheckButton(label=tr('Color predominante del hero'))
        dominant.set_group(blurred)
        dominant.set_active(shelf.settings.get('background_fill', 'blur') == 'dominant')
        blurred.set_active(not dominant.get_active())
        box.append(blurred)
        box.append(dominant)
        integrations = self.group(appearance, tr('Servicios e integraciones'))
        self.updates_section(self.group(integrations, tr('Actualizaciones')))
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
                shelf.save_settings({**shelf.settings, 'start_fullscreen': fullscreen.get_active(),
                                     'check_updates_on_start': auto_updates.get_active(),
                                     'show_session_history': session_history.get_active(),
                                     'playing_behavior': playing_modes[playing_choice.get_selected()],
                                     'hide_while_playing': playing_modes[playing_choice.get_selected()] == 'hide',
                                     **saver_settings(),
                                     'steamgriddb_key': key.get_text().strip(),
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
        details = self.group(cover_options, tr('Información del juego'))
        presentation = self.group(cover_options, tr('Presentación'))
        minimal = self.switch(presentation, tr('Presentación mínima'), minimal_for(shelf.settings, mode))
        presentation.append(Gtk.Label(label=tr('Destaca el fondo a pantalla completa y oculta sinopsis, actividad y ficha. Conserva los controles y evita duplicar la carátula seleccionada.'), wrap=True, xalign=0))
        technical = self.switch(details, tr('Mostrar datos del launcher'),
                                shelf.settings.get('show_launcher_details', {}).get(mode, True))
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
        effects = background_effects_for(shelf.settings, mode)
        effects_box = self.group(backgrounds, tr('Imagen de fondo'))
        background_dim = self.scale(effects_box, tr('Oscurecimiento del fondo (%)'), effects['dim'], 0, 100, 1)
        background_blur = self.scale(effects_box, tr('Desenfoque del fondo (px)'), effects['blur'], 0, 40, 1)
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
        cover_controls = self.group(cover_options, tr('Carátulas')) if mode != 'list' else None
        box = self.group(backgrounds, tr('Logos')) if mode == 'list' else cover_controls
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
        box = cover_controls if cover_controls is not None else self.group(cover_options, tr('Carátulas'))
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
                settings['show_launcher_details'] = {**shelf.settings.get('show_launcher_details', {}), mode: technical.get_active()}
                settings['background_dim'] = {**shelf.settings.get('background_dim', {}), mode: round(background_dim.get_value())}
                settings['background_blur'] = {**shelf.settings.get('background_blur', {}), mode: round(background_blur.get_value())}
                settings['hero_positions'] = {view: hero_position_for(shelf.settings, view) for view in VIEW_NAMES}
                settings['hero_positions'][mode] = 'full' if hero_full.get_active() else ('lower' if hero_lower.get_active() else 'top')
                settings['background_splits'] = {**shelf.settings.get('background_splits', {}),
                    mode: next(key for key, choice in split_choices.items() if choice.get_active())}
                if minimal is not None:
                    settings['minimal_views'] = {**shelf.settings.get('minimal_views', {}), mode: minimal.get_active()}
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
