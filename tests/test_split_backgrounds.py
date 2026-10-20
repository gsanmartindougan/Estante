import unittest
import cairo
from gi.repository import Gdk, GLib, Gtk
from backgrounds import background_split_for, crop_bounds, paint_hero_pair


def texture(red, green, blue):
    return Gdk.MemoryTexture.new(1, 1, Gdk.MemoryFormat.R8G8B8A8,
                                 GLib.Bytes.new(bytes((red, green, blue, 255))), 4)


def render(mode, position='full'):
    snapshot = Gtk.Snapshot.new()
    paint_hero_pair(snapshot, (texture(255, 0, 0), texture(0, 0, 255)), 120, 80, position, mode)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
    snapshot.to_node().draw(cairo.Context(surface))
    surface.flush()
    return surface


def pixel(surface, x, y):
    offset = y * surface.get_stride() + x * 4
    blue, green, red, alpha = surface.get_data()[offset:offset + 4]
    return red, green, blue, alpha


class SplitBackgroundTests(unittest.TestCase):
    def test_each_layout_stores_its_own_split_with_single_default(self):
        settings = {'background_splits': {'grid': 'vertical', 'carousel': 'diagonal'}}
        self.assertEqual(background_split_for(settings, 'grid'), 'vertical')
        self.assertEqual(background_split_for(settings, 'carousel'), 'diagonal')
        self.assertEqual(background_split_for(settings, 'ps5'), 'single')
        self.assertEqual(background_split_for({'background_splits': {'grid': 'bad'}}, 'grid'), 'single')

    def test_vertical_draws_each_image_on_its_side(self):
        surface = render('vertical')
        self.assertEqual(pixel(surface, 15, 40), (255, 0, 0, 255))
        self.assertEqual(pixel(surface, 105, 40), (0, 0, 255, 255))

    def test_horizontal_draws_each_image_in_its_half(self):
        surface = render('horizontal')
        self.assertEqual(pixel(surface, 60, 10), (255, 0, 0, 255))
        self.assertEqual(pixel(surface, 60, 70), (0, 0, 255, 255))

    def test_diagonal_follows_corners_on_non_square_canvas(self):
        surface = render('diagonal')
        self.assertEqual(pixel(surface, 10, 10), (255, 0, 0, 255))
        self.assertEqual(pixel(surface, 110, 70), (0, 0, 255, 255))
        self.assertEqual(pixel(surface, 100, 5), (255, 0, 0, 255))
        self.assertEqual(pixel(surface, 20, 75), (0, 0, 255, 255))

    def test_single_mode_keeps_only_first_image(self):
        surface = render('single')
        self.assertEqual(pixel(surface, 15, 40), (255, 0, 0, 255))
        self.assertEqual(pixel(surface, 105, 40), (255, 0, 0, 255))

    def test_seam_blends_both_images_without_a_transparent_gap(self):
        for mode in ('horizontal', 'vertical', 'diagonal'):
            with self.subTest(mode=mode):
                surface = render(mode)
                red, green, blue, alpha = pixel(surface, 60, 40)
                self.assertGreater(red, 30)
                self.assertGreater(blue, 30)
                self.assertEqual(green, 0)
                self.assertEqual(alpha, 255)
                self.assertAlmostEqual(red + blue, 255, delta=2)
                points = [(60, y) for y in range(36, 45)] if mode == 'horizontal' else [(x, 40) for x in range(56, 65)]
                reds = [pixel(surface, x, y)[0] for x, y in points]
                self.assertEqual(reds, sorted(reds, reverse=True))
                self.assertGreater(len(set(reds)), 3)
                for y in range(80):
                    for x in range(120):
                        self.assertEqual(pixel(surface, x, y)[3], 255)

    def test_crop_covers_region_without_distorting(self):
        image = Gdk.MemoryTexture.new(4, 2, Gdk.MemoryFormat.R8G8B8A8,
            GLib.Bytes.new(bytes((255, 0, 0, 255)) * 8), 16)
        bounds = crop_bounds(image, (60, 0, 60, 80))
        self.assertAlmostEqual(bounds.get_width() / bounds.get_height(), 2)
        self.assertLessEqual(bounds.get_x(), 60)
        self.assertGreaterEqual(bounds.get_x() + bounds.get_width(), 120)
        self.assertGreaterEqual(bounds.get_height(), 80)

    def test_panoramic_heroes_fill_whole_window_in_every_position(self):
        first = Gdk.MemoryTexture.new(4, 1, Gdk.MemoryFormat.R8G8B8A8,
            GLib.Bytes.new(bytes((255, 0, 0, 255)) * 4), 16)
        second = Gdk.MemoryTexture.new(8, 1, Gdk.MemoryFormat.R8G8B8A8,
            GLib.Bytes.new(bytes((0, 0, 255, 255)) * 8), 32)
        for position in ('top', 'lower', 'full'):
            for mode in ('horizontal', 'vertical', 'diagonal'):
                with self.subTest(position=position, mode=mode):
                    snapshot = Gtk.Snapshot.new()
                    paint_hero_pair(snapshot, (first, second), 120, 80, position, mode)
                    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
                    snapshot.to_node().draw(cairo.Context(surface))
                    surface.flush()
                    self.assertEqual(pixel(surface, 5, 5), (255, 0, 0, 255))
                    self.assertEqual(pixel(surface, 115, 75), (0, 0, 255, 255))
                    for y in (5, 35, 45, 75):
                        for x in (5, 55, 65, 115):
                            self.assertEqual(pixel(surface, x, y)[3], 255)
