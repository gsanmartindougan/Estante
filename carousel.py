"""A horizontal wheel with one widget per game."""
import math
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gsk, Graphene, GLib


def wheel_position(index, phase, count, width):
    angle = (index - phase) * 2 * math.pi / max(1, count)
    depth = (math.cos(angle) + 1) / 2
    return math.sin(angle) * max(0, width / 2 - 150), -80 * (1 - depth), .55 + .45 * depth, depth


class CarouselWheel(Gtk.Widget):
    def __init__(self):
        super().__init__(hexpand=True, overflow=Gtk.Overflow.VISIBLE)
        self.phase = 0.0
        self.destination = 0.0
        self.animation = None
        self.depths = []
        self.add_tick_callback(self.layout_tick)

    def append(self, child):
        child.set_parent(self)

    def remove(self, child):
        self.depths = []
        child.unparent()

    def set_homogeneous(self, value):
        pass

    def set_spacing(self, value):
        pass

    def do_measure(self, orientation, for_size):
        return (0, 980, -1, -1) if orientation == Gtk.Orientation.HORIZONTAL else (0, 0, -1, -1)

    def children(self):
        rows = []
        child = self.get_first_child()
        while child:
            if child.get_visible():
                rows.append(child)
            child = child.get_next_sibling()
        return rows

    def select(self, child):
        rows = self.children()
        if child not in rows:
            return
        target = rows.index(child)
        count = len(rows)
        delta = (target - self.destination + count / 2) % count - count / 2
        self.destination += delta
        self.animation = (self.phase, self.destination, GLib.get_monotonic_time())

    def layout_tick(self, *_):
        if self.animation:
            start, target, started = self.animation
            progress = min(1, (GLib.get_monotonic_time() - started) / 280000)
            self.phase = start + (target - start) * (1 - (1 - progress) ** 3)
            if progress == 1:
                self.animation = None
            self.queue_allocate()
        return True

    def do_size_allocate(self, width, height, baseline):
        rows = self.children()
        self.depths = []
        for index, child in enumerate(rows):
            x, y, scale, depth = wheel_position(index, self.phase, len(rows), self.get_width())
            _, width, _, _ = child.measure(Gtk.Orientation.HORIZONTAL, -1)
            _, height, _, _ = child.measure(Gtk.Orientation.VERTICAL, width)
            transform = Gsk.Transform.new().translate(Graphene.Point().init(
                self.get_width()/2 + x - width*scale/2,
                self.get_height()/2 + y - height*scale/2)).scale(scale, scale)
            child.allocate(width, height, -1, transform)
            child.set_opacity(.45 + .55 * depth)
            self.depths.append((depth, index, child))
        self.queue_draw()

    def do_snapshot(self, snapshot):
        for _, _, child in sorted(self.depths, key=lambda item: (item[0], item[1])):
            self.snapshot_child(child, snapshot)
