from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from estante import Shelf, SquarePicture, RoundedPicture, Gtk


class LogoScalingTests(TestCase):
    def test_logo_uses_fixed_logical_dimensions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'logo.png'
            path.touch()
            texture = Mock()
            with patch('estante.images.load', return_value=texture), \
                 patch('estante.SquarePicture') as picture:
                Shelf.logo_image(SimpleNamespace(request_picture=lambda picture, *args, **kwargs: picture), {'logo': str(path)}, 300, 100)
            picture.assert_called_once_with(None, 300, 100, radius=0)
        logical = SimpleNamespace(cover_width=300, cover_height=100)
        self.assertEqual(SquarePicture.do_measure(logical, Gtk.Orientation.HORIZONTAL, -1), (300, 300, -1, -1))
        self.assertEqual(SquarePicture.do_measure(logical, Gtk.Orientation.VERTICAL, 300), (100, 100, -1, -1))

    def test_wide_and_tall_logos_fit_without_cropping_or_stretching(self):
        for width, height, expected in ((3000, 500, (0, 25, 300, 50)),
                                        (500, 2000, (137.5, 0, 25, 100))):
            texture = SimpleNamespace(get_width=lambda: width, get_height=lambda: height)
            image = SimpleNamespace(get_paintable=lambda: texture, get_width=lambda: 300,
                                    get_height=lambda: 100, corner_radius=0,
                                    get_content_fit=lambda: Gtk.ContentFit.CONTAIN)
            snapshot = Mock()
            RoundedPicture.do_snapshot(image, snapshot)
            bounds = snapshot.append_texture.call_args.args[1]
            actual = bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()
            for result, target in zip(actual, expected):
                self.assertAlmostEqual(result, target)

    def test_focus_band_blurs_only_background_layers(self):
        from estante import Graphene
        snapshot = Mock()
        scene = Mock()
        wheel = SimpleNamespace(focus_scale=1.5, get_width=lambda: 700,
                                get_height=lambda: 800,
                                compute_bounds=lambda _: (True, Graphene.Rect().init(16, 40, 700, 800)))
        shelf = SimpleNamespace(list_flow=wheel, settings={}, scene=scene,
                                backdrop_fill=object(), backdrop=object())
        Shelf.paint_list_focus_band(shelf, snapshot)
        snapshot.push_rounded_clip.assert_called_once()
        snapshot.push_blur.assert_called_once_with(18)
        self.assertEqual(scene.snapshot_child.call_count, 2)
        bounds = snapshot.append_color.call_args.args[1]
        self.assertLess(bounds.get_x(), 0)
        self.assertAlmostEqual(bounds.get_y() + bounds.get_height()/2, 400)

    def test_contained_image_rounds_actual_pixels_in_wider_allocation(self):
        texture = SimpleNamespace(get_width=lambda: 100, get_height=lambda: 100)
        picture = SimpleNamespace(get_paintable=lambda: texture, get_width=lambda: 300,
                                  get_height=lambda: 100, corner_radius=16,
                                  get_content_fit=lambda: Gtk.ContentFit.CONTAIN)
        snapshot = Mock()
        RoundedPicture.do_snapshot(picture, snapshot)
        bounds = snapshot.push_rounded_clip.call_args.args[0].bounds
        self.assertEqual((bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()),
                         (100, 0, 100, 100))
