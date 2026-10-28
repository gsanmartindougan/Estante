import unittest
from carousel import wheel_position, list_position, list_opacity, list_anchor, CarouselWheel
from types import SimpleNamespace


class WheelTests(unittest.TestCase):
    def test_three_games_have_distinct_circular_positions(self):
        points = [wheel_position(i, 0, 3, 1200) for i in range(3)]
        self.assertEqual(len({(round(x), round(y)) for x, y, _, _ in points}), 3)
        self.assertEqual(points[0], (0, 0, 1, 1))
        self.assertGreater(points[1][0], 0)
        self.assertLess(points[2][0], 0)
        self.assertLess(points[1][2], 1)
        for index in range(3):
            for first, second in zip(wheel_position(index, 0, 3, 1200), wheel_position(index, 3, 3, 1200)):
                self.assertAlmostEqual(first, second)

    def test_wrap_rotates_one_position_without_copies(self):
        rows = [object(), object(), object()]
        wheel = SimpleNamespace(children=lambda: rows, animation_tick=None, add_tick_callback=lambda callback: 1, layout_tick=lambda *_: False, destination=2., phase=2.)
        CarouselWheel.select(wheel, rows[0])
        self.assertEqual(wheel.destination, 3)
        wheel.destination = wheel.phase = 0.
        CarouselWheel.select(wheel, rows[2])
        self.assertEqual(wheel.destination, -1)

    def test_vertical_list_centers_selection_and_wraps_without_copies(self):
        for count in (1, 2, 3, 12):
            points = [list_position(index, 0, count, 700, 100) for index in range(count)]
            self.assertEqual(points[0], (0, 0, 1.5, 1))
            if count > 1:
                self.assertGreater(points[0][2], max(point[2] for point in points[1:]))
            if count <= 5:
                self.assertEqual(len({(round(point[0], 6), round(point[1], 6)) for point in points}), count)
            else:
                self.assertEqual(sum(list_opacity(point[3]) > .01 for point in points), 3)
            for index in range(count):
                for actual, expected in zip(list_position(index, 0, count, 700, 100),
                                            list_position(index, count, count, 700, 100)):
                    self.assertAlmostEqual(actual, expected)
        self.assertLess(list_position(0, 1, 5, 700, 100)[1], 0)
        self.assertGreater(list_position(2, 1, 5, 700, 100)[1], 0)

    def test_vertical_wheel_has_depth_and_no_wrap_discontinuity(self):
        front = list_position(0, 0, 12, 800, 100)
        back = list_position(6, 0, 12, 800, 100)
        self.assertLess(back[0], front[0])
        self.assertLess(back[2], front[2])
        self.assertLess(back[3], front[3])
        for phase in (0, 6, 12):
            before = list_position(0, phase - .00001, 12, 800, 100)
            after = list_position(0, phase + .00001, 12, 800, 100)
            for first, second in zip(before, after):
                self.assertLess(abs(first - second), .01)

    def test_only_front_semicircle_is_visible_and_selected_logo_hugs_edge(self):
        for index in range(12):
            _, _, _, depth = list_position(index, 0, 12, 800, 100)
            opacity = list_opacity(depth)
            if index in (4, 5, 6, 7, 8):
                self.assertEqual(opacity, 0)
        self.assertEqual(list_opacity(1), 1)
        self.assertEqual(list_opacity(.5), 0)
        self.assertGreater(list_opacity(.75), 0)
        self.assertAlmostEqual(list_anchor(1000, 300) - 300 * 1.5 / 2, 24)

    def test_focused_logo_size_is_configurable_without_changing_other_logos(self):
        for zoom in (1, 1.5, 2.5):
            self.assertAlmostEqual(list_position(0, 0, 12, 800, 100, focus_scale=zoom)[2], zoom)
            self.assertAlmostEqual(list_anchor(1200, 300, zoom) - 300 * zoom / 2, 24)
        small = list_position(1, 0, 12, 800, 100, focus_scale=1)
        large = list_position(1, 0, 12, 800, 100, focus_scale=2.5)
        self.assertAlmostEqual(small[0], large[0])
        self.assertAlmostEqual(small[1], large[1])

    def test_small_libraries_show_neighbours_without_duplicates(self):
        for count in (2, 3, 4, 5):
            for selected in range(count):
                points = [list_position(index, selected, count, 800, 100) for index in range(count)]
                self.assertEqual(len({(round(x, 5), round(y, 5)) for x, y, _, _ in points}), count)
                self.assertTrue(all(list_opacity(depth) > .1 for _, _, _, depth in points))
                self.assertEqual(points[selected][:2], (0, 0))
        positions = [list_position(i, 1, 3, 800, 100)[1] for i in range(3)]
        self.assertLess(positions[0], 0)
        self.assertGreater(positions[2], 0)
