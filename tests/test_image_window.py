from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from image_cache import nearby_indices
from estante import Shelf, Gtk


class ImageWindowTests(TestCase):
    def test_window_has_at_most_three_unique_games(self):
        for count in (0, 1, 2, 3, 7, 13, 1000):
            for index in range(count):
                for wrap in (False, True):
                    result = nearby_indices(count, index, wrap=wrap)
                    self.assertLessEqual(len(result), 3)
                    self.assertTrue(all(0 <= value < count for value in result))
                    self.assertIn(index, result)
        self.assertEqual(nearby_indices(13, 0), {0, 1})
        self.assertEqual(nearby_indices(13, 0, wrap=True), {12, 0, 1})

    def test_navigation_releases_old_images_and_loads_only_new_neighbour(self):
        rows = [SimpleNamespace(game={'id': str(i), 'logo': f'{i}.png'}, image_loaded=False,
                                button=Mock()) for i in range(13)]
        for index, row in enumerate(rows):
            row.get_next_sibling = lambda i=index: rows[i + 1] if i + 1 < len(rows) else None
        host = SimpleNamespace(tiles=lambda: rows, selected_game='6', view_mode='list', settings={},
                               flow=SimpleNamespace(get_first_child=lambda: rows[0]),
                               logo_image=Mock(), cover=Mock(), request_picture=Mock())
        with patch('estante.release_images') as release, patch('estante.Gtk.Box'), \
             patch('estante.images.retain_paths') as retain:
            Shelf.update_image_window(host)
            self.assertEqual(host.logo_image.call_count, 3)
            self.assertEqual(sum(row.image_loaded for row in rows), 3)
            host.logo_image.reset_mock()
            release.reset_mock()
            old_selected, new_selected = Mock(spec=Gtk.Picture), Mock(spec=Gtk.Picture)
            old_selected.image_ticket = SimpleNamespace(cancelled=False)
            new_selected.image_ticket = SimpleNamespace(cancelled=False)
            rows[6].button.get_child.return_value = old_selected
            rows[7].button.get_child.return_value = new_selected
            rows[6].button.set_child.reset_mock()
            rows[7].button.set_child.reset_mock()
            host.selected_game = '7'
            Shelf.update_image_window(host)
            self.assertEqual(host.request_picture.call_count, 2)
            self.assertEqual([call.args[4] for call in host.request_picture.call_args_list], [1, 0])
            self.assertTrue(old_selected.image_ticket.cancelled)
            self.assertTrue(new_selected.image_ticket.cancelled)
            old_selected.set_paintable.assert_not_called()
            new_selected.set_paintable.assert_not_called()
            rows[6].button.set_child.assert_not_called()
            rows[7].button.set_child.assert_not_called()
            self.assertEqual(host.logo_image.call_count, 1)
            self.assertFalse(rows[5].image_loaded)
            self.assertTrue(rows[8].image_loaded)
            self.assertEqual(sum(row.image_loaded for row in rows), 3)
            self.assertNotIn('5.png', retain.call_args.args[0])
            self.assertEqual(release.call_count, 2)

    def test_sense_loads_only_visible_covers_and_releases_distant_covers(self):
        rows = [SimpleNamespace(game={'id': str(i), 'square_cover': f'{i}.png'},
                image_loaded=False, button=Mock(), set_opacity=Mock(),
                get_allocation=lambda i=i: SimpleNamespace(x=i*120, y=0, width=104, height=104))
                for i in range(30)]
        for index, row in enumerate(rows):
            row.get_next_sibling = lambda i=index: rows[i+1] if i+1 < len(rows) else None
        adjustment = Mock()
        adjustment.get_value.return_value = 0
        adjustment.get_page_size.return_value = 1200
        host = SimpleNamespace(tiles=lambda: rows, selected_game='0', view_mode='ps5', settings={},
               flow=SimpleNamespace(get_first_child=lambda: rows[0], get_margin_start=lambda: 0),
               library_scroll=SimpleNamespace(get_hadjustment=lambda: adjustment), cover=Mock())
        with patch('estante.release_images'), patch('estante.Gtk.Box'), patch('estante.images.retain_paths'):
            Shelf.update_image_window(host)
            self.assertTrue(all(row.image_loaded for row in rows[:10]))
            self.assertFalse(rows[10].image_loaded)
            adjustment.get_value.return_value = 2400
            host.selected_game = '20'
            Shelf.update_image_window(host)
            self.assertFalse(rows[0].image_loaded)
            self.assertTrue(all(row.image_loaded for row in rows[20:]))


class VirtualStripImageTests(TestCase):
    def test_new_unallocated_cards_load_by_virtual_viewport_coordinates(self):
        from carousel import VirtualStrip
        indices = [37, *range(81, 100)]
        rows = [SimpleNamespace(model_index=i, game={'id': str(i), 'square_cover': f'{i}.png'},
                image_loaded=False, button=Mock(), set_opacity=Mock(),
                get_allocation=lambda: SimpleNamespace(x=0, y=0, width=0, height=0)) for i in indices]
        for index, row in enumerate(rows):
            row.get_next_sibling = lambda i=index: rows[i+1] if i+1 < len(rows) else None
        flow = Mock(spec=VirtualStrip)
        flow.get_first_child.return_value = rows[0]
        flow.get_margin_start.return_value = 126
        flow.position.side_effect = lambda index: index * 128 + (108 if index > 37 else 0)
        flow.item_width = 116
        adjustment = SimpleNamespace(get_value=lambda: 10746, get_page_size=lambda: 2560)
        host = SimpleNamespace(tiles=lambda: rows, selected_game='37', view_mode='ps5', settings={},
            flow=flow, library_scroll=SimpleNamespace(get_hadjustment=lambda: adjustment), cover=Mock())
        with patch('estante.release_images'), patch('estante.Gtk.Box'), patch('estante.images.retain_paths'):
            Shelf.update_image_window(host)
        self.assertFalse(rows[0].image_loaded)
        self.assertGreater(sum(row.image_loaded for row in rows), 10)
        self.assertTrue(all(row.image_loaded for row in rows if row.model_index >= 83))


class FocusResolutionTests(TestCase):
    def test_sense_selection_changes_resolution_without_replacing_pictures(self):
        pictures = [Mock(spec=Gtk.Picture) for _ in range(3)]
        rows = []
        for index, picture in enumerate(pictures):
            picture.image_ticket = SimpleNamespace(cancelled=False)
            target = Mock()
            target.get_child.return_value = picture
            rows.append(SimpleNamespace(game={'id': str(index), 'square_cover': f'{index}.png'},
                image_loaded=True, image_priority=0 if index==0 else 1, button=target,
                set_opacity=Mock(), get_allocation=lambda i=index: SimpleNamespace(
                    x=i*128, y=0, width=116, height=116)))
        for index, row in enumerate(rows):
            row.get_next_sibling = lambda i=index: rows[i+1] if i+1<len(rows) else None
        host = SimpleNamespace(tiles=lambda: rows, selected_game='1', view_mode='ps5', settings={},
            flow=SimpleNamespace(get_first_child=lambda: rows[0], get_margin_start=lambda: 0),
            library_scroll=SimpleNamespace(get_hadjustment=lambda: SimpleNamespace(
                get_value=lambda: 0, get_page_size=lambda: 1200)), request_picture=Mock())
        with patch('estante.images.retain_paths'):
            Shelf.update_image_window(host)
        self.assertEqual(host.request_picture.call_count, 2)
        calls = host.request_picture.call_args_list
        self.assertEqual([(item.args[1], item.args[4], item.kwargs['kind']) for item in calls],
                         [('0.png', 1, 'cover'), ('1.png', 0, 'cover')])
        for row in rows:
            row.button.set_child.assert_not_called()
        self.assertTrue(pictures[0].image_ticket.cancelled)
        self.assertTrue(pictures[1].image_ticket.cancelled)
