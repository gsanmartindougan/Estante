"""GTK/Qt-independent launch worker; all UI delivery goes through emit."""
from datetime import datetime
from pathlib import Path
from threading import Event
import time

from library import Library, launch
from game_session import wait_for_game
import game_supervisor


STARTUP_DISPLAY_SECONDS = 25


class Transferred(Exception):
    """The acknowledged supervisor now owns recording and restoration."""


def run_session(game, root, restore, reopen, hide, emit):
    """Run on a worker thread. Never infer readiness from window focus."""
    try:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        process = launch(game, root)
        started = datetime.now().isoformat()
        started_at = time.monotonic()
        def ready():
            emit(('started', None))
            if not hide:
                return
            try:
                folder = game_supervisor.prepare(game, process, root, started,
                                                 started_at, restore, reopen=reopen)
                acknowledged = Event()
                emit(('handoff', (folder, acknowledged)))
                if acknowledged.wait(5):
                    raise Transferred()
                (folder/'cancel').touch()
                emit(('warning', 'No se completó la transferencia. Estante seguirá abierto.'))
            except Transferred:
                raise
            except Exception as error:
                emit(('warning', str(error)))
        # Keep monitoring failures/exits throughout the delay; never block in ready().
        def delay_elapsed(_pids):
            return time.monotonic() - started_at >= STARTUP_DISPLAY_SECONDS
        code = wait_for_game(game, process, on_started=ready, is_ready=delay_elapsed)
        # Re-read the current file; preserve edits made while the game ran.
        Library(data_dir=root).record_session(game, time.monotonic()-started_at, started, code)
        emit(('finished', code))
    except Transferred:
        return
    except Exception as error:
        emit(('error', str(error)))
