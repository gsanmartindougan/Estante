"""Optional Qt graphical editor integration; writes only a temporary library."""
import sys
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QTimer, QUrl, QMetaObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library

app = QGuiApplication([])
app.setDesktopFileName("io.github.estante.Test")
failed = []
with tempfile.TemporaryDirectory(prefix='estante-qt-editor-test-') as folder:
    library = Library(data_dir=folder)
    game = dict(id='test', title='Editor test', kind='custom', categories=['Fav'],
                metadata={'description':'Original', 'entity_id':'Q123'})
    library.put(game)
    controller = LibraryController([game], {}, Path(folder), allow_launch=False)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('libraryController', controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    def open_with_controller():
        try:
            controller.inputAction.emit('up')
            assert window.activeFocusItem().objectName() == 'editButton', window.activeFocusItem().objectName()
            controller.inputAction.emit('confirm')
        except Exception as error:
            failed.append(error)
            import traceback; traceback.print_exc()
            app.quit()
    def check():
        try:
            editor = window.findChild(QObject, 'gameEditor')
            assert editor is not None and editor.property('visible')
            def find_visual(item, name):
                if item.objectName() == name:
                    return item
                for child in item.childItems():
                    found = find_visual(child, name)
                    if found is not None:
                        return found
                return None
            assert window.activeFocusItem().objectName() == 'editVerticalCover'
            window.grabWindow().save('/tmp/estante-qt-editor-overview.png')
            QMetaObject.invokeMethod(editor, 'showManual')
            assert window.activeFocusItem().objectName() == 'title'
            controller.inputAction.emit('confirm')
            app.processEvents()
            keyboard=window.findChild(QObject,'virtualKeyboard')
            assert keyboard.property('visible'), 'A did not request the native keyboard'
            title=find_visual(window.contentItem(),'title')
            before=title.property('text')
            controller.inputAction.emit('right')
            assert title.property('text')==before  # Native keyboard owns controller input.
            title.setProperty('text',before+'q')  # Simulate committed text from the input method.
            controller.inputAction.emit('back')
            assert not keyboard.property('visible')
            assert title.property('text').endswith('q')
            controller.inputAction.emit('down')
            assert window.activeFocusItem().objectName() == 'developers'
            description = find_visual(window.contentItem(), 'description')
            date = find_visual(window.contentItem(), 'release_date')
            categories = find_visual(window.contentItem(), 'categories')
            description.setProperty('text', 'Saved from QML')
            date.setProperty('text', '31/02/2024')
            QMetaObject.invokeMethod(editor, 'save')
            assert controller.editing and controller.editorError
            assert description.property('text') == 'Saved from QML', 'Validation discarded draft'
            window.grabWindow().save('/tmp/estante-qt-editor.png')
            date.setProperty('text', '24/10/2026')
            categories.setProperty('text', 'Fav, Qt')
            controller.inputAction.emit('save')
            assert not controller.editing, controller.editorError
            saved = Library(data_dir=folder).games()[0]
            assert saved['metadata']['description'] == 'Saved from QML'
            assert saved['metadata']['release_date'] == '2026-10-24'
            assert saved['metadata']['entity_id'] == 'Q123'
            assert saved['categories'] == ['Fav', 'Qt']
            before = library.file.read_bytes()
            controller.edit()
            controller.cancelEdit()
            assert library.file.read_bytes() == before
            print('QT_EDITOR_INTEGRATION_OK', flush=True)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failed.append(error)
        app.quit()
    QTimer.singleShot(300, open_with_controller)
    QTimer.singleShot(1500, check)
    QTimer.singleShot(8000, app.quit)
    app.exec()
    del engine
sys.exit(bool(failed))
