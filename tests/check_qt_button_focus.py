"""Controller focus must be visually distinct on the primary play button."""
import sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QObject,QUrl,QPointF
from PySide6.QtGui import QColor,QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression
from qt_app.main import LibraryController
app=QApplication([])
def pump():
    end=time.monotonic()+.15
    while time.monotonic()<end:app.processEvents();time.sleep(.005)
errors=[]
with tempfile.TemporaryDirectory() as folder:
    c=LibraryController([dict(id='one',title='Focus test',kind='custom')],{},Path(folder))
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty('libraryController',c)
    engine.warnings.connect(lambda ws:errors.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(ROOT/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0]
    play=window.findChild(QObject,'playButton');edit=window.findChild(QObject,'editButton')
    ring=play.findChild(QObject,'buttonFocusRing')
    edit_ring=edit.findChild(QObject,'buttonFocusRing')
    strip=window.findChild(QObject,'libraryStrip')
    for highlight in ['#7e2a2b','#e3c7f2']:
        palette=QPalette(app.palette());palette.setColor(QPalette.Highlight,QColor(highlight));app.setPalette(palette)
        strip.forceActiveFocus();pump()
        assert not ring.property('visible')
        c.inputAction.emit('up');pump()
        assert window.activeFocusItem()==play
        assert ring.property('visible') and QQmlExpression(engine.rootContext(),ring,'border.width').evaluate()==(3,False)
        assert ring.width()>play.width()+10
        before=window.grabWindow()
        c.inputAction.emit('right');pump()
        assert window.activeFocusItem()==edit
        assert not ring.property('visible') and edit_ring.property('visible')
        assert before!=window.grabWindow()
    c.inputAction.emit('menu');pump()
    panel=window.findChild(QObject,'managementPanel');panel.setProperty('section',2);pump()
    button=window.findChild(QObject,'scanFaugusButton')
    assert button is not None
    button.forceActiveFocus();pump()
    ring=button.findChild(QObject,'buttonFocusRing')
    assert ring.property('visible')
    ancestor=ring.parentItem()
    while ancestor:
        if ancestor.clip():
            point=ring.mapToItem(ancestor,QPointF(0,0))
            assert point.x()>=0 and point.y()>=0,(ancestor.objectName(),point)
            assert point.x()+ring.width()<=ancestor.width()+.5
            assert point.y()+ring.height()<=ancestor.height()+.5
        ancestor=ancestor.parentItem()
    sidebar=window.findChild(QObject,'settingsSidebar')
    assert sidebar is not None
    def visual_tree(item):
        yield item
        for child in item.childItems(): yield from visual_tree(child)
    for width,height in [(1440,900),(800,600)]:
        window.resize(width,height);pump()
        buttons=[item for item in visual_tree(sidebar) if item.property('sectionId') is not None and item.isEnabled()]
        assert len(buttons)>=7
        for button in buttons:
            button.forceActiveFocus();pump()
            ring=button.findChild(QObject,'buttonFocusRing')
            assert ring.property('visible')
            ancestor=ring.parentItem()
            while ancestor:
                if ancestor.clip():
                    point=ring.mapToItem(ancestor,QPointF(0,0))
                    assert point.x()>=-.5 and point.y()>=-.5,(width,height,button.property('text'),ancestor.objectName(),point)
                    assert point.x()+ring.width()<=ancestor.width()+.5
                    assert point.y()+ring.height()<=ancestor.height()+.5
                ancestor=ancestor.parentItem()
    assert not errors,errors
    c.manager.shutdown();c.idle_timer.stop();window.close();del engine
print('QT_BUTTON_FOCUS_OK: controller navigation, separated high-contrast ring on dark/light fills, focus follows selection')
