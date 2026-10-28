from unittest import TestCase
from unittest.mock import Mock, patch
from gi.repository import Gio, GLib
from tray import TrayIcon, XML, PROPERTIES, icon_pixmap
from tempfile import TemporaryDirectory
from pathlib import Path


class TrayTests(TestCase):
    def test_exported_properties_match_dbus_signatures(self):
        icon = TrayIcon(Mock())
        interfaces = Gio.DBusNodeInfo.new_for_xml(XML).interfaces
        self.assertEqual(len(interfaces), 2)
        for interface in interfaces:
            for prop in interface.properties:
                value = icon.property(None, None, None, interface.name, prop.name)
                self.assertEqual(value.get_type_string(), prop.signature)
        self.assertEqual(icon.property(None, None, None, '', 'ItemIsMenu').unpack(), False)

    def test_window_is_not_hidden_until_watcher_and_host_confirm_registration(self):
        connection, done = Mock(), Mock()
        connection.register_object.side_effect = [1, 2]
        icon = TrayIcon(Mock())
        with patch('tray.Gio.bus_get_sync', return_value=connection), patch('tray.Gio.bus_own_name_on_connection', return_value=10):
            icon.show(done)
        done.assert_not_called()
        icon.acquired(connection, icon.name)
        self.assertEqual(connection.call.call_args.args[3], 'RegisterStatusNotifierItem')
        connection.call_finish.return_value = None
        connection.call.call_args.args[-1](connection, object())
        done.assert_not_called()
        self.assertEqual(connection.call.call_args.args[3], 'Get')
        connection.call_finish.return_value = GLib.Variant('(v)', (GLib.Variant('b', True),))
        connection.call.call_args.args[-1](connection, object())
        done.assert_called_once_with(True)
        self.assertTrue(icon.ready)
        with patch('tray.Gio.bus_unown_name') as unown:
            icon.hide()
        unown.assert_called_once_with(10)
        self.assertEqual(connection.unregister_object.call_count, 2)
        self.assertFalse(icon.ready)

    def test_host_absent_keeps_window_available(self):
        icon = TrayIcon(Mock())
        icon.connection = connection = Mock()
        icon.callbacks = [done := Mock()]
        icon.register(0, icon.revision)
        connection.call_finish.return_value = None
        connection.call.call_args.args[-1](connection, object())
        connection.call_finish.return_value = GLib.Variant('(v)', (GLib.Variant('b', False),))
        connection.call.call_args.args[-1](connection, object())
        done.assert_called_once_with(False)
        self.assertFalse(icon.ready)

    def test_watcher_fallback_and_late_reply_after_cancel(self):
        icon = TrayIcon(Mock())
        icon.connection = connection = Mock()
        icon.callbacks = [done := Mock()]
        icon.register(0, icon.revision)
        connection.call_finish.side_effect = GLib.Error('missing watcher')
        connection.call.call_args.args[-1](connection, object())
        self.assertEqual(connection.call.call_args.args[0], 'org.freedesktop.StatusNotifierWatcher')
        late = connection.call.call_args.args[-1]
        icon.hide()
        late(connection, object())
        done.assert_called_once_with(False)

    def test_tray_click_restores_application(self):
        activate, invocation = Mock(), Mock()
        icon = TrayIcon(activate)
        icon.method(None, None, None, '', 'Activate', None, invocation)
        activate.assert_called_once()
        invocation.return_value.assert_called_once_with(None)

    def test_icon_fallback_uses_network_order_argb(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'icon.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="red"/></svg>')
            [(width, height, pixels)] = icon_pixmap(path)
        self.assertEqual((width, height), (32, 32))
        self.assertEqual(len(pixels), 32 * 32 * 4)
        self.assertEqual(pixels[:4], bytes([255, 255, 0, 0]))
