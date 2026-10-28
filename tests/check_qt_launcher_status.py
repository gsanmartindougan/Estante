"""Launcher notifications and UI, without opening external applications or desktop windows."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from qt_app.launcher_status import LauncherStatus
from qt_app.settings_schema import groups, merge_values
from i18n import set_language
app = QApplication([])
set_language('es')

class StopAfter:
    def __init__(self, count): self.count = count
    def is_set(self): return self.count <= 0
    def wait(self, seconds): self.count -= 1; return self.is_set()

for enabled in (False, True):
    tracker = LauncherStatus()
    tracker._stop = StopAfter(3)
    snapshots = []
    tracker.snapshot.connect(lambda states, notice: snapshots.append((states, notice)))
    with patch('qt_app.launcher_status.running_clients', side_effect=[set(), {'steam', 'faugus', 'heroic'}, set()]), patch('qt_app.launcher_status.launch_hidden') as launch:
        tracker._watch({'steam', 'faugus', 'heroic'} if enabled else set())
        assert launch.call_count == (3 if enabled else 0)
    if enabled:
        assert any(states['steam'] == 'opening' and 'Steam' in notice for states, notice in snapshots)
        assert any(states['heroic'] == 'opening' and 'Heroic' in notice for states, notice in snapshots)
        assert any(states['faugus'] == 'opening' and 'Faugus' in notice for states, notice in snapshots)
    assert snapshots[-2][0] == {'steam': 'open', 'faugus': 'open', 'heroic': 'open'}
    assert snapshots[-1][0] == {'steam': 'closed', 'faugus': 'closed', 'heroic': 'closed'}
tracker = LauncherStatus(); tracker._stop = StopAfter(1)
with patch('qt_app.launcher_status.running_clients', return_value={'steam', 'faugus', 'heroic'}), patch('qt_app.launcher_status.launch_hidden') as launch:
    tracker._watch({'steam', 'faugus', 'heroic'})
    launch.assert_not_called()
tracker = LauncherStatus(); tracker._stop = StopAfter(1)
with patch('qt_app.launcher_status.running_clients', return_value=set()), patch('qt_app.launcher_status.launch_hidden', side_effect=FileNotFoundError):
    tracker._watch({'steam', 'faugus', 'heroic'})
    assert all(row['state'] == 'missing' for row in tracker.entries)
tracker = LauncherStatus(); tracker._stop = StopAfter(1)
with patch('qt_app.launcher_status.running_clients', return_value=set()), patch('qt_app.launcher_status.launch_hidden'), patch('qt_app.launcher_status.time.monotonic', side_effect=[0, 46]):
    tracker._watch({'steam'})
    assert tracker.entries[0]['state'] == 'timeout'
startup = next(card for card in groups({}) if any(row['path'] == ['start_fullscreen'] for row in card['rows']))
assert any(row['path'] == ['start_faugus_on_start'] and row['value'] is False for row in startup['rows'])
assert merge_values({}, [{'path': ['start_faugus_on_start'], 'value': True}])['start_faugus_on_start']
for key in ('start_heroic_on_start', 'close_heroic_on_exit'):
    assert any(row['path']==[key] and row['value'] is False for row in startup['rows'])
    assert merge_values({}, [{'path':[key], 'value':True}])[key]


def visual(item):
    yield item
    for child in item.childItems(): yield from visual(child)
def pump():
    end = time.monotonic()+.15
    while time.monotonic()<end: app.processEvents(); time.sleep(.004)
with tempfile.TemporaryDirectory() as root:
    c = LibraryController([], {}, Path(root), allow_launch=False)
    engine = QQmlApplicationEngine(); errors=[]
    engine.warnings.connect(lambda rows: errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController', c)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(), errors
    window = engine.rootObjects()[0]; c.window = window
    for state in ('closed', 'opening', 'open', 'closed', 'timeout'):
        c.launchers.apply_snapshot({'steam': state, 'faugus': state, 'heroic': state}, 'Abriendo Steam y Faugus…' if state == 'opening' else '')
        pump()
        for key in ('steam', 'faugus', 'heroic'):
            label = next(i for i in visual(window.contentItem()) if i.objectName() == 'launcherStatus:'+key)
            assert label.property('visible') == (state != 'open')
            assert label.property('text')
        notice = next(i for i in visual(window.contentItem()) if i.objectName() == 'launcherStartupNotice')
        assert notice.property('visible') == (state == 'opening')
    assert not errors, '\n'.join(errors)
    c.manager.shutdown(); c.idle_timer.stop(); window.close(); pump(); del engine
print('QT_LAUNCHER_STATUS_OK: three launchers closed/opening/open, notification, failure state, optional startup, no duplicate launches; offscreen only')
