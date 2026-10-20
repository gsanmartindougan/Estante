import json
import unittest
from appearance import cover_format_for, cover_size_for


class CoverFormatTests(unittest.TestCase):
    def test_defaults_preserve_existing_formats(self):
        self.assertEqual(cover_size_for({}, 'grid'), (156, 234))
        self.assertEqual(cover_size_for({}, 'carousel'), (192, 288))
        self.assertEqual(cover_size_for({}, 'ps5'), (104, 104))

    def test_formats_are_independent_and_keep_grid_zoom(self):
        settings = {'cover_formats': {'grid': 'square', 'ps5': 'portrait'}, 'grid_zoom': 150}
        self.assertEqual(cover_size_for(settings, 'grid'), (234, 234))
        self.assertEqual(cover_size_for(settings, 'ps5'), (104, 156))
        self.assertEqual(cover_format_for(settings, 'carousel'), 'portrait')
        settings['cover_formats']['carousel'] = 'square'
        self.assertEqual(cover_size_for(settings, 'carousel'), (192, 192))

from appearance import ring_for, with_ring, VIEW_NAMES, cover_radius_for, hero_position_for


class AppearanceTests(unittest.TestCase):
    def test_hero_positions_are_independent_with_legacy_fallback(self):
        settings = {'hero_position': 'lower', 'hero_positions': {'grid': 'top'}}
        self.assertEqual(hero_position_for(settings, 'grid'), 'top')
        self.assertEqual(hero_position_for(settings, 'ps5'), 'lower')
        self.assertEqual(hero_position_for({}, 'carousel'), 'top')
        self.assertEqual(hero_position_for({'hero_positions': {'ps5': 'full'}}, 'ps5'), 'full')

    def test_cover_rounding_is_per_view_and_can_be_disabled(self):
        settings = {'cover_radii': {'ps5': 20, 'grid': 0}}
        self.assertEqual(cover_radius_for(settings, 'grid'), 0)
        self.assertEqual(cover_radius_for(settings, 'ps5'), 20)
        self.assertEqual(cover_radius_for(settings, 'carousel'), 12)
        self.assertEqual(cover_radius_for({'cover_radii': {'grid': 100}}, 'grid'), 40)

    def test_legacy_global_values_are_preserved_for_each_view(self):
        old = {'focus_ring_color': '#ffb077', 'focus_ring_width': 6,
               'focus_ring_enabled': False, 'background_fill': 'dominant'}
        changed = with_ring(old, 'ps5', {'focus_ring_enabled': True, 'focus_ring_width': 2})
        for view in ('grid', 'carousel'):
            self.assertEqual(ring_for(changed, view)['focus_ring_width'], 6)
            self.assertFalse(ring_for(changed, view)['focus_ring_enabled'])
            self.assertEqual(ring_for(changed, view)['focus_ring_color'], '#ffb077')
        self.assertEqual(ring_for(changed, 'ps5')['focus_ring_width'], 2)
        self.assertTrue(ring_for(changed, 'ps5')['focus_ring_enabled'])
        self.assertNotIn('selection_rings', old)
        self.assertEqual(changed['background_fill'], 'dominant')

    def test_ring_isolation_survives_settings_round_trip(self):
        settings = with_ring({}, 'grid', {'focus_ring_color': '#ff0000', 'focus_ring_width': 1})
        settings = with_ring(settings, 'carousel', {'focus_ring_color': '#00ff00', 'focus_ring_width': 5})
        settings = with_ring(settings, 'ps5', {'focus_ring_enabled': False, 'focus_ring_radius': 0})
        settings = json.loads(json.dumps(settings))
        self.assertEqual(ring_for(settings, 'grid')['focus_ring_color'], '#ff0000')
        self.assertEqual(ring_for(settings, 'carousel')['focus_ring_color'], '#00ff00')
        self.assertTrue(ring_for(settings, 'carousel')['focus_ring_enabled'])
        self.assertFalse(ring_for(settings, 'ps5')['focus_ring_enabled'])
        self.assertEqual(ring_for(settings, 'ps5')['focus_ring_radius'], 0)
        self.assertEqual(VIEW_NAMES['ps5'], 'Sense')


class ListAppearanceTests(unittest.TestCase):
    def test_logo_size_is_independent_of_cover_format(self):
        self.assertIn('list', VIEW_NAMES)
        self.assertEqual(cover_size_for({}, 'list'), (300, 100))
        self.assertEqual(cover_size_for({'list_zoom': 150, 'cover_formats': {'list': 'square'}}, 'list'), (450, 150))
        self.assertEqual(cover_size_for({'list_zoom': 500}, 'list'), (600, 200))


class ListDetailCoverTests(unittest.TestCase):
    def test_size_preserves_aspect_ratio_and_is_independent_of_logos(self):
        from appearance import list_cover_size
        self.assertEqual(list_cover_size({'list_cover_zoom': 150, 'list_zoom': 50}), (270, 405))
        self.assertEqual(list_cover_size({'list_cover_zoom': 150, 'cover_formats': {'list': 'square'}}), (330, 330))
        self.assertEqual(list_cover_size({'list_cover_zoom': 1000}), (315, 472))
