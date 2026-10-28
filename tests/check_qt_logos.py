"""List logos keep their bounds, aspect ratio and spacing at focus zoom."""
import sys
import tempfile
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QUrl, QPointF
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
from qt_app.main import LibraryController

app = QApplication([])
errors = []
def pump():
    end = time.monotonic()+0.25
    while time.monotonic()<end:
        app.processEvents()
        time.sleep(.005)
def tree(item):
    yield item
    for child in item.childItems():
        yield from tree(child)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    for name, width, height in [('wide', 900, 100), ('tall', 100, 400)]:
        image = QImage(width, height, QImage.Format_RGBA8888)
        image.fill(QColor('coral'))
        assert image.save(str(root/(name+'.png')))
    games = [dict(id=str(i), title=f'Game {i}', kind='custom', logo=str(root/('wide.png' if i%2 else 'tall.png'))) for i in range(13)]
    c = LibraryController(games, {}, root, allow_edit=False, allow_launch=False)
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda ws: errors.extend(w.toString() for w in ws))
    engine.rootContext().setContextProperty('libraryController', c)
    qml = root/'Logos.qml'
    qml.write_text('import QtQuick\nimport "'+QUrl.fromLocalFile(str(ROOT/'qt_app')).toString()+'"\nWindow {visible:true; width:1280; height:300; LibraryView {anchors.fill:parent;controller:libraryController}}')
    engine.load(QUrl.fromLocalFile(str(qml)))
    assert engine.rootObjects(), errors
    window = engine.rootObjects()[0]
    for count in [1, 2, 13]:
        c.catalog.games = games[:count]
        c.catalog.filter()
        c.changed.emit()
        for side in ['top', 'left', 'bottom', 'right']:
            vertical = side in ['left','right']
            window.resize(320 if vertical else 1280, 900 if vertical else 260)
            for zoom, focus in [(50,100), (100,150), (200,250)]:
                c.settings = dict(list_side=side, list_zoom=zoom, list_focus_zoom=focus)
                c.appearanceChanged.emit()
                c.move(1)
                pump()
                tiles = []
                cross_positions = []
                for tile in tree(window.contentItem()):
                    if tile.objectName()!='listLogoTile': continue
                    on_path, error = QQmlExpression(engine.contextForObject(tile), tile, 'PathView.onPath').evaluate()
                    if error or not on_path: continue
                    point = tile.mapToScene(QPointF(0,0))
                    assert point.x()>=-1 and point.y()>=-1, (count,side,zoom,focus,point)
                    assert point.x()+tile.width()<=window.width()+1
                    assert point.y()+tile.height()<=window.height()+1
                    assert tile.scale()==1
                    if tile.property('selected'):
                        assert abs(point.x()+tile.width()/2-window.width()/2)<1,(count,side,zoom,focus,point,tile.width(),window.width())
                        assert abs(point.y()+tile.height()/2-window.height()/2)<1,(count,side,zoom,focus,point,tile.height(),window.height())
                    artwork = next(item for item in tree(tile) if item.objectName()=='tileArtwork')
                    assert artwork.property('cornerRadius')==0
                    assert artwork.property('paintedWidth')<=artwork.width()+1
                    assert artwork.property('paintedHeight')<=artwork.height()+1
                    cross_positions.append(point.x()+tile.width()/2 if vertical else point.y()+tile.height()/2)
                    tiles.append((point.y() if vertical else point.x(),tile.height() if vertical else tile.width()))
                assert len(tiles)>=min(count,5), (count,side,zoom,focus,len(tiles))
                if count>=3: assert max(cross_positions)-min(cross_positions)>0.5
                tiles.sort()
                for (start,extent),(next_start,_) in zip(tiles,tiles[1:]):
                    assert next_start-start-extent>=23, (count,side,zoom,focus,tiles)
    # User case: 120% base size and 250% focus must not shrink all neighbours.
    window.resize(1800,360)
    c.settings=dict(list_side='bottom',list_zoom=120,list_focus_zoom=250)
    c.appearanceChanged.emit();pump()
    normal_widths=[];selected_width=None
    for tile in tree(window.contentItem()):
        if tile.objectName()!='listLogoTile': continue
        on_path,error=QQmlExpression(engine.contextForObject(tile),tile,'PathView.onPath').evaluate()
        if error or not on_path: continue
        if tile.property('selected'): selected_width=tile.width()
        else: normal_widths.append(tile.width())
    assert len(normal_widths)>=4
    assert min(normal_widths)>=250,normal_widths
    assert abs(selected_width/normal_widths[0]-2.5)<.01
    assert not errors, errors
    c.manager.shutdown()
    c.idle_timer.stop()
    window.close()
    del engine
print('QT_LOGOS_OK: wide/tall images, 1/2/13 games, both orientations, zoom 50–200%, focus 100–250%, no clipping or overlap')
