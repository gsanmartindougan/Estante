"""Observe launcher processes off the GUI thread and expose their startup state."""
import threading
import subprocess
import time
from PySide6.QtCore import QObject, Property, Signal, Slot
from i18n import tr
from qt_app.launcher_processes import running_clients, launch_hidden, CLIENT_NAMES


class LauncherStatus(QObject):
    changed = Signal()
    snapshot = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {key: 'checking' for key in CLIENT_NAMES}
        self._notice = ''
        self._manual = {}
        self._stop = threading.Event()
        self._thread = None
        self.snapshot.connect(self.apply_snapshot)

    @Property('QVariantList', notify=changed)
    def entries(self):
        labels = {'checking': tr('Comprobando…'), 'closed': tr('No está abierto'),
                  'opening': tr('Abriendo…'), 'closing': tr('Cerrando…'), 'open': tr('Abierto'),
                  'missing': tr('No instalado'), 'error': tr('No se pudo abrir'),
                  'timeout': tr('No se ha confirmado el inicio')}
        return [dict(id=key, name=name, state=self._states[key], text=labels[self._states[key]])
                for key, name in CLIENT_NAMES.items()]

    @Property(str, notify=changed)
    def notice(self):
        return self._notice

    def begin_action(self, client, opening):
        self._manual[client] = ('opening' if opening else 'closing', time.monotonic()+45)
        self._states[client] = self._manual[client][0]
        self.changed.emit()

    def cancel_action(self, client):
        self._manual.pop(client, None)
        self._states[client] = 'error'
        self.changed.emit()

    @Slot(object, str)
    def apply_snapshot(self, states, notice):
        updated = {key: states.get(key, 'checking') for key in CLIENT_NAMES}
        for client, (pending, deadline) in list(self._manual.items()):
            complete = updated[client] == ('open' if pending == 'opening' else 'closed')
            if complete:
                self._manual.pop(client)
            elif time.monotonic() >= deadline:
                self._manual.pop(client)
                updated[client] = 'timeout'
            else:
                updated[client] = pending
        if self._states != updated or self._notice != notice:
            self._states = updated
            self._notice = notice
            self.changed.emit()

    def start(self, settings):
        if self._thread:
            return
        enabled = {key for key in self._states if settings.get('start_' + key + '_on_start', False)}
        self._thread = threading.Thread(target=self._watch, args=(enabled,), name='launcher-status', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _watch(self, enabled):
        pending, failures = {}, {}
        first = True
        while not self._stop.is_set():
            try:
                running = running_clients()
            except OSError:
                if self._stop.wait(3):
                    break
                continue
            notice = ''
            for key in running:
                failures.pop(key, None)
            if first:
                first = False
                for key in enabled - running:
                    name = CLIENT_NAMES[key]
                    # Notify before starting the external process.
                    pending[key] = time.monotonic()
                    states = {k: 'open' if k in running else 'opening' if k in pending else 'closed' for k in self._states}
                    self.snapshot.emit(states, tr('Abriendo') + ' ' + name + ' ' + tr('en segundo plano…'))
                    try:
                        launch_hidden(key)
                    except FileNotFoundError:
                        failures[key] = 'missing'
                        pending.pop(key)
                    except (OSError, subprocess.TimeoutExpired):
                        failures[key] = 'error'
                        pending.pop(key)
            for key in list(pending):
                if key in running:
                    pending.pop(key)
                elif time.monotonic() - pending[key] > 45:
                    pending.pop(key)
                    failures[key] = 'timeout'
            states = {key: 'open' if key in running else 'opening' if key in pending else failures.get(key, 'closed') for key in self._states}
            opening = [CLIENT_NAMES[key] for key in pending]
            if opening:
                notice = tr('Abriendo') + ' ' + ', '.join(opening) + ' ' + tr('en segundo plano…')
            self.snapshot.emit(states, notice)
            self._stop.wait(3)
