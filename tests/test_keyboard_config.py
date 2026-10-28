import unittest
from qt_app.keyboard_config import provider,cosmic_connection_supported
from qt_app.settings_schema import groups,merge_values

class KeyboardConfigTests(unittest.TestCase):
    def test_desktop_choice_and_installed_fallback(self):
        self.assertEqual(provider(desktop='COSMIC',cosmic=True,kde=True,wayland=True),'cosmic')
        self.assertEqual(provider(desktop='KDE',cosmic=True,kde=True,wayland=True),'kde')
        self.assertEqual(provider(desktop='mango',cosmic=True,wayland=True),'cosmic')
        self.assertEqual(provider(desktop='mango',cosmic=True,wayland=False),'system')
        self.assertEqual(provider(),'system')
    def test_explicit_choice_is_not_silently_replaced(self):
        for mode in ('system','cosmic','kde','builtin','disabled'):
            self.assertEqual(provider(mode,kde=True,cosmic=True,wayland=True),mode)
        self.assertEqual(provider('unexpected'),'system')
    def test_settings_roundtrip_preserves_other_settings(self):
        settings={'plugin':'preserved'}
        result=merge_values(settings,[{'path':['onscreen_keyboard'],'value':'cosmic'}])
        self.assertEqual(result,{'plugin':'preserved','onscreen_keyboard':'cosmic'})
        self.assertEqual(settings,{'plugin':'preserved'})
        cards=groups(result)
        keyboard=next(card for card in cards if card.get('keyboard'))
        self.assertEqual(keyboard['rows'][0]['value'],'cosmic')
        with self.assertRaises(ValueError):merge_values(settings,[{'path':['onscreen_keyboard'],'value':'shell command'}])


class CosmicCompatibilityTests(unittest.TestCase):
    def test_wlr_portal_without_remote_desktop_is_not_compatible(self):
        self.assertFalse(cosmic_connection_supported([], '<node><interface name="org.freedesktop.portal.ScreenCast"/></node>'))
        self.assertFalse(cosmic_connection_supported([], '<node><interface name="org.freedesktop.portal.RemoteDesktop"><method name="CreateSession"/></interface></node>'))
    def test_supported_transports(self):
        self.assertTrue(cosmic_connection_supported(['com.system76.CosmicComp']))
        self.assertTrue(cosmic_connection_supported([],libei_socket='/run/user/test/eis'))
        self.assertTrue(cosmic_connection_supported([], '<node><interface name="org.freedesktop.portal.RemoteDesktop"><method name="ConnectToEIS"/></interface></node>'))
    def test_missing_or_bad_introspection_is_not_a_confirmation(self):
        self.assertFalse(cosmic_connection_supported([],''))
        self.assertFalse(cosmic_connection_supported([],'not xml'))


class BuiltinKeyboardSettingsTests(unittest.TestCase):
    def test_builtin_and_fallback_are_explicit_settings(self):
        original={'plugin_setting':'retained'}
        values=[{'path':['onscreen_keyboard'],'value':'builtin'},{'path':['keyboard_fallback'],'value':False}]
        merged=merge_values(original,values)
        self.assertEqual(merged,{'plugin_setting':'retained','onscreen_keyboard':'builtin','keyboard_fallback':False})
        self.assertEqual(original,{'plugin_setting':'retained'})
        keyboard=next(card for card in groups({}) if card.get('keyboard'))
        self.assertTrue(next(row['value'] for row in keyboard['rows'] if row['path']==['keyboard_fallback']))
