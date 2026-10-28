from unittest.mock import patch
import ctypes as C
import unittest

from controls import controller_buttons, controller_hint, controller_save_hint, Gamepad, BumperChord, Repeater, neighbor, alphabet_target, alphabet_window


class NavigationTests(unittest.TestCase):
    def test_controller_profile_hints(self):
        for kind, confirm, back, save, chord in (
            ('xbox', 'A', 'B', 'Y', 'LB+RB'),
            ('sony', '×', '○', '△', 'L1+R1'),
            ('nintendo', 'B', 'A', 'X', 'L+R')):
            settings = {'controller_type': kind}
            buttons = controller_buttons(settings)
            self.assertEqual((buttons['confirm'], buttons['back'], buttons['save']),
                             (confirm, back, save))
            self.assertIn(chord, controller_hint(settings))
            self.assertIn(save, controller_save_hint(settings))
        self.assertEqual(controller_buttons({}), controller_buttons({'controller_type': 'unknown'}))

    def test_alphabet_indicator_matches_populated_letters(self):
        titles = ['Álbum', 'Another', 'Bloodborne', 'Cyberpunk', 'Zelda']
        self.assertEqual(alphabet_window(titles, 'Bloodborne'), ('A', 'B', 'C'))
        self.assertEqual(alphabet_window(titles, 'Álbum'), ('Z', 'A', 'B'))
        self.assertEqual(alphabet_window(['Game 0', 'Game 1'], 'Game 1'), ('', 'G', ''))
        self.assertEqual(alphabet_window([], ''), ('', '—', ''))

    def test_alphabet_skips_empty_initials_and_wraps(self):
        titles = ['123', 'Álbum', 'Another', 'Bloodborne', 'Cyberpunk', 'Zelda']
        self.assertEqual(alphabet_target(titles, 1), 3)
        self.assertEqual(alphabet_target(titles, 2, False), 0)
        self.assertEqual(alphabet_target(titles, 4, False), 3)
        self.assertEqual(alphabet_target(titles, 5), 0)
        self.assertEqual(alphabet_target(titles, 0, False), 5)
        self.assertEqual(alphabet_target(['Game 0', 'Game 1'], 1), 1)
        self.assertIsNone(alphabet_target([], 0))

    def test_directional_grid_with_incomplete_last_row(self):
        points = [(0, 0), (100, 0), (200, 0), (0, 200), (100, 200)]
        self.assertEqual(neighbor(points, None, 'right'), 0)
        self.assertEqual(neighbor(points, 0, 'right'), 1)
        self.assertEqual(neighbor(points, 1, 'down'), 4)
        self.assertEqual(neighbor(points, 2, 'down'), 4)
        self.assertEqual(neighbor(points, 0, 'left'), 0)
        self.assertEqual(neighbor([], None, 'down'), None)

    def test_repeat_only_directions_and_release_resets(self):
        repeat = Repeater()
        self.assertEqual(set(repeat.update({'down', 'confirm'}, 0)), {'down', 'confirm'})
        self.assertEqual(repeat.update({'down', 'confirm'}, .2), [])
        self.assertEqual(repeat.update({'down', 'confirm'}, .41), ['down'])
        self.assertEqual(repeat.update({'down', 'confirm'}, .55), ['down'])
        repeat.update(set(), .6)
        self.assertEqual(repeat.update({'confirm'}, .61), ['confirm'])

    def test_bumper_chord_suppresses_letters_and_does_not_repeat(self):
        chord = BumperChord()
        self.assertEqual(chord.update({'page_previous'}), [])
        self.assertEqual(chord.update({'page_previous', 'page_next'}), ['cycle_view'])
        self.assertEqual(chord.update({'page_previous', 'page_next'}), [])
        self.assertEqual(chord.update({'page_next'}), [])
        self.assertEqual(chord.update(set()), [])
        self.assertEqual(chord.update({'page_next'}), [])
        self.assertEqual(chord.update(set()), ['page_next'])

    def test_sdl_virtual_controller_buttons_stick_and_focus_gate(self):
        actions = []
        active = [True]
        try:
            pad = Gamepad(lambda action, _: actions.append(action), lambda: active[0])
        except (OSError, RuntimeError) as error:
            self.skipTest(str(error))
        self.addCleanup(pad.close)
        sdl = pad.sdl
        for name, result, args in [
            ('SDL_JoystickAttachVirtual', C.c_int, [C.c_int, C.c_int, C.c_int, C.c_int]),
            ('SDL_JoystickDetachVirtual', C.c_int, [C.c_int]),
            ('SDL_JoystickOpen', C.c_void_p, [C.c_int]),
            ('SDL_JoystickClose', None, [C.c_void_p]),
            ('SDL_JoystickSetVirtualButton', C.c_int, [C.c_void_p, C.c_int, C.c_uint8]),
            ('SDL_JoystickSetVirtualAxis', C.c_int, [C.c_void_p, C.c_int, C.c_int16]),
        ]:
            fn = getattr(sdl, name)
            fn.restype, fn.argtypes = result, args
        index = sdl.SDL_JoystickAttachVirtual(1, 6, 15, 0)
        self.assertGreaterEqual(index, 0)
        self.addCleanup(sdl.SDL_JoystickDetachVirtual, index)
        stick = sdl.SDL_JoystickOpen(index)
        self.addCleanup(sdl.SDL_JoystickClose, stick)
        # A device can attach with stale buttons or an uncalibrated stick.
        sdl.SDL_JoystickSetVirtualButton(stick, 14, 1)
        sdl.SDL_JoystickSetVirtualAxis(stick, 0, 24000)
        pad.poll()
        self.assertTrue(pad.controller)
        self.assertFalse(pad.input_ready)
        with patch('controls.time.monotonic', return_value=100000):
            pad.poll()
        self.assertEqual(actions, [], 'Attachment must not emit repeating input or reset idle')
        sdl.SDL_JoystickSetVirtualButton(stick, 14, 0)
        sdl.SDL_JoystickSetVirtualAxis(stick, 0, 0)
        pad.poll()
        self.assertTrue(pad.input_ready)
        sdl.SDL_JoystickSetVirtualButton(stick, 0, 1)
        pad.poll()
        self.assertIn('confirm', actions)
        actions.clear()
        sdl.SDL_JoystickSetVirtualButton(stick, 0, 0)
        pad.poll()
        sdl.SDL_JoystickSetVirtualButton(stick, 4, 1)
        pad.poll()
        self.assertEqual(actions, ['search'])
        actions.clear()
        sdl.SDL_JoystickSetVirtualButton(stick, 4, 0)
        pad.poll()
        sdl.SDL_JoystickSetVirtualButton(stick, 3, 1)
        pad.poll()
        self.assertEqual(actions, ['save'])
        actions.clear()
        pad.poll()
        self.assertEqual(actions, [], 'Holding Y must not save repeatedly')
        sdl.SDL_JoystickSetVirtualButton(stick, 3, 0)
        pad.poll()
        for index, action in ((9, 'page_previous'), (10, 'page_next')):
            sdl.SDL_JoystickSetVirtualButton(stick, index, 1)
            pad.poll()
            self.assertEqual(actions, [])
            sdl.SDL_JoystickSetVirtualButton(stick, index, 0)
            pad.poll()
            self.assertEqual(actions, [action])
            actions.clear()
        for axis, action in ((4, 'category_previous'), (5, 'category_next')):
            sdl.SDL_JoystickSetVirtualAxis(stick, axis, 24000)
            pad.poll()
            self.assertEqual(actions, [action])
            actions.clear()
            pad.poll()
            self.assertEqual(actions, [])
            sdl.SDL_JoystickSetVirtualAxis(stick, axis, -32768)
            pad.poll()
        sdl.SDL_JoystickSetVirtualAxis(stick, 0, 24000)
        pad.poll()
        self.assertEqual(actions, ['right'])
        actions.clear()
        active[0] = False
        sdl.SDL_JoystickSetVirtualButton(stick, 1, 1)
        pad.poll()
        self.assertEqual(actions, [])
        active[0] = True
        pad.poll()
        self.assertEqual(actions, [])


if __name__ == '__main__':
    unittest.main()


class AppearanceShortcutTests(unittest.TestCase):
    def test_both_stick_buttons_open_settings_once_per_press(self):
        from controls import appearance_chord
        repeat = Repeater()
        self.assertEqual(appearance_chord({'left_stick'}), set())
        self.assertEqual(appearance_chord({'right_stick'}), set())
        pressed = appearance_chord({'left_stick', 'right_stick'})
        self.assertEqual(repeat.update(pressed, 0), ['appearance_settings'])
        self.assertEqual(repeat.update(pressed, 2), [])
        repeat.update(set(), 3)
        self.assertEqual(repeat.update(pressed, 4), ['appearance_settings'])


class StickPageTests(unittest.TestCase):
    def test_single_sticks_change_pages_on_release(self):
        from controls import StickChord
        chord = StickChord()
        self.assertEqual(chord.update({'left_stick'}), [])
        self.assertEqual(chord.update(set()), ['grid_page_previous'])
        self.assertEqual(chord.update({'right_stick'}), [])
        self.assertEqual(chord.update(set()), ['grid_page_next'])

    def test_chord_never_changes_pages_and_fires_once(self):
        from controls import StickChord
        chord = StickChord()
        self.assertEqual(chord.update({'left_stick'}), [])
        self.assertEqual(chord.update({'left_stick', 'right_stick'}), ['appearance_settings'])
        self.assertEqual(chord.update({'left_stick', 'right_stick'}), [])
        self.assertEqual(chord.update({'right_stick'}), [])
        self.assertEqual(chord.update(set()), [])
