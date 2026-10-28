import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

from estante import BlurredBackdrop, TopAlignedPicture, Gdk, GLib


def solid_texture(red, green, blue, alpha=255):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes((0, red, green, blue, alpha)))) + chunk(b'IEND', b''))
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))


class BackgroundTests(unittest.TestCase):
    def test_color_reuses_texture_without_reading_image_again(self):
        texture = solid_texture(255, 176, 119)
        with patch('estante.Gdk.Texture.new_from_filename', side_effect=AssertionError('No second decode')):
            color = BlurredBackdrop.dominant_color('/nonexistent/hero.png', texture)
        self.assertAlmostEqual(color.red, 1, places=2)
        self.assertAlmostEqual(color.green, 176 / 255, places=2)
        self.assertAlmostEqual(color.blue, 119 / 255, places=2)

    def test_transparent_pixels_have_neutral_fallback(self):
        color = BlurredBackdrop.dominant_color('', solid_texture(255, 0, 0, 0))
        self.assertAlmostEqual(color.red, 32 / 255, places=2)
        self.assertAlmostEqual(color.green, 32 / 255, places=2)

    def test_sampling_failure_preserves_background_texture(self):
        texture = solid_texture(255, 176, 119)
        for mode in ('blur', 'dominant'):
            backdrop = SimpleNamespace(colors={}, color=None, texture=None, mode=mode,
                                       dominant_color=Mock(side_effect=GLib.Error('sampling failed')),
                                       queue_draw=Mock())
            BlurredBackdrop.set_texture(backdrop, texture, '/hero.png')
            self.assertIs(backdrop.texture, texture)
            self.assertIsNotNone(backdrop.color)
            backdrop.queue_draw.assert_called_once()


class BackgroundEffectSnapshotTests(unittest.TestCase):
    def test_blur_wraps_entire_background_and_zero_avoids_blur_node(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        for radius in (0, 18):
            snapshot = Mock()
            host = SimpleNamespace(blur=radius, snapshot_background=Mock())
            with patch('estante.blur_radius', side_effect=lambda value: value):
                TopAlignedPicture.do_snapshot(host, snapshot)
            host.snapshot_background.assert_called_once_with(snapshot)
            self.assertEqual(snapshot.push_blur.call_count, int(radius > 0))
            self.assertEqual(snapshot.pop.call_count, int(radius > 0))
