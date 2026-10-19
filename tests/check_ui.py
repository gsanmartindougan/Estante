"""Graphical layout regression check; uses only a temporary library."""
import os
import json
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from estante import App, Gdk, GdkPixbuf, GLib, Gtk


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from descendants(child)
        child = child.get_next_sibling()


with tempfile.TemporaryDirectory(prefix='estante-ui-') as directory:
    root = Path(directory)
    os.environ['ESTANTE_DATA_DIR'] = str(root / 'library')
    (root / 'library').mkdir()
    (root / 'library/settings.json').write_text(json.dumps({'language': 'es'}))
    os.environ['XDG_DATA_HOME'] = str(root / 'data')
    os.environ['XDG_CONFIG_HOME'] = str(root / 'config')
    app = App()
    app.set_application_id('io.github.estante.LayoutCheck')
    failures = []
    original = []
    games = []
    motion_sample = []

    def fail():
        failures.append(traceback.format_exc())
        app.quit()

    def setup():
        try:
            shelf = app.window
            shelf.set_default_size(1200, 800)
            script = root / 'test.sh'
            script.write_text('#!/bin/sh\nexit 0\n')
            for index, color in enumerate((0xB34734FF, 0x236C99FF)):
                image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 600, 200)
                image.fill(color)
                path = root / f'banner-{index}.png'
                image.savev(str(path), 'png', [], [])
                game = shelf.library.local_game(f'Game {index}', str(script), cover=str(path))
                game['banner'] = str(path)
                game['square_cover'] = str(path)
                shelf.library.put(game)
                games.append(game)
            shelf.reload()
            GLib.timeout_add(300, open_panel)
        except Exception:
            fail()
        return False

    def geometry():
        flow = app.window.flow
        return (flow.get_width(), [(w.get_allocation().x, w.get_allocation().y,
                                   w.get_width(), w.get_height())
                                  for w in descendants(flow) if isinstance(w, Gtk.FlowBoxChild)])

    def open_panel():
        try:
            shelf = app.window
            assert not any(isinstance(w, Gtk.Label) for tile in shelf.tiles() for w in descendants(tile.button)), 'Text on cards'
            original.append(geometry())
            shelf.details(games[0])
            GLib.timeout_add(350, verify_open)
        except Exception:
            fail()
        return False

    def verify_open():
        try:
            shelf = app.window
            assert geometry() == original[0], 'Opening panel moved/resized the grid'
            assert shelf.drawer.get_reveal_child()
            assert abs(shelf.drawer.get_width() - shelf.scene.get_width() // 2) <= 1, shelf.drawer.get_width()
            assert shelf.backdrop.get_paintable() is not None
            assert shelf.backdrop.get_content_fit() == Gtk.ContentFit.CONTAIN, 'Panoramic hero is cropped'
            assert shelf.backdrop.image_bounds().get_y() == 0, 'Banner is not aligned to the top'
            assert shelf.backdrop_fill.texture == shelf.backdrop.get_paintable()
            assert shelf.backdrop_fill.color is not None
            first_background = shelf.backdrop.get_paintable()
            shelf.focus_game(games[1])
            assert shelf.backdrop.get_paintable() != first_background, 'Background did not change'
            assert shelf.backdrop_fill.texture == shelf.backdrop.get_paintable(), 'Blurred fill did not update'
            frame = next(w for w in descendants(shelf.sidebar) if isinstance(w, Gtk.AspectFrame))
            assert frame.get_child().get_width() <= 114
            assert frame.get_child().get_height() <= 170
            assert len([w for w in Gtk.Window.get_toplevels() if w.get_visible()]) == 1
            shelf.close_panel()
            GLib.timeout_add(250, verify_closed)
        except Exception:
            fail()
        return False

    def verify_closed():
        try:
            assert geometry() == original[0], 'Closing panel moved/resized the grid'
            shelf = app.window
            shelf.key_pressed(None, Gdk.KEY_Left, 0, 0)
            assert shelf.selected_game == games[0]['id'], 'Keyboard selection failed'
            assert shelf.tiles()[0].button.has_css_class('selected-game')
            for key, state in ((Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK), (Gdk.KEY_slash, 0)):
                shelf.key_pressed(None, key, 0, state)
                assert shelf.search.has_focus() or shelf.get_focus().is_ancestor(shelf.search)
                shelf.focus_library()
            shelf.pointer_moved(None, 10, 10)
            shelf.navigate('search', True)
            assert shelf.gamepad_cursor_hidden
            assert shelf.get_cursor().get_name() == 'none'
            shelf.pointer_moved(None, 10, 10)
            assert shelf.gamepad_cursor_hidden, 'Unchanged pointer restored the cursor'
            shelf.pointer_moved(None, 20, 20)
            assert not shelf.gamepad_cursor_hidden and shelf.get_cursor() is None
            assert shelf.search.has_focus() or shelf.get_focus().is_ancestor(shelf.search)
            shelf.focus_library()
            for tile in shelf.tiles():
                controllers = tile.button.observe_controllers()
                assert not any(isinstance(controllers.get_item(i), Gtk.EventControllerMotion)
                               for i in range(controllers.get_n_items())), 'Hover changes selection'
            shelf.navigate('confirm', True)
            assert not shelf.drawer.get_reveal_child(), 'Selection opened a panel'
            assert not hasattr(shelf.tiles()[0], 'inline_actions'), 'Grid has duplicate actions'
            assert geometry() == original[0], 'Selection resized the grid'
            GLib.timeout_add(180, verify_controls)
        except Exception:
            fail()
        return False

    def verify_controls():
        try:
            shelf = app.window
            assert isinstance(shelf.get_focus(), Gtk.Button)
            assert shelf.get_focus().get_label() == '▶ Jugar', 'Selection did not focus Play'
            play_button = shelf.get_focus()
            if shelf.is_active():
                assert play_button.has_css_class('action-focused'), 'Play focus is not visible'
            shelf.navigate('right', True)
            assert shelf.get_focus().get_label() == 'Editar'
            if shelf.is_active():
                assert shelf.get_focus().has_css_class('action-focused'), 'Edit focus is not visible'
            assert not play_button.has_css_class('action-focused'), 'Previous button stayed highlighted'
            shelf.navigate('left', True)
            assert shelf.get_focus() == play_button
            if shelf.is_active():
                assert play_button.has_css_class('action-focused')
            shelf.game_actions.get_last_child().emit('clicked')
            assert shelf.drawer.get_reveal_child(), 'Edit did not open editor'
            shelf.navigate('back', True)
            assert not shelf.drawer.get_reveal_child()
            shelf.navigate('right', True)
            assert shelf.selected_game == games[1]['id'], 'Gamepad direction failed'
            selected_banner = games[0]['banner']
            def immediate(work, done, on_error=None):
                done(work())
            def click(label):
                next(w for w in descendants(shelf.sidebar)
                     if isinstance(w, Gtk.Button) and w.get_label() == label).emit('clicked')
            with patch.object(shelf, 'background', immediate), \
                 patch('estante.SteamGridDB.search', return_value=[{'id': 42, 'name': 'Fixture'}]), \
                 patch('estante.SteamGridDB.heroes', return_value=[{'url': 'fixture'}]) as heroes, \
                 patch('estante.SteamGridDB.download', return_value=selected_banner):
                shelf.artwork(games[1], banner=True)
                click('Buscar en SteamGridDB')
                click('Fixture')
                heroes.assert_called_once_with(42)
                preview = next(w for w in descendants(shelf.sidebar)
                               if isinstance(w, Gtk.Button) and isinstance(w.get_child(), Gtk.AspectFrame))
                preview.emit('clicked')
            saved = next(row for row in shelf.library.games() if row['id'] == games[1]['id'])
            assert saved['banner'] == selected_banner
            assert saved['cover'] == games[1]['cover'], 'Banner picker changed cover'
            with patch.object(shelf, 'background', immediate), \
                 patch('estante.SteamGridDB.search', return_value=[{'id': 42, 'name': 'Square fixture'}]), \
                 patch('estante.SteamGridDB.grids', return_value=[{'url': 'fixture'}]) as grids, \
                 patch('estante.SteamGridDB.download', return_value=selected_banner):
                shelf.artwork(saved, square=True)
                click('Buscar en SteamGridDB')
                click('Square fixture')
                grids.assert_called_once_with(42, square=True)
                preview = next(w for w in descendants(shelf.sidebar)
                               if isinstance(w, Gtk.Button) and isinstance(w.get_child(), Gtk.AspectFrame))
                preview.emit('clicked')
            saved = next(row for row in shelf.library.games() if row['id'] == games[1]['id'])
            assert saved['square_cover'] == selected_banner
            assert saved['cover'] == games[1]['cover']
            igdb_image = str(shelf.library.root / 'igdb-test.png')
            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 320, 180)
            pixbuf.fill(0x993333ff)
            pixbuf.savev(igdb_image, 'png', [], [])
            previous_id = saved.get('steamgriddb_id')
            with patch.object(shelf, 'background', immediate), \
                 patch('estante.IGDBArtwork.search', return_value=[{'id': 999, 'name': 'IGDB fixture'}]), \
                 patch('estante.IGDBArtwork.images', return_value=[{'url': 'fixture', 'width': 1920, 'height': 1080}]) as images, \
                 patch('estante.SteamGridDB.download', return_value=igdb_image):
                shelf.artwork(saved, banner=True)
                click('Buscar fondos 16:9 en IGDB')
                click('IGDB fixture')
                images.assert_called_once_with(999)
                preview = next(w for w in descendants(shelf.sidebar)
                               if isinstance(w, Gtk.Button) and isinstance(w.get_child(), Gtk.AspectFrame))
                assert preview.get_sensitive()
                preview.emit('clicked')
            saved = next(row for row in shelf.library.games() if row['id'] == games[1]['id'])
            assert saved['banner'] == igdb_image
            assert saved['steamgriddb_id'] == previous_id, 'IGDB replaced the SteamGridDB identity'
            assert saved['cover'] == games[1]['cover']
            fixture = {'title': 'Game information', 'developers': ['Fixture Studio'],
                       'publishers': ['Fixture Publisher'], 'genres': ['Action'],
                       'platforms': ['Linux'], 'description': 'A test game',
                       'release_date': '2020-01-02', 'source': 'https://www.wikidata.org/wiki/Q1', 'entity_id': 'Q1'}
            with patch.object(shelf, 'background', immediate), \
                 patch('estante.GameMetadata.search', return_value=[{'id': 'Q1', 'name': 'Fixture game', 'description': 'Test'}]), \
                 patch('estante.GameMetadata.fetch', return_value=fixture):
                shelf.metadata_search(saved)
                click('Buscar en Wikidata')
                click('Fixture game')
                click('Usar esta ficha')
            saved = next(row for row in shelf.library.games() if row['id'] == games[1]['id'])
            assert saved['metadata']['developers'] == ['Fixture Studio']
            shelf.update_game_information(saved)
            labels = [w.get_text() for w in descendants(shelf.game_information) if isinstance(w, Gtk.Label)]
            assert 'Estudio: Fixture Studio' in labels
            assert 'Editora: Fixture Publisher' in labels
            assert 'Primer lanzamiento registrado: 02/01/2020' in labels
            shelf.metadata_edit(saved)
            fields = [w for w in descendants(shelf.sidebar) if isinstance(w, Gtk.Entry)]
            assert len(fields) == 6
            fields[1].set_text('Estudio manual, Otro estudio')
            fields[-1].set_text('31/02/2020')
            description = next(w for w in descendants(shelf.sidebar) if isinstance(w, Gtk.TextView))
            description.get_buffer().set_text('Descripción escrita a mano')
            click('Guardar ficha')
            assert shelf.drawer.get_reveal_child(), 'Invalid date was accepted'
            assert next(row for row in shelf.library.games() if row['id'] == saved['id'])['metadata'] == fixture
            fields[-1].set_text('15/03/2020')
            click('Guardar ficha')
            saved = next(row for row in shelf.library.games() if row['id'] == saved['id'])
            assert saved['metadata']['developers'] == ['Estudio manual', 'Otro estudio']
            assert saved['metadata']['release_date'] == '2020-03-15'
            assert saved['metadata']['description'] == 'Descripción escrita a mano'
            assert saved['metadata']['source'] == fixture['source']
            assert saved['cover'] == games[1]['cover'] and saved['banner'] == igdb_image
            assert not shelf.drawer.get_reveal_child()
            shelf.metadata_edit(saved)
            click('Cancelar')
            assert next(row for row in shelf.library.games() if row['id'] == saved['id'])['metadata'] == saved['metadata']

            gesture = MagicMock()
            with patch.object(shelf, 'play') as play:
                shelf.tile_pressed(gesture, 1, saved)
                play.assert_not_called()
                shelf.tile_pressed(gesture, 2, saved)
                play.assert_called_once_with(saved)
                gesture.set_state.assert_called_once_with(Gtk.EventSequenceState.CLAIMED)
            print('PASS: image-only cards, overlay panel at half window width, unchanged grid, '
                  'selected-game background, keyboard/gamepad navigation, banner picker, double-click Play')
            shelf.close_panel()
            for index in range(8):
                game = shelf.library.local_game(f'Extra {index}', str(root / 'test.sh'), cover=games[0]['cover'])
                game['banner'] = games[0]['banner']
                game['square_cover'] = games[0]['square_cover']
                shelf.library.put(game)
            shelf.settings['sentinel'] = True
            shelf.change_view('carousel')
            GLib.timeout_add(200, verify_carousel)
        except Exception:
            fail()
        return False

    def verify_carousel():
        try:
            shelf = app.window
            assert shelf.view_mode == 'carousel'
            assert shelf.spotlight.get_visible()
            assert shelf.info_scroll.get_visible()
            activity = shelf.game_information.get_first_child()
            information = activity.get_next_sibling()
            assert information and information.get_next_sibling() is None
            valid_activity, activity_bounds = activity.compute_bounds(shelf.game_information)
            valid_info, info_bounds = information.compute_bounds(shelf.game_information)
            assert valid_activity and valid_info
            assert activity_bounds.get_x() + activity_bounds.get_width() <= info_bounds.get_x() + 1
            assert abs(activity_bounds.get_y() - info_bounds.get_y()) < 1
            assert len({tile.get_allocation().y for tile in shelf.tiles()}) == 1
            adjustment = shelf.library_scroll.get_hadjustment()
            assert adjustment.get_upper() > adjustment.get_page_size(), 'Carousel does not scroll horizontally'
            shelf.focus_library()
            shelf.navigate('left', True)
            shelf.navigate('down', True)
            assert shelf.get_focus().is_ancestor(shelf.spotlight), 'Gamepad cannot reach Play'
            if shelf.is_active():
                assert shelf.get_focus().has_css_class('action-focused')
            shelf.navigate('right', True)
            assert shelf.get_focus().get_label() == 'Editar'
            if shelf.is_active():
                assert shelf.get_focus().has_css_class('action-focused')
            shelf.navigate('up', True)
            assert shelf.get_focus().is_ancestor(shelf.flow), 'Gamepad cannot return to carousel'
            identities = list(dict.fromkeys(tile.game['id'] for tile in shelf.tiles()))
            original_id = shelf.selected_game
            for _ in range(len(identities) * 2):
                shelf.navigate('right', True)
            assert shelf.selected_game == original_id, 'Carousel does not loop right'
            for _ in range(len(identities) * 2):
                shelf.navigate('left', True)
            assert shelf.selected_game == original_id, 'Carousel does not loop left'
            shelf.search.set_text('Extra 2')
            shelf.filter()
            assert len({tile.game['id'] for tile in shelf.tiles()}) == 1
            assert shelf.count.get_text() == '1 juegos'
            shelf.search.set_text('')
            shelf.filter()
            shelf.focus_library()
            GLib.timeout_add(400, verify_carousel_center)
        except Exception:
            fail()
        return False

    def verify_carousel_center():
        try:
            shelf = app.window
            tile = shelf.selected_tile()
            valid, bounds = tile.button.compute_bounds(shelf.strip)
            assert valid
            assert abs(bounds.get_x() + bounds.get_width()/2 - shelf.strip.get_width()/2) < 3, (
                bounds.get_x(), bounds.get_width(), shelf.strip.get_width())
            assert abs(bounds.get_width() - 192 * shelf.carousel_zoom()) < 2
            assert abs(bounds.get_height() - 288 * shelf.carousel_zoom()) < 2
            assert bounds.get_y() >= 0
            assert bounds.get_y() + bounds.get_height() <= shelf.strip.get_height() + 1
            valid_selector, selector_bounds = shelf.ps5_selector.compute_bounds(shelf.strip)
            assert valid_selector and abs(selector_bounds.get_width() - bounds.get_width()) < 2
            assert shelf.ps5_selector.get_halign() == Gtk.Align.CENTER
            print('PASS: infinite carousel in both directions, stationary central selector, metadata in carousel')
            shelf.settings['carousel_position'] = 'bottom'
            shelf.configure_view()
            GLib.timeout_add(300, verify_bottom_carousel)
        except Exception:
            fail()
        return False

    def verify_ps5():
        try:
            import json
            shelf = app.window
            assert shelf.view_mode == 'ps5'
            assert len({tile.get_allocation().y for tile in shelf.tiles()}) == 1
            picture = next(w for w in descendants(shelf.tiles()[0]) if isinstance(w, Gtk.Picture))
            assert picture.get_width() == picture.get_height(), 'PS5 tile is not square'
            assert picture.get_content_fit() == Gtk.ContentFit.CONTAIN
            first = shelf.tiles()[0]
            assert first.button.get_width() == first.button.get_height(), 'Button adds side bars'
            assert first.button.get_width() == 104
            assert isinstance(first.button.get_child(), Gtk.Picture), 'Cover still has a box behind it'
            assert first.button.get_overflow() == Gtk.Overflow.VISIBLE, 'Cover animation is clipped'
            snapshot = Gtk.Snapshot.new()
            first.button.get_child().do_snapshot(snapshot)
            node = snapshot.to_node()
            assert node is not None, 'Rounded cover produces an empty render node'
            assert node.get_bounds().get_width() > 100, 'Rounded clipping rectangle is invalid'
            saved = json.loads(shelf.settings_path.read_text())
            assert saved['layout'] == 'ps5' and saved['sentinel'] is True
            assert shelf.spotlight_title.get_text()
            assert shelf.info_scroll.get_visible()
            labels = [w.get_text() for w in descendants(shelf.game_information) if isinstance(w, Gtk.Label)]
            for heading in ('Tiempo jugado', 'Sesiones en Estante', 'Última sesión',
                            'Última vez', 'Información del juego', 'Sesiones recientes'):
                assert heading in labels, f'Missing game information: {heading}'
            shelf.select_tile(first)
            GLib.timeout_add(400, verify_first_anchor)
        except Exception:
            fail()
        return False

    def verify_bottom_carousel():
        try:
            shelf = app.window
            assert shelf.games_page.get_last_child() == shelf.strip
            valid, covers = shelf.strip.compute_bounds(shelf.games_page)
            valid_info, information = shelf.details_column.compute_bounds(shelf.games_page)
            assert valid and valid_info
            assert information.get_y() + information.get_height() <= covers.get_y() + 1
            shelf.focus_library()
            shelf.navigate('up', True)
            assert shelf.get_focus().is_ancestor(shelf.spotlight)
            shelf.navigate('down', True)
            assert shelf.get_focus().is_ancestor(shelf.flow)
            shelf.change_view('ps5')
            assert shelf.games_page.get_first_child() == shelf.strip
            GLib.timeout_add(200, verify_ps5)
        except Exception:
            fail()
        return False

    def check_anchor(tile):
        shelf = app.window
        valid, bounds = tile.button.compute_bounds(shelf.strip)
        visible, selector = shelf.ps5_selector.compute_bounds(shelf.strip)
        assert valid and visible
        assert abs(bounds.get_x() - selector.get_x()) < 6, (bounds.get_x(), selector.get_x())
        assert abs(bounds.get_width() - 156) < 2, bounds.get_width()
        assert abs(bounds.get_height() - 156) < 2, bounds.get_height()

    def verify_first_anchor():
        try:
            shelf = app.window
            check_anchor(shelf.tiles()[0])
            shelf.select_tile(shelf.tiles()[-1])
            GLib.timeout_add(400, verify_last_anchor)
        except Exception:
            fail()
        return False

    def verify_last_anchor():
        try:
            shelf = app.window
            check_anchor(shelf.tiles()[-1])
            assert shelf.library_scroll.get_hadjustment().get_value() > 0
            print('PASS: square image/button without bars, animated 1.5x zoom, '
                  'fixed left selector with first and last game anchored under it')
            shelf.preferences()
            assert shelf.pages.get_visible_child_name() == 'settings'
            assert not shelf.drawer.get_reveal_child(), 'Settings still use the side panel'
            globals_widgets = list(descendants(shelf.preferences_view.sections.get_visible_child()))
            next(w for w in globals_widgets if isinstance(w, Gtk.CheckButton) and
                 w.get_label() == 'Color predominante del hero').set_active(True)
            next(w for w in globals_widgets if isinstance(w, Gtk.Button) and w.get_label() == 'Guardar globales').emit('clicked')
            shelf.preferences_view.show_section('ps5')
            navigation = list(shelf.preferences_view.controls(shelf.preferences_view.navigation))
            navigation[-1].grab_focus()
            shelf.navigate('confirm', True)
            assert shelf.preferences_view.sections.get_visible_child_name() == 'ps5'
            shelf.navigate('right', True)
            assert shelf.get_focus().is_ancestor(shelf.preferences_view.sections)
            widgets = list(descendants(shelf.preferences_view.sections.get_visible_child()))
            scale = next(w for w in widgets if isinstance(w, Gtk.Scale))
            scale.grab_focus()
            old_value = scale.get_value()
            shelf.navigate('right', True)
            assert scale.get_value() > old_value
            shelf.navigate('left', True)
            assert scale.get_value() == old_value
            shelf.navigate('down', True)
            assert isinstance(shelf.get_focus(), Gtk.Switch)
            switch = shelf.get_focus()
            old_active = switch.get_active()
            shelf.navigate('confirm', True)
            assert switch.get_active() != old_active
            shelf.navigate('confirm', True)
            assert switch.get_active() == old_active
            spinner = next(w for w in widgets if isinstance(w, Gtk.SpinButton))
            spinner.grab_focus()
            old_value = spinner.get_value()
            shelf.navigate('right', True)
            assert spinner.get_value() == old_value + 1
            next(w for w in widgets if isinstance(w, Gtk.Scale)).set_value(208)
            [w for w in widgets if isinstance(w, Gtk.Scale)][-1].set_value(20)
            [w for w in widgets if isinstance(w, Gtk.Switch)][-1].set_active(False)
            next(w for w in widgets if isinstance(w, Gtk.Entry) and w.get_text().startswith('#')).set_text('#75baff')
            spinners = [w for w in widgets if isinstance(w, Gtk.SpinButton)]
            spinners[0].set_value(5)
            spinners[1].set_value(8)
            next(w for w in widgets if isinstance(w, Gtk.Button) and w.get_label() == 'Guardar aspecto').grab_focus()
            shelf.navigate('confirm', True)
            shelf.preferences_view.show_section('grid')
            grid_widgets = list(descendants(shelf.preferences_view.sections.get_visible_child()))
            assert not any(isinstance(w, Gtk.Label) and w.get_text() == 'Tamaño del juego con foco (px)'
                           for w in grid_widgets), 'Sense-only controls appear under Grid'
            [w for w in grid_widgets if isinstance(w, Gtk.Scale)][-1].set_value(0)
            next(w for w in grid_widgets if isinstance(w, Gtk.Scale)).set_value(150)
            next(w for w in grid_widgets if isinstance(w, Gtk.Button) and w.get_label() == 'Guardar aspecto').emit('clicked')
            assert shelf.view_mode == 'ps5', 'Editing Grid changed the active library view'
            shelf.leave_preferences()
            assert shelf.pages.get_visible_child_name() == 'library'
            GLib.timeout_add(400, verify_appearance)
        except Exception:
            fail()
        return False

    def verify_appearance():
        try:
            import json
            shelf = app.window
            saved = json.loads(shelf.settings_path.read_text())
            ring = saved['selection_rings']['ps5']
            assert saved['ps5_focus_size'] == 208 and ring['focus_ring_enabled'] is False
            assert saved['ps5_motion'] is True
            assert saved['background_fill'] == 'dominant'
            assert shelf.backdrop_fill.mode == 'dominant'
            assert shelf.backdrop_fill.color is not None
            assert shelf.backdrop_fill.color.red > shelf.backdrop_fill.color.blue
            assert ring['focus_ring_width'] == 5 and ring['focus_ring_radius'] == 8
            assert saved['cover_radii']['ps5'] == 20
            assert saved['cover_radii']['grid'] == 0
            assert saved['grid_zoom'] == 150
            assert saved['selection_rings']['carousel']['focus_ring_enabled'] is True
            assert saved['selection_rings']['grid']['focus_ring_width'] == 3
            assert saved['sentinel'] is True
            assert not shelf.ps5_selector.get_visible(), 'Disabled ring is still visible'
            assert shelf.library_scroll.get_policy()[0] == Gtk.PolicyType.EXTERNAL
            selected = next(tile for tile in shelf.tiles() if tile.game['id'] == shelf.selected_game)
            assert selected.button.get_child().corner_radius == 20
            assert selected.button.get_child().get_mapped(), 'Cover not mapped after leaving settings'
            snapshot = Gtk.Snapshot.new()
            selected.button.get_child().do_snapshot(snapshot)
            assert snapshot.to_node() is not None, 'Cover disappeared after changing appearance settings'
            assert shelf.flow.get_width() >= sum(tile.get_width() for tile in shelf.tiles()), 'Horizontal row was underallocated'
            valid, bounds = selected.button.compute_bounds(shelf.strip)
            assert valid and abs(bounds.get_width() - 208) < 2, bounds.get_width()
            assert abs(bounds.get_x() - 24) < 6, bounds.get_x()
            assert shelf.flow.get_spacing() == 12, 'Zoom spreads all games apart'
            assert all(tile.get_child().get_margin_end() == 0 for tile in shelf.tiles()
                       if tile != selected), 'Unselected games reserve zoom space'
            picture = next(w for w in descendants(selected.button) if isinstance(w, Gtk.Picture))
            _, image_bounds = picture.compute_bounds(selected.button)
            motion_sample.append((picture, selected.button, image_bounds.get_x(), image_bounds.get_y()))
            print('PASS: saved zoom/color/thickness/radius, optional ring, 2x zoom at fixed anchor, hidden scrollbar')
            GLib.timeout_add(350, verify_motion)
        except Exception:
            fail()
        return False

    def verify_motion():
        try:
            picture, target, x, y = motion_sample[0]
            _, bounds = picture.compute_bounds(target)
            if Gtk.Settings.get_default().get_property('gtk-enable-animations'):
                assert abs(bounds.get_x() - x) + abs(bounds.get_y() - y) > 0.01, 'Focused cover is not animated'
            print('PASS: compact gaps independent of zoom and continuous focused-cover motion')
            app.window.change_view('carousel')
            assert app.window.ps5_selector.get_visible(), 'Sense ring settings leaked into Carousel'
            assert app.window.selected_tile().button.get_child().corner_radius == 12
            app.window.change_view('grid')
            assert app.window.selected_tile().button.get_child().get_size_request() == (234, 351)
            GLib.timeout_add(200, verify_grid)
        except Exception:
            fail()
        return False

    def verify_grid():
        try:
            shelf = app.window
            assert shelf.view_mode == 'grid'
            assert shelf.spotlight.get_visible()
            assert shelf.info_scroll.get_visible()
            assert shelf.games_page.get_orientation() == Gtk.Orientation.HORIZONTAL
            valid, covers = shelf.strip.compute_bounds(shelf.games_page)
            valid_details, details = shelf.details_column.compute_bounds(shelf.games_page)
            assert valid and valid_details
            assert covers.get_x() + covers.get_width() <= details.get_x() + 1, 'Grid columns overlap'
            assert details.get_width() > 300
            assert len({tile.get_allocation().y for tile in shelf.tiles()}) > 1
            print('PASS: Grid/Carousel/PS5 layouts, horizontal scrolling, search, '
                  'gamepad spotlight navigation, preserved settings and saved view; split grid with game data')
            shelf.focus_game(games[0])
            shelf.play(games[0])
            GLib.timeout_add(300, verify_session)
        except Exception:
            fail()
        return False

    def verify_session():
        try:
            shelf = app.window
            stats = shelf.library.game_stats(games[0])
            assert stats['sessions'] == 1, stats
            assert len(stats['history']) == 1
            assert stats['history'][0]['exit_code'] == 0
            assert shelf.processes[games[0]['id']].poll() == 0
            print('PASS: lower game information and stats; temporary script completion updates saved session history')
            long_title = 'Cyberpunk 2077: ' + 'Una edición de nombre extraordinariamente largo ' * 12
            def immediate(work, done, on_error=None):
                done(work())
            with patch.object(shelf, 'background', immediate), \
                 patch('estante.GameMetadata.search', return_value=[{
                     'id': 'Q1', 'name': long_title, 'description': 'DescripciónSinEspacios' * 80}]):
                shelf.metadata_search(games[0])
                next(w for w in descendants(shelf.sidebar) if isinstance(w, Gtk.Button)
                     and w.get_label() == 'Buscar en Wikidata').emit('clicked')
            GLib.timeout_add(200, verify_sidebar_width)
        except Exception:
            fail()
        return False

    def verify_sidebar_width():
        try:
            shelf = app.window
            assert abs(shelf.drawer.get_width() - shelf.scene.get_width() // 2) <= 1, shelf.drawer.get_width()
            assert shelf.sidebar.get_width() <= shelf.scene.get_width() // 2, shelf.sidebar.get_width()
            close = next(w for w in descendants(shelf.sidebar) if isinstance(w, Gtk.Button)
                         and w.get_icon_name() == 'window-close-symbolic')
            valid, bounds = close.compute_bounds(shelf.scene)
            assert valid and bounds.get_x() >= 0
            assert bounds.get_x() + bounds.get_width() <= shelf.scene.get_width(), 'Close button offscreen'
            for widget in descendants(shelf.sidebar):
                if isinstance(widget, Gtk.Label) and widget.get_text().startswith('Cyberpunk 2077:'):
                    valid, text = widget.compute_bounds(shelf.sidebar)
                    assert valid and text.get_x() + text.get_width() <= shelf.sidebar.get_width()
                    assert widget.get_wrap()
            print('PASS: extremely long titles/descriptions wrap inside sidebar; close control remains onscreen')
            def immediate(work, done, on_error=None):
                done(work())
            with patch.object(shelf, 'background', immediate), \
                 patch('estante.SteamGridDB.search', return_value=[{'id': 42, 'name': 'Gallery fixture'}]), \
                 patch('estante.SteamGridDB.heroes', return_value=[{'url': 'fixture'}] * 4), \
                 patch('estante.SteamGridDB.download', return_value=games[0]['banner']):
                shelf.artwork(games[0], banner=True)
                for title in ('Buscar en SteamGridDB', 'Gallery fixture'):
                    next(w for w in descendants(shelf.sidebar)
                         if isinstance(w, Gtk.Button) and w.get_label() == title).emit('clicked')
            GLib.timeout_add(250, verify_gallery_navigation)

        except Exception:
            failures.append(traceback.format_exc())
            app.quit()
        return False

    def verify_gallery_navigation():
        try:
            shelf = app.window
            flow = shelf.artwork_gallery
            cards = list(shelf.gallery_cards(flow))
            assert len(cards) == 4
            bounds = [card.compute_bounds(flow)[1] for card in cards]
            assert abs(bounds[0].get_y() - bounds[1].get_y()) < 1
            assert bounds[2].get_y() > bounds[0].get_y()
            assert bounds[1].get_x() > bounds[0].get_x()
            frame = cards[0].get_child()
            assert frame.get_child().get_content_fit() == Gtk.ContentFit.CONTAIN
            cards[0].grab_focus()
            shelf.navigate('right', True)
            assert shelf.get_focus() == cards[1]
            shelf.navigate('down', True)
            assert shelf.get_focus() == cards[3]
            shelf.key_pressed(None, Gdk.KEY_Left, 0, 0)
            assert shelf.get_focus() == cards[2]
            shelf.key_pressed(None, Gdk.KEY_Up, 0, 0)
            assert shelf.get_focus() == cards[0]
            with patch.object(cards[0], 'activate', return_value=True) as activate:
                shelf.navigate('confirm', True)
                activate.assert_called_once()
            print('PASS: two-column artwork gallery, uncropped previews, keyboard and gamepad navigation/confirmation')
            shelf.close_panel()
            for mode in ('grid', 'carousel', 'ps5'):
                shelf.change_view(mode)
                tiles = shelf.tiles()
                identities = list(dict.fromkeys(tile.game['id'] for tile in tiles))
                first = next(tile for tile in tiles if tile.game['id'] == identities[0])
                shelf.select_tile(first)
                from controls import alphabet_target
                titles = [next(tile.game['title'] for tile in tiles if tile.game['id'] == identity) for identity in identities]
                destination = alphabet_target(titles, 0)
                shelf.navigate('page_next', True)
                assert shelf.selected_game == identities[destination], mode
                from controls import alphabet_window
                assert tuple(label.get_text() for label in shelf.alphabet_labels) == alphabet_window(titles, titles[destination])
                shelf.navigate('page_previous', True)
                assert shelf.selected_game == identities[alphabet_target(titles, destination, False)], mode
            print('PASS: bumper jumps select the expected game in Grid, Carousel and Sense')

        except Exception:
            failures.append(traceback.format_exc())
        finally:
            app.quit()
        return False

    app.connect('activate', lambda *_: GLib.timeout_add(300, setup))
    app.run([])
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        raise SystemExit(1)
