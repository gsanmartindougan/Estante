"""Directional selection and SDL2 gamepad input, without a Python SDL dependency."""
from i18n import tr
import ctypes as C
from ctypes.util import find_library
import time
import unicodedata
import os
from pathlib import Path


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

    def poll(self):
        now = time.monotonic()
        self.sdl.SDL_PumpEvents()
        self.sdl.SDL_GameControllerUpdate()
        if self.controller and not self.sdl.SDL_GameControllerGetAttached(self.controller):
            self.sdl.SDL_GameControllerClose(self.controller)
            self.controller = None
            self.repeater.update(set(), now)
        if not self.controller and now >= self.scan_at:
            self.scan_at = now + 1
            for index in range(self.sdl.SDL_NumJoysticks()):
                if self.sdl.SDL_IsGameController(index):
                    self.controller = self.sdl.SDL_GameControllerOpen(index)
                    if self.controller:
                        break
        pressed = set()
        if self.controller:
            for index, action in {0: 'confirm', 1: 'back', 2: 'search', 4: 'search',
                                  6: 'menu', 9: 'page_previous', 10: 'page_next', 11: 'up', 12: 'down', 13: 'left', 14: 'right'}.items():
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
        active = self.active()
        actions = self.repeater.update(pressed, now)
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
