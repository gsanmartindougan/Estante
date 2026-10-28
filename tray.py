"""Small StatusNotifierItem implementation using the existing Gio dependency."""
import os
import sys
from pathlib import Path
from gi.repository import Gio, GLib
from i18n import tr

APP_ID = 'io.github.estante.Launcher'
PATH = '/StatusNotifierItem'
WATCHERS = ('org.kde.StatusNotifierWatcher', 'org.freedesktop.StatusNotifierWatcher')
PROPERTIES = {'Category': 's', 'Id': 's', 'Title': 's', 'Status': 's', 'WindowId': 'u',
              'IconName': 's', 'IconThemePath': 's', 'IconPixmap': 'a(iiay)',
              'OverlayIconName': 's', 'OverlayIconPixmap': 'a(iiay)',
              'AttentionIconName': 's', 'AttentionIconPixmap': 'a(iiay)',
              'AttentionMovieName': 's', 'ToolTip': '(sa(iiay)ss)', 'ItemIsMenu': 'b', 'Menu': 'o'}
METHODS = '''<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>'''
XML = '<node>' + ''.join('<interface name="' + interface + '">' + METHODS + ''.join(
    '<property name="' + key + '" type="' + kind + '" access="read"/>'
    for key, kind in PROPERTIES.items()) + '</interface>' for interface in
    ('org.kde.StatusNotifierItem', 'org.freedesktop.StatusNotifierItem')) + '</node>'


def icon_pixmap(path, size=32):
    """Export a small network-order ARGB fallback for hosts without our icon theme."""
    import cairo
    import gi
    gi.require_version('Rsvg', '2.0')
    from gi.repository import Rsvg
    handle = Rsvg.Handle.new_from_data(path.read_bytes())
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    viewport = Rsvg.Rectangle()
    viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, size, size
    handle.render_document(cairo.Context(surface), viewport)
    surface.flush()
    data = surface.get_data()
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            offset = y * surface.get_stride() + x * 4
            value = int.from_bytes(data[offset:offset + 4], sys.byteorder)
            alpha = value >> 24
            rgb = [(value >> shift) & 255 for shift in (16, 8, 0)]
            pixels.extend([alpha, *[min(255, round(c * 255 / alpha)) if alpha else 0 for c in rgb]])
    return [(size, size, bytes(pixels))]


class TrayIcon:
    def __init__(self, activate):
        self.activate = activate
        self.connection = None
        self.objects = []
        self.name_id = None
        self.ready = False
        self.pixmaps = None
        self.revision = 0
        self.callbacks = []
        self.name = 'org.kde.StatusNotifierItem-' + str(os.getpid()) + '-1'

    def show(self, done):
        if self.ready:
            done(True)
            return
        self.callbacks.append(done)
        if self.name_id:
            return
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            for interface in Gio.DBusNodeInfo.new_for_xml(XML).interfaces:
                self.objects.append(self.connection.register_object(PATH, interface, self.method, self.property, None))
            self.name_id = Gio.bus_own_name_on_connection(self.connection, self.name,
                Gio.BusNameOwnerFlags.NONE, self.acquired, self.lost)
        except GLib.Error:
            self.hide()

    def acquired(self, connection, name):
        self.register(0, self.revision)

    def lost(self, *_):
        self.hide()

    def register(self, index, revision):
        if revision != self.revision:
            return
        if index == len(WATCHERS):
            self.hide()
            return
        service = WATCHERS[index]
        def registered(connection, result):
            if revision != self.revision:
                return
            try:
                connection.call_finish(result)
            except GLib.Error:
                self.register(index + 1, revision)
                return
            # A watcher without a visualization host must not make a window vanish.
            def host_ready(connection, result):
                if revision != self.revision:
                    return
                try:
                    available = bool(connection.call_finish(result).unpack()[0])
                except GLib.Error:
                    available = False
                if not available:
                    self.hide()
                    return
                self.ready = True
                callbacks, self.callbacks = self.callbacks, []
                for callback in callbacks:
                    callback(True)
            connection.call(service, '/StatusNotifierWatcher', 'org.freedesktop.DBus.Properties',
                'Get', GLib.Variant('(ss)', (service, 'IsStatusNotifierHostRegistered')),
                GLib.VariantType.new('(v)'), Gio.DBusCallFlags.NONE, 2000, None, host_ready)
        self.connection.call(service, '/StatusNotifierWatcher', service, 'RegisterStatusNotifierItem',
            GLib.Variant('(s)', (self.name,)), None, Gio.DBusCallFlags.NONE, 2000, None, registered)

    def property(self, connection, sender, path, interface, key):
        icon_dirs = [Path(os.environ.get('ESTANTE_APPDIR', '/nonexistent')),
                     Path(__file__).resolve().parent / 'packaging',
                     Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'icons/hicolor/scalable/apps']
        directory = next((str(path) for path in icon_dirs if (path / (APP_ID + '.svg')).is_file()), '')
        values = {'Category': 'ApplicationStatus', 'Id': 'estante', 'Title': 'Estante',
                  'Status': 'Active', 'WindowId': 0, 'IconName': APP_ID,
                  'IconThemePath': directory, 'ToolTip': (APP_ID, [], 'Estante', tr('Mostrar Estante')),
                  'ItemIsMenu': False, 'Menu': '/'}
        if key == 'IconPixmap':
            if self.pixmaps is None:
                try:
                    self.pixmaps = icon_pixmap(Path(directory) / (APP_ID + '.svg')) if directory else []
                except (ImportError, ValueError, OSError, GLib.Error):
                    self.pixmaps = []
            values['IconPixmap'] = self.pixmaps
        kind = PROPERTIES[key]
        return GLib.Variant(kind, values.get(key, [] if kind.startswith('a') else ''))

    def method(self, connection, sender, path, interface, method, parameters, invocation):
        if method in ('Activate', 'SecondaryActivate', 'ContextMenu'):
            self.activate()
        invocation.return_value(None)

    def hide(self):
        self.revision += 1
        self.ready = False
        if self.name_id:
            name_id, self.name_id = self.name_id, None
            Gio.bus_unown_name(name_id)
        if self.connection:
            for identity in self.objects:
                self.connection.unregister_object(identity)
        self.objects = []
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            callback(False)
