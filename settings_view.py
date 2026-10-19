"""Dedicated in-window settings, split into global and per-view pages."""
from i18n import tr
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gtk
from appearance import VIEW_NAMES, ring_for, with_ring, cover_radius_for, hero_position_for, cover_format_for
from version import __version__
from updates import latest_release, appimage_path, update_available, install_appimage, RELEASES_URL


class SettingsView(Gtk.Box):
    def __init__(self, shelf, button, margins, section='global'):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=['background'])
        self.shelf, self.button, self.margins = shelf, button, margins
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
        nav.append(button(tr('Categorías'), lambda: self.show_section('categories')))
        nav.append(margins(Gtk.Label(label=tr('APARIENCIA'), xalign=0, css_classes=['dim-label']), 8))
        for mode, name in VIEW_NAMES.items():
            nav.append(button(name, lambda mode=mode: self.show_section(mode)))
        self.global_page()
        self.categories_page()
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
            if isinstance(child, types):
                if child.get_sensitive():
                    yield child
            else:
                yield from SettingsView.controls(child)
            child = child.get_next_sibling()

    def navigate(self, action):
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
            if owner in navigation and action == 'right' and page:
                page[0].grab_focus()
                return True
            if owner in page and action == 'left':
                navigation[('global', 'categories', *VIEW_NAMES).index(self.sections.get_visible_child_name())].grab_focus()
                return True
        index = controls.index(owner)
        delta = -1 if action in ('up', 'left') else 1
        controls[max(0, min(len(controls)-1, index + delta))].grab_focus()
        return True

    def show_section(self, section):
        self.sections.set_visible_child_name(section if section in ('global', 'categories', *VIEW_NAMES) else 'global')

    def categories_page(self):
        shelf = self.shelf
        box = self.page('categories', tr('Categorías'), tr('Crea, renombra o elimina categorías. Asígnalas desde Editar → Categorías en cada juego.'))
        entry = shelf.field(box, tr('Nueva categoría'))
        feedback = Gtk.Label(xalign=0, wrap=True)
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        def change(name, previous=None, delete=False):
            try:
                shelf.library.manage_category(name, previous, delete)
                if previous == shelf.active_category:
                    shelf.active_category = None if delete else name.strip()
                shelf.reload()
                entry.set_text('')
                refresh()
                feedback.set_text(tr('Categoría eliminada. Los juegos se conservan.') if delete else tr('Categorías guardadas.'))
                entry.grab_focus()
            except Exception as error:
                feedback.set_text(str(error))
        def refresh():
            while child := rows.get_first_child():
                rows.remove(child)
            for name in shelf.library.categories():
                row = Gtk.Box(spacing=8)
                value = Gtk.Entry(text=name, hexpand=True)
                row.append(value)
                row.append(self.button(tr('Renombrar'), lambda name=name, value=value: change(value.get_text(), name)))
                row.append(self.button(tr('Eliminar'), lambda name=name: change('', name, True)))
                rows.append(row)
            for control in self.controls(rows):
                control.add_css_class('settings-control')
        box.append(self.button(tr('Crear categoría'), lambda: change(entry.get_text()), 'suggested-action'))
        box.append(feedback)
        box.append(Gtk.Separator())
        box.append(rows)
        refresh()

    def page(self, key, title, description):
        box = self.margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16), 32)
        box.append(Gtk.Label(label=title, xalign=0, css_classes=['title-1']))
        box.append(Gtk.Label(label=description, xalign=0, wrap=True, css_classes=['dim-label']))
        clamp = Adw.Clamp(maximum_size=760, tightening_threshold=600)
        clamp.set_child(box)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(clamp)
        self.sections.add_named(scroll, key)
        return box

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
        box.append(Gtk.Label(label=tr('Idioma'), xalign=0, css_classes=['title-3']))
        languages = {}
        previous = None
        preference = shelf.settings.get('language', 'system')
        if preference not in ('system', 'es', 'en'):
            preference = 'system'
        for code, name in (('system', tr('Idioma del sistema')), ('es', 'Español'), ('en', 'English')):
            choice = Gtk.CheckButton(label=name)
            if previous:
                choice.set_group(previous)
            previous = choice
            languages[code] = choice
            box.append(choice)
        languages[preference].set_active(True)
        box.append(Gtk.Label(label=tr('El idioma se aplicará al volver a abrir Estante.'), wrap=True, xalign=0,
                             css_classes=['dim-label']))
        box.append(Gtk.Separator())
        self.updates_section(box)
        box.append(Gtk.Label(label=tr('Aspecto de la biblioteca'), xalign=0, css_classes=['title-3']))
        views = {}
        previous = None
        for mode, name in VIEW_NAMES.items():
            choice = Gtk.CheckButton(label=name)
            if previous:
                choice.set_group(previous)
            previous = choice
            choice.set_active(shelf.view_mode == mode)
            views[mode] = choice
            box.append(choice)
        box.append(Gtk.Separator())
        box.append(Gtk.Label(label=tr('Relleno del fondo'), xalign=0, css_classes=['title-3']))
        blurred = Gtk.CheckButton(label=tr('Hero desenfocado'))
        dominant = Gtk.CheckButton(label=tr('Color predominante del hero'))
        dominant.set_group(blurred)
        dominant.set_active(shelf.settings.get('background_fill', 'blur') == 'dominant')
        blurred.set_active(not dominant.get_active())
        box.append(blurred)
        box.append(dominant)
        box.append(Gtk.Separator())
        box.append(Gtk.Label(label='SteamGridDB', xalign=0, css_classes=['title-3']))
        key = shelf.field(box, tr('Clave API'), shelf.settings.get('steamgriddb_key', ''), True)
        box.append(Gtk.LinkButton(uri='https://www.steamgriddb.com/profile/preferences/api', label=tr('Obtener mi clave API')))
        box.append(Gtk.Separator())
        box.append(Gtk.Label(label=tr('IGDB · fondos 16:9'), xalign=0, css_classes=['title-3']))
        igdb_id = shelf.field(box, tr('Client ID de Twitch'), shelf.settings.get('igdb_client_id', ''))
        igdb_secret = shelf.field(box, tr('Client Secret de Twitch'), shelf.settings.get('igdb_client_secret', ''), True)
        box.append(Gtk.LinkButton(uri='https://dev.twitch.tv/console/apps', label=tr('Crear credenciales de Twitch')))
        box.append(Gtk.LinkButton(uri='https://api-docs.igdb.com/#account-creation', label=tr('Instrucciones de IGDB')))
        feedback = Gtk.Label(xalign=0, wrap=True)
        box.append(feedback)
        def save():
            try:
                selected = next(mode for mode, choice in views.items() if choice.get_active())
                language = next(code for code, choice in languages.items() if choice.get_active())
                language_changed = language != shelf.settings.get('language', 'system')
                shelf.save_settings({**shelf.settings, 'steamgriddb_key': key.get_text().strip(),
                    'igdb_client_id': igdb_id.get_text().strip(), 'igdb_client_secret': igdb_secret.get_text().strip(),
                    'background_fill': 'dominant' if dominant.get_active() else 'blur',
                    'layout': selected, 'language': language})
                changed = shelf.view_mode != selected
                shelf.view_mode = selected
                shelf.configure_view()
                if changed:
                    shelf.reload()
                feedback.set_text(tr('Ajustes globales guardados. Reinicia Estante para aplicar el idioma.') if language_changed
                                  else tr('Ajustes globales guardados.'))
            except Exception as error:
                feedback.set_text(str(error))
        box.append(self.button(tr('Guardar globales'), save, 'suggested-action'))

    def updates_section(self, box):
        shelf = self.shelf
        status = Gtk.Label(label=tr('Busca nuevas versiones publicadas en GitHub.'), wrap=True, xalign=0)
        box.append(Gtk.Label(label=tr('Actualizaciones'), xalign=0, css_classes=['title-3']))
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
        box.append(Gtk.Separator())

    def appearance_page(self, mode):
        shelf = self.shelf
        ring = ring_for(shelf.settings, mode)
        box = self.page(mode, VIEW_NAMES[mode], tr('Estos ajustes se aplican solo a ') + VIEW_NAMES[mode] + '.')
        box.append(Gtk.Label(label=tr('Posición del hero'), xalign=0, css_classes=['title-3']))
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
        box.append(Gtk.Separator())
        carousel_zoom = carousel_bottom = None
        grid_zoom = None
        if mode == 'grid':
            grid_zoom = self.scale(box, tr('Zoom de las carátulas (%)'), shelf.grid_zoom() * 100, 50, 200, 5)
            box.append(Gtk.Separator())
        if mode == 'carousel':
            carousel_bottom = self.switch(box, tr('Mostrar los juegos en la parte inferior'),
                                          shelf.settings.get('carousel_position', 'top') == 'bottom')
            carousel_zoom = self.scale(box, tr('Zoom del juego con foco (%)'), shelf.carousel_zoom() * 100, 100, 175, 5)
            box.append(Gtk.Separator())
        zoom = motion = None
        if mode == 'ps5':
            zoom = self.scale(box, tr('Tamaño del juego con foco (px)'), shelf.ps5_focus_size(), 104, 320, 4)
            motion = self.switch(box, tr('Animación suave de la carátula'), shelf.settings.get('ps5_motion', True))
            box.append(Gtk.Separator())
        box.append(Gtk.Label(label=tr('Carátulas'), xalign=0, css_classes=['title-3']))
        square = Gtk.CheckButton(label=tr('Cuadrada (1:1)'))
        portrait = Gtk.CheckButton(label=tr('Vertical (2:3)'))
        portrait.set_group(square)
        square.set_active(cover_format_for(shelf.settings, mode) == 'square')
        portrait.set_active(not square.get_active())
        box.append(square)
        box.append(portrait)
        corners = self.scale(box, tr('Redondeado de las esquinas (px; 0 = rectas)'), cover_radius_for(shelf.settings, mode), 0, 40)
        box.append(Gtk.Separator())
        box.append(Gtk.Label(label=tr('Anillo de selección'), xalign=0, css_classes=['title-3']))
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
        box.append(feedback)
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
                feedback.set_text(tr('Aspecto ') + VIEW_NAMES[mode] + tr(' guardado.'))
            except Exception as error:
                feedback.set_text(str(error))
        box.append(self.button(tr('Guardar aspecto'), save, 'suggested-action'))
