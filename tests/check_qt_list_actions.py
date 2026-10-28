"""List actions belong below the detail cover, outside the focused logo strip."""
import sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QObject,QUrl,QPointF
from PySide6.QtGui import QImage,QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression
from qt_app.main import LibraryController
app=QApplication([])
def pump():
    end=time.monotonic()+.2
    while time.monotonic()<end:app.processEvents();time.sleep(.005)
errors=[]
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    image=QImage(300,450,QImage.Format_RGBA8888);image.fill(QColor('coral'));image.save(str(root/'cover.png'))
    games=[dict(id=str(i),kind='custom',title=f'Game {i}',cover=str(root/'cover.png'),logo=str(root/'cover.png')) for i in range(13)]
    c=LibraryController(games,{'layout':'list'},root,allow_edit=False,allow_launch=False)
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('libraryController',c)
    engine.warnings.connect(lambda ws:errors.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(ROOT/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0]
    cover=window.findChild(QObject,'detailCover');actions=window.findChild(QObject,'gameActions')
    strip=window.findChild(QObject,'libraryStrip')
    for width,height in [(800,600),(1440,900),(2560,1440)]:
        window.resize(width,height)
        for side in ['left','right','top','bottom']:
            c.settings['list_side']=side;c.appearanceChanged.emit();pump()
            body_top=window.property('listBodyTop');body_height=window.property('listBodyHeight')
            if side in ['left','right']:
                assert abs(strip.x()+strip.width()/2-width*(.175 if side=='left' else .825))<1
                assert abs(strip.y()+strip.height()/2-body_top-body_height/2)<1
                panel=window.findChild(QObject,'heroSurface')
                content=window.findChild(QObject,'infoContent')
                assert panel.width()<=880
                assert panel.height()<=420
                assert panel.height()<=content.property('implicitHeight')+48.5
                panel_point=panel.mapToScene(QPointF(0,0))
                assert abs(panel_point.x()+panel.width()/2-width*(.675 if side=='left' else .325))<1
                assert actions.y()+actions.height()<panel_point.y()
            else:
                assert abs(strip.y()+strip.height()/2-body_top-body_height*(.175 if side=='top' else .825))<1
            point=cover.mapToScene(QPointF(0,0))
            assert point.y()+cover.height()<actions.y(),(width,height,side,point,actions.y())
            assert abs(point.x()+cover.width()/2-actions.x()-actions.width()/2)<1
            assert actions.x()>=0 and actions.x()+actions.width()<=width
            assert actions.y()+actions.height()<=height,(width,height,side,actions.y())
            selected,error=QQmlExpression(engine.rootContext(),strip,'selectedItem()').evaluate()
            assert not error and selected is not None
            assert window.findChild(QObject,'wheelSelector') is None
            assert selected.property('color').alpha()>0
            if side in ['left','right']: assert abs(strip.width()/width-.35)<.001
            position=selected.mapToScene(QPointF(0,0))
            assert actions.y()>=position.y()+selected.height() or actions.y()+actions.height()<=position.y() or actions.x()>=position.x()+selected.width() or actions.x()+actions.width()<=position.x()
    for game in c.catalog.games: game['cover']=''
    c.changed.emit();c.selectionChanged.emit()
    window.resize(800,600)
    for side in ['left','right','top','bottom']:
        c.settings['list_side']=side;c.appearanceChanged.emit();pump()
        assert not cover.property('visible')
        if side in ['left','right']:
            panel=window.findChild(QObject,'heroSurface')
            assert actions.y()+actions.height()<panel.mapToScene(QPointF(0,0)).y()
        else:
            assert actions.y()>strip.y()+strip.height()
        assert actions.x()>=0 and actions.x()+actions.width()<=window.width()
        assert actions.y()+actions.height()<=window.height()
    c.catalog.games[0]['metadata']={'synopsis':'Descripción larga del juego. '*300}
    c.catalog.select(0)
    c.settings['list_side']='left'
    window.resize(1440,900)
    c.changed.emit();c.selectionChanged.emit();c.appearanceChanged.emit();pump()
    panel=window.findChild(QObject,'heroSurface')
    content=window.findChild(QObject,'infoContent')
    assert content.property('implicitHeight')>panel.height()
    assert panel.height()<=420
    assert not errors,errors
    c.manager.shutdown();c.idle_timer.stop();window.close();del engine
print('QT_LIST_ACTIONS_OK: buttons under cover, visible selected-logo highlight, no overlap, four positions and three window sizes')
