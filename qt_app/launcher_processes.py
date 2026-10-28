"""Linux launcher detection and quiet startup, independent of the UI."""
import os
import signal
from pathlib import Path
import shutil
import subprocess

CLIENTS = {'steam': ('steam', 'com.valvesoftware.Steam', '-silent'),
           'faugus': ('faugus-launcher', 'io.github.Faugus.faugus-launcher', '--hide'),
           'heroic': ('heroic', 'com.heroicgameslauncher.hgl', '--no-gui')}

CLIENT_NAMES = {'steam': 'Steam', 'faugus': 'Faugus', 'heroic': 'Heroic'}


def is_heroic_main(args):
    if any(arg.startswith(b'--type=') for arg in args):
        return False
    paths = [os.fsdecode(arg) for arg in args[:2] if arg]
    return any(Path(path).name.lower() in ('heroic', 'heroic.bin', 'heroic-launcher')
               or (Path(path).name == 'app.asar' and 'heroic' in str(Path(path).parent).lower())
               for path in paths)


def running_clients(proc=Path('/proc')):
    running = set()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            comm = (entry / 'comm').read_text().strip()
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            if is_heroic_main(args):
                running.add('heroic')
            if comm == 'steam':
                running.add('steam')
            # Exclude runners, backup daemons and games launched through Faugus.
            names = {Path(os.fsdecode(arg)).name for arg in args[:2] if arg}
            if 'faugus-launcher' in names or any(
                args[i] == b'-m' and args[i+1] in (b'faugus.tray_only', b'faugus.launcher')
                for i in range(len(args)-1)
            ):
                running.add('faugus')
        except (OSError, ValueError):
            continue
    return running


def client_command(client, flag):
    executable, app_id, _ = CLIENTS[client]
    native = shutil.which(executable)
    if native:
        command = [native, flag]
    else:
        flatpak = shutil.which('flatpak')
        if not flatpak:
            raise FileNotFoundError(executable)
        installed = subprocess.run([flatpak, 'info', app_id], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=5)
        if installed.returncode:
            raise FileNotFoundError(app_id)
        command = [flatpak, 'run', app_id, flag]
    return command


def launch_hidden(client):
    command = client_command(client, CLIENTS[client][2])
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def close_client(client):
    """Request client termination; never signal games or whole process groups."""
    if client == 'heroic':
        close_heroic()
        return
    if client == 'steam':
        command = client_command(client, '-shutdown')
        subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5, check=True)
        return
    gdbus = shutil.which('gdbus')
    if not gdbus:
        raise FileNotFoundError('gdbus')
    base = [gdbus, 'call', '--session']
    tray = subprocess.run(base + ['--dest', 'io.github.Faugus.faugus-launcher.Tray',
        '--object-path', '/io/github/Faugus/faugus_launcher/Tray',
        '--method', 'io.github.Faugus.Tray.Quit'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    if tray.returncode:
        # Without a tray, the GTK application exports its normal Quit action.
        subprocess.run(base + ['--dest', 'io.github.Faugus.faugus-launcher',
            '--object-path', '/io/github/Faugus/faugus_launcher',
            '--method', 'org.gtk.Actions.Activate', 'quit', '[]', '{}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=True)


def close_on_exit(settings, session_transferred=False):
    if session_transferred:
        return {}
    enabled = {key for key in CLIENTS if settings.get('close_' + key + '_on_exit', False)}
    if not enabled:
        return {}
    errors = {}
    try:
        running = running_clients()
    except OSError as error:
        return {'detection': str(error)}
    for client in enabled & running:
        try:
            close_client(client)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            errors[client] = str(error)
    return errors


def close_heroic(proc=Path('/proc')):
    # Heroic exposes no CLI/DBus Quit action. Use SIGTERM on its main process only.
    # A pidfd keeps a PID reuse race from targeting a different process.
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('No se dispone de cierre seguro mediante pidfd.')
    entries = list(proc.iterdir())
    for entry in entries:
        if not entry.name.isdigit(): continue
        try:
            if entry.stat().st_uid != os.getuid(): continue
            environment = (entry/'environ').read_bytes().split(b'\0')
            if any(value.startswith(b'HEROIC_APP_NAME=') and value != b'HEROIC_APP_NAME=' for value in environment):
                raise RuntimeError('Heroic tiene una partida activa; se mantiene abierto.')
        except OSError:
            continue
    for entry in entries:
        if not entry.name.isdigit(): continue
        try:
            if entry.stat().st_uid != os.getuid(): continue
            if not is_heroic_main((entry/'cmdline').read_bytes().split(b'\0')): continue
            fd = os.pidfd_open(int(entry.name))
            try:
                # Revalidate after acquiring the handle, before sending any signal.
                if entry.stat().st_uid == os.getuid() and is_heroic_main((entry/'cmdline').read_bytes().split(b'\0')):
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        except ProcessLookupError:
            continue
