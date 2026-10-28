"""Qt graphical migration checks. All writes and commands use a temporary profile."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library

app=QApplication([])
app.setDesktopFileName("io.github.estante.Test")
errors=[]
def pump(seconds=.1):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents(); time.sleep(.005)
def done(manager):
    deadline=time.monotonic()+8
    while manager.busy and time.monotonic()<deadline: pump(.02)
    assert not manager.busy, 'Worker did not finish'
    assert not any(word in manager.message.lower() for word in ('traceback','no válida','error:')),manager.message

with tempfile.TemporaryDirectory(prefix='estante-qt-complete-') as folder:
    root=Path(folder)
    image=QImage(80,120,QImage.Format.Format_RGB32); image.fill(0xff556677)
    image.save(str(root/'source.png'))
    library=Library(data_dir=root)
    games=[dict(id=str(i),title=f'Game {i:03d}',kind='custom',cover=str(root/'source.png'),banner=str(root/'source.png'),categories=['Fav'] if i%2 else []) for i in range(100)]
    library.put_many(games)
    controller=LibraryController(games,{},root,allow_launch=False)
    engine=QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0]; controller.window=window
    window.resize(1440,1000)
    pump(.4)
    for mode in ('grid','carousel','ps5','list'):
        controller.changeView(mode)
        for _ in range(12): controller.move(1)
        pump(.2)
        window.grabWindow().save('/tmp/estante-qt-mode-'+mode+'.png')
    # Circular list crosses both boundaries with a bounded set of delegates.
    def visible_tree(item):
        yield item
        for child in item.childItems(): yield from visible_tree(child)
    loop=next(item for item in visible_tree(window.contentItem()) if item.objectName()=='infiniteList')
    assert loop and loop.property('pathItemCount') < 12
    controller.select(99);pump(.2)
    controller.move(1);pump(.3)
    assert controller.selected==0 and loop.property('currentIndex')%100==0
    controller.move(-1);pump(1)
    assert controller.selected==99 and loop.property('currentIndex')%100==99
    strip=window.findChild(QObject,'libraryStrip')
    controller.changeView('grid');pump(.2)
    assert strip.property('height')>window.height()*.7
    assert strip.property('width')>window.width()*.6
    controller.changeView('ps5');pump(.2)
    assert strip.property('x')<window.width()*.1
    controller.inputAction.emit('appearance_settings');pump()
    assert window.findChild(QObject,'managementPanel').property('section')==10
    controller.inputAction.emit('back');pump()
    controller.changeView('list');pump(.2)
    assert window.findChild(QObject,'editButton').property('text')=='...'
    assert 'editar' in controller.controllerHints and 'ajustes' in controller.controllerHints
    manager=controller.manager
    manager.saveSettingValues([dict(path=['minimal_views','list'],value=True),dict(path=['background_dim','list'],value=44)])
    pump(.2)
    window.findChild(QObject,'libraryStrip').forceActiveFocus();pump(.1)
    controller.inputAction.emit('up'); pump()
    assert window.activeFocusItem().objectName()=='editButton'
    controller.inputAction.emit('confirm'); pump()
    assert controller.editing
    controller.inputAction.emit('back'); pump()
    assert not controller.editing
    controller.inputAction.emit('menu'); pump()
    management=window.findChild(QObject,'managementPanel')
    assert management and management.property('visible')
    def visual_children(item):
        yield item
        for child in item.childItems(): yield from visual_children(child)
    for page in range(11):
        management.setProperty('section',page);pump(.12)
        if page==4 or page>=7:
            headers=[item for item in visual_children(window.contentItem()) if item.objectName().startswith('groupHeader:')]
            assert headers
    management.setProperty('section',4);pump()
    assert controller.letters[controller.letterIndex]=='G'
    assert window.findChild(QObject,'category').metaObject().className().startswith('ContextStrip')
    controller.inputAction.emit('back');pump()
    assert not management.property('visible')
    manager.category('create','Empty',''); done(manager)
    assert 'Empty' in controller.categories
    controller.category(controller.categories.index('Empty'))
    controller.refresh(); assert controller.catalog.category=='Empty'
    controller.category(0)
    manager.importImage('logo',str(root/'source.png'));done(manager)
    selected=controller.catalog.selected_id
    assert Library(data_dir=root).games()[int(selected)]['cover']  # Original retained.
    script=root/'test.sh';script.write_text('#!/bin/sh\nexit 0\n')
    manager.saveLocal('Added',str(script),'','',False); done(manager)
    assert any(g['title']=='Added' for g in controller.catalog.games)
    manager.category('rename','Renamed','Empty');done(manager)
    assert 'Renamed' in controller.categories
    controller.activateScreensaver();pump()
    assert controller.screensaverActive and controller.entries==[]
    controller.recordActivity();pump()
    assert not controller.screensaverActive and len(controller.entries)==101
    assert 'gi.repository.Gtk' not in sys.modules, 'Qt loaded GTK'
    manager.shutdown();controller.idle_timer.stop()
    window.close();pump()
    del engine
assert not errors,'\n'.join(errors)
print('QT_MIGRATION_INTEGRATION_OK: modes, minimal/controller, 7 panels, settings, categories, artwork, local add, screensaver, no GTK')
