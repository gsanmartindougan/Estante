import unittest
from settings_view import spatial_target


class SettingsNavigationTests(unittest.TestCase):
    def test_horizontal_navigation_uses_adjacent_column_at_similar_height(self):
        points = [(90, 228), (450, 255), (450, 340), (950, 215), (950, 300), (1120, 1375)]
        self.assertEqual(spatial_target(points, 1, 'right'), 3)
        self.assertEqual(spatial_target(points, 3, 'left'), 1)
        self.assertEqual(spatial_target(points, 2, 'right'), 4)
        self.assertEqual(spatial_target(points, 1, 'down'), 2)
        self.assertEqual(spatial_target(points, 1, 'left'), 0)

    def test_boundaries_do_not_jump_to_next_control_in_tree(self):
        points = [(100, 100), (100, 200)]
        self.assertEqual(spatial_target(points, 0, 'right'), 0)
        self.assertEqual(spatial_target(points, 0, 'up'), 0)
        self.assertEqual(spatial_target(points, 1, 'down'), 1)

    def test_expanded_sections_follow_visible_control_geometry(self):
        points = [(300, 100), (300, 160), (300, 205), (800, 100), (800, 190)]
        self.assertEqual(spatial_target(points, 2, 'right'), 4)
        self.assertEqual(spatial_target(points, 1, 'up'), 0)
        self.assertEqual(spatial_target(points, 3, 'left'), 0)

    def test_trailing_switch_uses_labelled_row_for_directional_navigation(self):
        from unittest.mock import Mock, patch
        from settings_view import navigation_bounds
        class Row:
            compute_bounds = Mock(return_value=(True, 'row-bounds'))
        class Switch:
            def get_parent(self):
                return row
        row = Row()
        switch = Switch()
        with patch('settings_view.Gtk.Switch', Switch), patch('settings_view.Gtk.Box', Row):
            self.assertEqual(navigation_bounds(switch, 'page'), (True, 'row-bounds'))
        # The switch shares its row's centre with the full-width section header.
        points = [(300, 65), (300, 110), (300, 150), (300, 240)]
        self.assertEqual(spatial_target(points, 0, 'down'), 1)
        self.assertEqual(spatial_target(points, 1, 'down'), 2)
        self.assertEqual(spatial_target(points, 2, 'up'), 1)
