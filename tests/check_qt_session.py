import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QTimer
from qt_app.main import LibraryController
from library import Library
app=QCoreApplication([])
with tempfile.TemporaryDirectory() as root:
    root=Path(root)
    script=root/'game.sh';script.write_text('#!/bin/sh\nsleep 1\n')
    library=Library(data_dir=root)
    game=Library.local_game('Qt integration test',str(script))
    library.put(game)
    controller=LibraryController([game], {'playing_behavior':'none'}, root)
    visited=[]
    def changed():
        visited.append((controller.busy,controller.loading,controller.status))
        if not controller.busy:
            app.quit()
    controller.sessionChanged.connect(changed)
    controller.play()
    controller.play()  # Duplicate launch must be ignored.
    QTimer.singleShot(8000,app.quit)
    app.exec()
    assert not controller.busy, visited
    assert any(busy and loading for busy,loading,_ in visited)
    assert any(busy and not loading for busy,loading,_ in visited)
    assert Library(data_dir=root).game_stats(game)['sessions']==1
    print('QT_SESSION_INTEGRATION_OK', visited)
