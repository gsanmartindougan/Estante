"""A lightweight tile model with correctly scoped invalidation; full details stay selected-only."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from qt_app.main import LibraryController
from library import Library
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);image=QImage(16,16,QImage.Format_RGB32);image.fill(0xff447799);image.save(str(root/'cover.png'))
    games=[dict(id=str(i),title=f'Game {i}',kind='custom',cover=str(root/'cover.png'),categories=['Fav'] if i==1 else [],metadata={'description':'Full description','developers':['Studio']}) for i in range(100)]
    lib=Library(data_dir=root);lib.put_many(games);c=LibraryController(games,{},root,allow_launch=False)
    with patch.object(c,'entry',side_effect=AssertionError('Tile model built a full metadata entry')):
        rows=c.entries
        assert len(rows)==100 and not any('metadata' in row or 'history' in row for row in rows)
        assert c.entries is rows
        c.move(1);assert c.entries is rows
        c.changeView('grid');assert c.entries is rows
        c.search('Game 1');assert c.entries is not rows and len(c.entries)==11
        c.category(c.categories.index('Fav'));assert [row['id'] for row in c.entries]==['1']
        c.category(0);c.search('');assert len(c.entries)==100
        original=c.entries;c.use_image_provider=True
        assert c.entries is not original and c.entries[0]['cover'].startswith('image://artwork/')
    assert c.game['description']=='Full description' and 'Studio' in c.game['details']
    lib.put({**games[0],'cover':''});c.refresh();assert not c.entries[0]['cover']
    c._in_tray=True;c.changed.emit();assert c.entries==[]
    c._in_tray=False;c.changed.emit();assert len(c.entries)==100
    c.restoreCursor();c.manager.shutdown();c.idle_timer.stop()
print('QT_MODEL_PROJECTION_OK: lightweight rows, cached across navigation/modes, invalidation on filter/reload/provider/suspension; full selected details retained')
