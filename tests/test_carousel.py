import unittest
from carousel import wheel_position, CarouselWheel
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
        wheel = SimpleNamespace(children=lambda: rows, destination=2., phase=2.)
        CarouselWheel.select(wheel, rows[0])
        self.assertEqual(wheel.destination, 3)
        wheel.destination = wheel.phase = 0.
        CarouselWheel.select(wheel, rows[2])
        self.assertEqual(wheel.destination, -1)
