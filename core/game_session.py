"""Observe launched games without terminating or modifying their processes."""
from pathlib import Path
import os
import time


def playing_behavior(settings):
    value = settings.get('playing_behavior')
    if value in ('none', 'hide', 'screensaver', 'tray'):
        return value
    return 'hide' if settings.get('hide_while_playing', False) else 'none'


def game_processes(game, launcher_pid, proc_root=Path('/proc'), ready_only=False, session_token=None):
    steam_id = str(game.get('steam_appid', '')) if game.get('kind') == 'steam' else None
    found = []
    for entry in Path(proc_root).iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
            if fields[0] == 'Z':
                continue
            if steam_id:
                environment = (entry / 'environ').read_bytes().split(b'\0')
                identities = (b'SteamAppId=' + steam_id.encode(), b'SteamGameId=' + steam_id.encode())
                matches = any(value in environment for value in identities)
            elif game.get('kind') == 'heroic':
                environment = (entry / 'environ').read_bytes().split(b'\0')
                matches = (('HEROIC_APP_NAME=' + str(game.get('heroic_app_name', ''))).encode() in environment
                           and ('HEROIC_APP_RUNNER=' + str(game.get('heroic_runner', ''))).encode() in environment)
            else:
                matches = int(fields[3]) == launcher_pid
                if session_token:
                    environment = (entry / 'environ').read_bytes().split(b'\0')
                    matches = b'ESTANTE_GAME_SESSION=' + session_token.encode() in environment
            if matches and ready_only and not steam_id:
                target = Path(game.get('path') or '').name.lower()
                if game.get('kind') == 'faugus' and target:
                    # Faugus starts the actual game with start_new_session=True.
                    # Its inherited token follows wrappers and extracted AppImages.
                    if session_token and int(fields[3]) != launcher_pid:
                        found.append(int(entry.name))
                        continue
                    command = (entry / 'cmdline').read_bytes().decode(errors='replace').replace('\\', '/').lower()
                    matches = any(part.rstrip('"').rsplit('/', 1)[-1] == target for part in command.split('\0'))
                elif game.get('path', '').endswith('.sh'):
                    matches = int(entry.name) != launcher_pid
            if matches:
                found.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return found


def wait_for_game(game, process, startup_timeout=90, interval=.5, on_started=None, is_ready=None):
    token = getattr(process, 'estante_session_token', None)
    token = token if isinstance(token, str) else None
    def members(ready_only=False):
        return game_processes(game, process.pid, ready_only=ready_only, session_token=token)
    if game.get('kind') not in ('steam', 'heroic') and on_started is not None:
        observed = False
        while True:
            code = process.poll()
            running = members()
            candidates = members(ready_only=True) if not observed else []
            if candidates and (is_ready is None or is_ready(candidates)):
                observed = True
                on_started()
            if code is not None and not running:
                return code
            time.sleep(interval)
    if game.get('kind') not in ('steam', 'heroic'):
        code = process.wait()
        while members():
            time.sleep(interval)
        return code
    deadline = time.monotonic() + startup_timeout
    observed = False
    notified = False
    while True:
        candidates = members()
        running = bool(candidates)
        code = process.poll()
        if running:
            if not notified and on_started is not None and (is_ready is None or is_ready(candidates)):
                notified = True
                on_started()
            observed = True
        elif observed:
            return code or 0
        elif code is not None and code != 0:
            return code
        elif time.monotonic() >= deadline:
            raise RuntimeError('No se pudo detectar el proceso del juego de ' + ('Heroic.' if game.get('kind') == 'heroic' else 'Steam.'))
        time.sleep(interval)
