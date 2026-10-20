from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from appearance import list_side_for, list_navigation
from carousel import list_coordinates
from estante import Shelf


class ListSidesTests(TestCase):
    def test_default_and_navigation_match_each_edge(self):
        self.assertEqual(list_side_for({}), 'left')
        self.assertEqual(list_side_for({'list_side': 'invalid'}), 'left')
        for side, directions, enter, leave in (
                ('left', ('up', 'down'), 'right', 'left'),
                ('right', ('up', 'down'), 'left', 'right'),
                ('top', ('left', 'right'), 'down', 'up'),
                ('bottom', ('left', 'right'), 'up', 'down')):
            self.assertEqual(list_navigation({'list_side': side}), (directions, enter, leave))

    def test_selected_logo_is_centered_on_its_edge_and_other_logos_follow_axis(self):
        left = list_coordinates(0, 0, 3, 1000, 800, 300, 100, 1.5, 'left')
        right = list_coordinates(0, 0, 3, 1000, 800, 300, 100, 1.5, 'right')
        self.assertAlmostEqual(left[0] + right[0], 1000)
        self.assertEqual(left[1], 400)
        self.assertEqual(right[1], 400)
        top = list_coordinates(0, 0, 3, 1000, 800, 300, 100, 1.5, 'top')
        bottom = list_coordinates(0, 0, 3, 1000, 800, 300, 100, 1.5, 'bottom')
        self.assertEqual(top[0], 500)
        self.assertEqual(bottom[0], 500)
        self.assertAlmostEqual(top[1] + bottom[1], 800)
        for side in ('left', 'right', 'top', 'bottom'):
            before = list_coordinates(0, 1, 3, 1000, 800, 300, 100, 1.5, side)
            selected = list_coordinates(1, 1, 3, 1000, 800, 300, 100, 1.5, side)
            after = list_coordinates(2, 1, 3, 1000, 800, 300, 100, 1.5, side)
            axis = 0 if side in ('top', 'bottom') else 1
            self.assertLess(before[axis], selected[axis])
            self.assertLess(selected[axis], after[axis])
            self.assertEqual(selected[2:], (1.5, 1))

    def test_controller_cycles_and_enters_details_from_each_side(self):
        for side in ('left', 'right', 'top', 'bottom'):
            tiles = [object(), object(), object()]
            play = Mock()
            host = SimpleNamespace(view_mode='list', settings={'list_side': side},
                pages=SimpleNamespace(get_visible_child_name=lambda: 'library'),
                drawer=SimpleNamespace(get_reveal_child=lambda: False), get_focus=lambda: None,
                stack=SimpleNamespace(get_visible_child_name=lambda: 'games'),
                tiles=lambda: tiles, selected_tile=lambda: tiles[0], select_tile=Mock(),
                game_actions=SimpleNamespace(get_first_child=lambda: play))
            directions, enter, _ = list_navigation(host.settings)
            Shelf.navigate(host, directions[0])
            host.select_tile.assert_called_with(tiles[-1])
            Shelf.navigate(host, directions[1])
            host.select_tile.assert_called_with(tiles[1])
            Shelf.navigate(host, enter)
            play.grab_focus.assert_called_once()

    def test_neighbour_logos_do_not_enter_focused_capsule(self):
        for side in ('left', 'right', 'top', 'bottom'):
            for count in (2, 3, 5, 13, 30):
                for zoom in (1, 1.5, 2.5):
                    width, height, item_width, item_height = 2048, 900, 300, 100
                    center = list_coordinates(0, 0, count, width, height, item_width, item_height, zoom, side)
                    horizontal = side in ('top', 'bottom')
                    axis = 0 if horizontal else 1
                    extent = item_width if horizontal else item_height
                    padding = 24 if horizontal else 16
                    for index in (1, count-1):
                        other = list_coordinates(index, 0, count, width, height, item_width, item_height, zoom, side)
                        # A two-game library has only one neighbour.
                        if other[3] <= .5:
                            continue
                        distance = abs(other[axis] - center[axis])
                        minimum = extent * zoom / 2 + padding + extent * other[2] / 2
                        self.assertGreaterEqual(distance + .0001, minimum + 16)
