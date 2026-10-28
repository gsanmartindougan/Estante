"""Transfer an already-started game to a temporary, GTK-free user service."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from game_session import game_processes


def write_state(path, value):
    temporary = Path(str(path) + '.tmp')
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError):
        return None


def host_environment():
    env = dict(os.environ)
    if env.get('ESTANTE_APPDIR'):
        for key in list(env):
            if key.startswith('ESTANTE_HOST_'):
                name = key.removeprefix('ESTANTE_HOST_')
                value = env.pop(key)
                if value:
                    env[name] = value
                else:
                    env.pop(name, None)
        env.pop('ESTANTE_APPDIR', None)
    return env


def prepare(game, process, root, started, started_at, restore, reopen=None):
    executable = shutil.which('systemd-run', path=host_environment().get('PATH'))
    python = '/usr/bin/python3'
    if not executable or not Path(python).is_file():
        raise RuntimeError('Se necesitan systemd-run y Python del sistema para cerrar Estante durante la partida.')
    folder = Path(tempfile.mkdtemp(prefix='estante-session-'))
    try:
        source = Path(__file__).resolve().parent
        # AppImage's temporary mount disappears when its UI exits.
        for name in ('game_supervisor.py', 'game_session.py', 'library.py', 'steam_import.py', 'i18n.py'):
            shutil.copy2(source / name, folder / name)
        environment = host_environment()
        appimage = os.environ.get('APPIMAGE')
        if reopen is None:
            reopen = [appimage] if appimage else [sys.executable, str(source / 'estante.py')]
        spec = dict(game=game, launcher_pid=process.pid,
                    token=getattr(process, 'estante_session_token', None), root=str(root),
                    started=started, started_at=started_at, restore=restore,
                    ui_pid=os.getpid(), ui_identity=process_identity(os.getpid()),
                    reopen=reopen, environment=environment, cwd=str(Path.cwd()))
        path = folder / 'session.json'
        path.write_text(json.dumps(spec))
        path.chmod(0o600)
        command = [executable, '--user', '--collect', '--quiet',
                   '--unit=estante-game-' + uuid.uuid4().hex,
                   '--property=Type=exec', '--property=KillMode=process',
                   '--', python, str(folder / 'game_supervisor.py'), str(path)]
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'No se pudo iniciar el supervisor de la partida.')
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status = folder / 'status.json'
            if status.exists():
                state = json.loads(status.read_text())
                if state['state'] == 'ready':
                    return folder
                raise RuntimeError(state.get('error') or 'La partida terminó antes de transferir la supervisión.')
            time.sleep(.05)
        raise RuntimeError('El supervisor de la partida no respondió. Estante seguirá abierto.')
    except Exception:
        # No acknowledgment means the service must not record or reopen anything.
        (folder / 'cancel').touch()
        raise


def run(path):
    folder = Path(path).parent
    spec = json.loads(Path(path).read_text())
    def members():
        return game_processes(spec['game'], spec['launcher_pid'], session_token=spec['token'])
    try:
        if not members():
            write_state(folder / 'status.json', {'state': 'finished'})
            return
        write_state(folder / 'status.json', {'state': 'ready'})
        deadline = time.monotonic() + 15
        while not (folder / 'handoff').exists():
            if (folder / 'cancel').exists() or time.monotonic() > deadline:
                return
            time.sleep(.05)
        # Wait for the UI to exit before touching its library file.
        while spec['ui_identity'] is not None and process_identity(spec['ui_pid']) == spec['ui_identity']:
            time.sleep(.1)
        while members():
            time.sleep(1)
        from library import Library
        library = Library(data_dir=spec['root'])
        try:
            library.record_session(spec['game'], time.monotonic() - spec['started_at'], spec['started'], None)
        except Exception as error:
            print(f'Estante supervisor: no se pudo guardar la sesión: {error}', file=sys.stderr, flush=True)
        # Leave this tiny restore file outside the temporary service directory.
        restore = Path(spec['root']) / ('resume-' + uuid.uuid4().hex + '.json')
        write_state(restore, spec['restore'])
        environment = dict(spec['environment'], ESTANTE_RESUME_FILE=str(restore), ESTANTE_DATA_DIR=spec['root'])
        subprocess.Popen(spec['reopen'], cwd=spec['cwd'] if Path(spec['cwd']).is_dir() else spec['root'],
                         env=environment, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as error:
        print(f'Estante supervisor: {error}', file=sys.stderr, flush=True)
        raise
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    run(sys.argv[1])
