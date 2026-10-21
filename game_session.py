"""Observe launched games without terminating or modifying their processes."""
from pathlib import Path
import os
import time


def game_processes(game, launcher_pid, proc_root=Path('/proc'), ready_only=False):
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
            else:
                matches = int(fields[3]) == launcher_pid
            if matches and ready_only and not steam_id:
                target = Path(game.get('path') or '').name.lower()
                if game.get('kind') == 'faugus' and target:
                    command = (entry / 'cmdline').read_bytes().decode(errors='replace').replace('\\', '/').lower()
                    matches = any(part.rstrip('"').rsplit('/', 1)[-1] == target for part in command.split('\0'))
                elif game.get('path', '').endswith('.sh'):
                    matches = int(entry.name) != launcher_pid
            if matches:
                found.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return found


def wait_for_game(game, process, startup_timeout=90, interval=.5, on_started=None):
    if game.get('kind') != 'steam' and on_started is not None:
        observed = False
        while True:
            code = process.poll()
            members = game_processes(game, process.pid)
            if not observed and game_processes(game, process.pid, ready_only=True):
                observed = True
                on_started()
            if code is not None and not members:
                return code
            time.sleep(interval)
    if game.get('kind') != 'steam':
        code = process.wait()
        while game_processes(game, process.pid):
            time.sleep(interval)
        return code
    deadline = time.monotonic() + startup_timeout
    observed = False
    while True:
        running = bool(game_processes(game, process.pid))
        code = process.poll()
        if running:
            if not observed and on_started is not None:
                on_started()
            observed = True
        elif observed:
            return code or 0
        elif code is not None and code != 0:
            return code
        elif time.monotonic() >= deadline:
            raise RuntimeError('No se pudo detectar el proceso del juego de Steam.')
        time.sleep(interval)
