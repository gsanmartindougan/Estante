"""GTK-style groups, inline radios, controller navigation and saved drafts."""
import sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QUrl,QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from qt_app.main import LibraryController
from library import Library
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
def descendants(item):
    yield item
    for child in item.childItems():yield from descendants(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);library=Library(data_dir=root)
    game=dict(id='one',title='Game',kind='custom');library.put(game)
    controller=LibraryController([game],{'language':'es'},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[];engine.warnings.connect(lambda rows:errors.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];controller.window=window;pump(.3)
    controller.inputAction.emit('menu');pump(.2)
    panel=window.findChild(QObject,'managementPanel');assert panel.property('visible')
    def find(name):return next(item for item in descendants(window.contentItem()) if item.objectName()==name)
    controller.inputAction.emit('right');pump()
    assert window.activeFocusItem().objectName()=='groupHeader:Idioma'
    window.grabWindow().save('/tmp/estante-settings-gtk-collapsed.png')
    controller.inputAction.emit('confirm');pump()
    group=find('settingsGroup:Idioma');assert group.property('expanded')
    controller.inputAction.emit('down');pump()
    assert window.activeFocusItem().objectName()=='radio:["language"]:0'
    controller.inputAction.emit('confirm');pump()
    assert panel.property('settingsDraft').toVariant()['["language"]']=='system'
    controller.inputAction.emit('down');pump()
    controller.inputAction.emit('confirm');pump()
    assert '["language"]' not in panel.property('settingsDraft').toVariant()
    heading=find('groupHeader:Tipo de mando');heading.forceActiveFocus();controller.inputAction.emit('confirm');pump()
    assert group.property('expanded') and find('settingsGroup:Tipo de mando').property('expanded')
    window.grabWindow().save('/tmp/estante-settings-gtk-radios.png')
    controller.inputAction.emit('down');pump();controller.inputAction.emit('confirm');pump()
    assert panel.property('settingsDraft').toVariant()['["controller_type"]']=='sony'
    controller.inputAction.emit('back');pump()
    assert not find('settingsGroup:Tipo de mando').property('expanded') and panel.property('visible')
    # Page changes retain the pending global draft.
    for page in [8,9,10,7]:
        panel.setProperty('section',page);pump()
        assert find('groupHeader:Imagen de fondo') and find('groupHeader:Anillo de selección')
    heading=find('groupHeader:Imagen de fondo');heading.forceActiveFocus()
    controller.inputAction.emit('confirm');pump()
    controller.inputAction.emit('down');pump()
    slider=window.activeFocusItem();assert slider.property('gamepadKind')=='slider'
    value=slider.property('value')
    controller.inputAction.emit('confirm');pump();controller.inputAction.emit('right');pump()
    assert slider.property('value')==value+1 and window.activeFocusItem()==slider
    controller.inputAction.emit('back');pump()
    assert not slider.property('gamepadAdjusting') and panel.property('visible')
    panel.setProperty('section',4);pump()
    save=next(item for item in descendants(window.contentItem()) if item.property('text')=='Guardar globales')
    save.forceActiveFocus();controller.inputAction.emit('save');pump()
    assert controller.settings['controller_type']=='sony',controller.settings
    assert not panel.property('settingsDraft').toVariant()
    controller.manager.shutdown();controller.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_GTK_SETTINGS_OK: sidebar, columns, independent expanders, inline radios, controller, draft/save')
