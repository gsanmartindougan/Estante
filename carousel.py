"""A horizontal wheel with one widget per game."""
from profiling import timed
import math
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gsk, Graphene, GLib


def wheel_position(index, phase, count, width):
    angle = (index - phase) * 2 * math.pi / max(1, count)
    depth = (math.cos(angle) + 1) / 2
    return math.sin(angle) * max(0, width / 2 - 150), -80 * (1 - depth), .55 + .45 * depth, depth


def list_position(index, phase, count, height, item_height, width=600, focus_scale=1.5):
    # Small libraries share the visible arc instead of hiding every neighbour behind it.
    if 1 < count <= 5:
        boundary = count // 2 + .5
        offset = (index - phase + boundary) % count - boundary
        angle = offset * math.pi / (2 * (count // 2 + 1))
        fade = min(1, max(0, min(offset + boundary, count - boundary - offset) / .2))
        depth = (.5 + .5 * math.cos(angle)) * fade
        emphasis = math.exp(-2 * offset ** 2)
        radius = max(0, height / 2 - item_height * .8 - 20)
        return (-min(180, width * .28) * (1 - math.cos(angle)),
                math.sin(angle) * radius,
                .45 + .35 * (.5 + .5 * math.cos(angle)) + (focus_scale - .8) * emphasis,
                depth)
    # A continuous ellipse: the front is centered, the rear recedes to the left.
    angle = (index - phase) * 2 * math.pi / max(1, count)
    depth = (math.cos(angle) + 1) / 2
    emphasis = math.exp(-2 * (math.sin(angle / 2) * count / math.pi) ** 2)
    horizontal_radius = min(180, width * .28)
    vertical_radius = max(0, height / 2 - item_height * .8 - 20)
    return (-horizontal_radius * (1 - depth), math.sin(angle) * vertical_radius,
            .45 + .35 * depth + (focus_scale - .8) * emphasis, depth)


def list_opacity(depth):
    # Only the front semicircle is visible; fade at its two ends.
    return max(0, 2 * depth - 1) ** .65


def list_anchor(width, item_width, focus_scale=1.5):
    return min(width / 2, 24 + item_width * focus_scale / 2)


def list_coordinates(index, phase, count, width, height, item_width, item_height, focus_scale, side):
    horizontal = side in ('top', 'bottom')
    x, y, scale, depth = list_position(index, phase, count,
        width if horizontal else height, item_width if horizontal else item_height,
        height if horizontal else width, focus_scale)
    # Reserve the selected capsule plus half of its neighbour and a small gap.
    # Apply the same extra arc spacing to farther logos so their order is retained.
    if count > 1:
        _, neighbour_y, neighbour_scale, _ = list_position(phase + 1, phase, count,
            width if horizontal else height, item_width if horizontal else item_height,
            height if horizontal else width, focus_scale)
        extent = item_width if horizontal else item_height
        padding = 24 if horizontal else 16
        required = extent * (focus_scale + neighbour_scale) / 2 + padding + 16
        extra = max(0, required - abs(neighbour_y))
        offset = (index - phase + count / 2) % count - count / 2
        weight = min(1, abs(offset))
        weight = weight * weight * (3 - 2 * weight)
        if abs(y) > .000001:
            y += math.copysign(extra * weight, y)
    if horizontal:
        anchor = list_anchor(height, item_height, focus_scale)
        return width/2 + y, (height - anchor - x if side == 'bottom' else anchor + x), scale, depth
    anchor = list_anchor(width, item_width, focus_scale)
    return (width - anchor - x if side == 'right' else anchor + x), height/2 + y, scale, depth


class CarouselWheel(Gtk.Widget):
    def __init__(self, vertical=False):
        super().__init__(hexpand=True, overflow=Gtk.Overflow.VISIBLE)
        self.vertical = vertical
        self.focus_scale = 1.5
        self.list_side = 'left'
        self.paint_focus_band = None
        self.phase = 0.0
        self.destination = 0.0
        self.animation = None
        self.depths = []
        self.animation_tick = None

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
        if self.vertical and self.list_side in ('top', 'bottom'):
            return (0, 980 if orientation == Gtk.Orientation.HORIZONTAL else 240, -1, -1)
        if self.vertical:
            return (0, 360 if orientation == Gtk.Orientation.HORIZONTAL else 600, -1, -1)
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
        if abs(delta) < 0.000001:
            return
        self.destination += delta
        self.animation = (self.phase, self.destination, GLib.get_monotonic_time())
        if self.animation_tick is None:
            self.animation_tick = self.add_tick_callback(self.layout_tick)

    def layout_tick(self, *_):
        if self.animation:
            start, target, started = self.animation
            progress = min(1, (GLib.get_monotonic_time() - started) / 280000)
            self.phase = start + (target - start) * (1 - (1 - progress) ** 3)
            if progress == 1:
                self.animation = None
            self.queue_allocate()
        if self.animation is None:
            self.animation_tick = None
            return False
        return True

    @timed('ui.wheel_layout')
    def do_size_allocate(self, width, height, baseline):
        rows = self.children()
        self.depths = []
        for index, child in enumerate(rows):
            x, y, scale, depth = wheel_position(index, self.phase, len(rows), self.get_width())
            _, width, _, _ = child.measure(Gtk.Orientation.HORIZONTAL, -1)
            _, height, _, _ = child.measure(Gtk.Orientation.VERTICAL, width)
            center_x, center_y = self.get_width()/2 + x, self.get_height()/2 + y - min(24, self.get_height() * .04)
            if self.vertical:
                center_x, center_y, scale, depth = list_coordinates(index, self.phase, len(rows),
                    self.get_width(), self.get_height(), width, height, self.focus_scale, self.list_side)
            transform = Gsk.Transform.new().translate(Graphene.Point().init(
                center_x - width*scale/2, center_y - height*scale/2)).scale(scale, scale)
            child.allocate(width, height, -1, transform)
            opacity = list_opacity(depth) if self.vertical else .45 + .55 * depth
            child.set_opacity(opacity if getattr(child, 'image_loaded', True) else 0)
            if self.vertical:
                child.set_can_target(opacity > .01)
            self.depths.append((depth, index, child))
        self.queue_draw()

    @timed('ui.wheel_snapshot')
    def do_snapshot(self, snapshot):
        if self.vertical and self.children() and self.paint_focus_band:
            self.paint_focus_band(snapshot)
        for _, _, child in sorted(self.depths, key=lambda item: (item[0], item[1])):
            self.snapshot_child(child, snapshot)
