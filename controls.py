"""Directional selection and SDL2 gamepad input, without a Python SDL dependency."""
from i18n import tr
import ctypes as C
from ctypes.util import find_library
import time
import unicodedata
import os
from pathlib import Path


def controller_buttons(settings):
    profiles = {
        'xbox': dict(confirm='A', back='B', save='Y', search='View', bumpers='LB/RB', triggers='LT/RT', chord='LB+RB'),
        'sony': dict(confirm='×', back='○', save='△', search='Share', bumpers='L1/R1', triggers='L2/R2', chord='L1+R1'),
        'nintendo': dict(confirm='B', back='A', save='X', search='−', bumpers='L/R', triggers='ZL/ZR', chord='L+R'),
    }
    return profiles.get(settings.get('controller_type'), profiles['xbox'])


def controller_hint(settings):
    return tr('← ↑ ↓ →: mover · {bumpers}: letra · {triggers}: categoría · Enter / {confirm}: abrir · Esc / {back}: volver · Ctrl+F / {search}: buscar · Ctrl+Tab / {chord}: aspecto').format(**controller_buttons(settings)) + tr(' · L3+R3: ajustes del aspecto')


def controller_save_hint(settings):
    return tr('{save} · Ctrl+S: guardar').format(**controller_buttons(settings))


def title_initial(title):
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', title.strip())
                         if not unicodedata.combining(c)).upper()
    return normalized[0] if normalized and 'A' <= normalized[0] <= 'Z' else '#'


def alphabet_window(titles, current_title):
    letters = sorted({title_initial(title) for title in titles})
    current = title_initial(current_title)
    if current not in letters:
        return ('', '—', '')
    if len(letters) == 1:
        return ('', current, '')
    index = letters.index(current)
    return (letters[(index - 1) % len(letters)], current, letters[(index + 1) % len(letters)])


def alphabet_target(titles, current, forward=True):
    """First game in the next populated initial, wrapping at the ends."""
    if not titles:
        return None
    initials = [title_initial(title) for title in titles]
    letters = sorted(set(initials))
    if len(letters) == 1:
        return current
    letter = letters[(letters.index(initials[current]) + (1 if forward else -1)) % len(letters)]
    return initials.index(letter)


def neighbor(points, current, direction):
    """Choose the nearest tile in the requested row/column direction."""
    if not points:
        return None
    if current is None or not 0 <= current < len(points):
        return 0
    x, y = points[current]
    dx, dy = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}[direction]
    candidates = []
    for index, (px, py) in enumerate(points):
        forward = (px - x) * dx + (py - y) * dy
        cross = abs((py - y) if dx else (px - x))
        if forward > 1:
            candidates.append((cross, forward, index))
    return min(candidates)[2] if candidates else current


def appearance_chord(pressed):
    actions = pressed - {'left_stick', 'right_stick'}
    if {'left_stick', 'right_stick'} <= pressed:
        actions.add('appearance_settings')
    return actions


class Repeater:
    def __init__(self):
        self.held = set()
        self.deadlines = {}

    def update(self, pressed, now):
        actions = []
        for action in sorted(pressed):
            if action not in self.held:
                actions.append(action)
                self.deadlines[action] = now + 0.4
            elif action in ('left', 'right', 'up', 'down', 'page_previous', 'page_next') and now >= self.deadlines[action]:
                actions.append(action)
                self.deadlines[action] = now + 0.13
        self.held = set(pressed)
        self.deadlines = {key: value for key, value in self.deadlines.items() if key in pressed}
        return actions


class BumperChord:
    """Defer a single bumper until release so a chord never jumps letters."""
    def __init__(self):
        self.held = set()
        self.chord = False

    def update(self, pressed):
        bumpers = pressed & {'page_previous', 'page_next'}
        actions = []
        if len(bumpers) == 2 and not self.chord:
            self.chord = True
            actions.append('cycle_view')
        if not bumpers:
            if not self.chord:
                actions.extend(sorted(self.held))
            self.chord = False
        self.held = set(bumpers)
        return actions


class StickChord(BumperChord):
    """Dispatch single stick clicks on release, reserving the chord for settings."""
    def update(self, pressed):
        mapped = set()
        if 'left_stick' in pressed:
            mapped.add('page_previous')
        if 'right_stick' in pressed:
            mapped.add('page_next')
        actions = super().update(mapped)
        return [{'page_previous': 'grid_page_previous', 'page_next': 'grid_page_next',
                 'cycle_view': 'appearance_settings'}[action] for action in actions]


class Gamepad:
    FLAGS = 0x2000  # SDL_INIT_GAMECONTROLLER includes joystick and event subsystems.

    def __init__(self, dispatch, active):
        path = find_library('SDL2-2.0') or find_library('SDL2')
        if os.environ.get('ESTANTE_APPDIR'):
            bundled = Path(os.environ['ESTANTE_APPDIR']) / 'usr/lib/libSDL2-2.0.so.0'
            if bundled.is_file():
                path = str(bundled)
        if not path:
            raise RuntimeError(tr('Instala SDL2 para usar un mando.'))
        self.bumpers = BumperChord()
        self.sticks = StickChord()
        self.sdl = C.CDLL(path)
        signatures = {
            'SDL_InitSubSystem': (C.c_int, [C.c_uint32]),
            'SDL_QuitSubSystem': (None, [C.c_uint32]),
            'SDL_NumJoysticks': (C.c_int, []),
            'SDL_IsGameController': (C.c_int, [C.c_int]),
            'SDL_GameControllerOpen': (C.c_void_p, [C.c_int]),
            'SDL_GameControllerClose': (None, [C.c_void_p]),
            'SDL_GameControllerGetAttached': (C.c_int, [C.c_void_p]),
            'SDL_GameControllerGetButton': (C.c_uint8, [C.c_void_p, C.c_int]),
            'SDL_GameControllerGetAxis': (C.c_int16, [C.c_void_p, C.c_int]),
            'SDL_GameControllerUpdate': (None, []),
            'SDL_PumpEvents': (None, []),
            'SDL_FlushEvents': (None, [C.c_uint32, C.c_uint32]),
            'SDL_SetHint': (C.c_int, [C.c_char_p, C.c_char_p]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.sdl, name)
            function.restype, function.argtypes = result, args
        # GTK owns the window; SDL only reads controllers. Focus is gated below.
        self.sdl.SDL_SetHint(b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', b'1')
        if self.sdl.SDL_InitSubSystem(self.FLAGS) < 0:
            raise RuntimeError(tr('No se pudo iniciar la lectura del mando con SDL2.'))
        self.dispatch, self.active = dispatch, active
        self.controller = None
        self.scan_at = 0
        self.repeater = Repeater()
        self.was_active = False
        self.input_ready = False

    def poll(self):
        now = time.monotonic()
        self.sdl.SDL_PumpEvents()
        self.sdl.SDL_GameControllerUpdate()
        if self.controller and not self.sdl.SDL_GameControllerGetAttached(self.controller):
            self.sdl.SDL_GameControllerClose(self.controller)
            self.controller = None
            self.input_ready = False
            self.repeater.update(set(), now)
        if not self.controller and now >= self.scan_at:
            self.scan_at = now + 1
            for index in range(self.sdl.SDL_NumJoysticks()):
                if self.sdl.SDL_IsGameController(index):
                    self.controller = self.sdl.SDL_GameControllerOpen(index)
                    if self.controller:
                        self.input_ready = False
                        break
        pressed = set()
        if self.controller:
            for index, action in {0: 'confirm', 1: 'back', 2: 'search', 3: 'save', 4: 'search',
                                  6: 'menu', 7: 'left_stick', 8: 'right_stick', 9: 'page_previous', 10: 'page_next', 11: 'up', 12: 'down', 13: 'left', 14: 'right'}.items():
                if self.sdl.SDL_GameControllerGetButton(self.controller, index):
                    pressed.add(action)
            x = self.sdl.SDL_GameControllerGetAxis(self.controller, 0)
            y = self.sdl.SDL_GameControllerGetAxis(self.controller, 1)
            for axis, action in ((4, 'category_previous'), (5, 'category_next')):
                if self.sdl.SDL_GameControllerGetAxis(self.controller, axis) > 16000:
                    pressed.add(action)
            if max(abs(x), abs(y)) > 16000:
                pressed.add(('right' if x > 0 else 'left') if abs(x) > abs(y)
                            else ('down' if y > 0 else 'up'))
        # Ignore held/stale controls on attachment until the controller is neutral.
        # Otherwise a stuck direction repeats forever and prevents idle detection.
        if not self.input_ready:
            self.input_ready = not pressed
            pressed = set()
        active = self.active()
        bumper_actions = self.bumpers.update(pressed)
        stick_actions = self.sticks.update(pressed)
        pressed -= {'page_previous', 'page_next', 'left_stick', 'right_stick'}
        actions = self.repeater.update(pressed, now) + bumper_actions + stick_actions
        if active and self.was_active:
            for action in actions:
                self.dispatch(action, True)
        self.was_active = active
        self.sdl.SDL_FlushEvents(0, 0xFFFF)
        return True

    def close(self):
        if self.controller:
            self.sdl.SDL_GameControllerClose(self.controller)
            self.controller = None
        self.sdl.SDL_QuitSubSystem(self.FLAGS)
