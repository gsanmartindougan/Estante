"""Start an installed Steam client quietly, without disturbing an existing session."""
import os
from pathlib import Path
import shutil
import subprocess
import threading


def steam_running(proc=Path('/proc')):
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == os.getuid() and (entry / 'comm').read_text().strip() == 'steam':
                return True
        except (OSError, ValueError):
            continue
    return False


def ensure_steam():
    try:
        if steam_running():
            return
        executable = shutil.which('steam')
        if executable:
            command = [executable, '-silent']
        else:
            flatpak = shutil.which('flatpak')
            if not flatpak:
                return
            installed = subprocess.run(
                [flatpak, 'info', 'com.valvesoftware.Steam'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
            if installed.returncode:
                return
            command = [flatpak, 'run', 'com.valvesoftware.Steam', '-silent']
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired):
        # Missing/broken Steam must never prevent opening the library.
        return


def start_steam_in_background():
    threading.Thread(target=ensure_steam, name='steam-startup', daemon=True).start()
