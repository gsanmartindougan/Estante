"""Single GTK-style editor drawer, tested without compositor windows or network."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject,QUrl,QMetaObject
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from qt_app.main import LibraryController
from library import Library
from i18n import set_language
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test');set_language('es')
def pump(seconds=.15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:app.processEvents();time.sleep(.005)
def visual(item):
    yield item
    for child in item.childItems():yield from visual(child)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);library=Library(data_dir=root)
    picture=QImage(120,180,QImage.Format_RGB32);picture.fill(0xff627c99);picture.save(str(root/'cover.png'))
    source=str(root/'cover.png')
    hero=QImage(3840,2160,QImage.Format_RGB32);hero.fill(0xff446688);hero.save(str(root/'hero.png'))
    secondary=QImage(1920,1080,QImage.Format_RGB32);secondary.fill(0xff885544);secondary.save(str(root/'secondary.png'))
    script=root/'example.sh';script.write_text('#!/bin/sh\nexit 0\n');script.chmod(0o755)
    game=dict(id='one',title='Example',kind='local',path=str(script),cover=source,banner=str(root/'hero.png'),banner_secondary=str(root/'secondary.png'),categories=['Fav'])
    library.put(game)
    controller=LibraryController([game],{'language':'es'},root,allow_launch=False)
    engine=QQmlApplicationEngine();errors=[]
    engine.warnings.connect(lambda rows:errors.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('libraryController',controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    window=engine.rootObjects()[0];controller.window=window;window.resize(1600,1000);pump()
    def find(name):return next(item for item in visual(window.contentItem()) if item.objectName()==name)
    def same_panel(page):
        assert editor.property('visible') and editor.property('page')==page
        assert not window.findChild(QObject,'managementPanel').property('visible')
        assert len(app.topLevelWindows())==1
    def done():
        deadline=time.monotonic()+5
        while controller.manager.busy and time.monotonic()<deadline:pump(.02)
        pump();assert not controller.manager.busy
    controller.settings['background_source']='global'
    controller.settings['global_background']=''
    assert controller.game['banner']=='' and controller.editorImages['banner']==QUrl.fromLocalFile(str(root/'hero.png')).toString()
    assert controller.editorImages['secondary']==QUrl.fromLocalFile(str(root/'secondary.png')).toString()
    controller.inputAction.emit('save');pump();editor=window.findChild(QObject,'gameEditor');same_panel('overview')
    find('editVerticalCover').forceActiveFocus();controller.inputAction.emit('confirm');pump();same_panel('artwork')
    find('editorLocalImages').forceActiveFocus();controller.inputAction.emit('confirm');pump()
    find('editorBrowseFiles').forceActiveFocus();controller.inputAction.emit('confirm');pump();same_panel('artwork')
    find('editorLocalImages').forceActiveFocus();controller.inputAction.emit('confirm');pump()
    with patch('qt_app.management.SteamGridDB.search',return_value=[{'id':1,'name':'Example'}]), patch('qt_app.management.SteamGridDB.grids',return_value=[{'url':QUrl.fromLocalFile(source).toString(),'width':600,'height':900} for _ in range(12)]), patch('qt_app.management.SteamGridDB.download',return_value=source):
        find('editorSearchArtwork').forceActiveFocus();controller.inputAction.emit('confirm');done()
        gallery=find('editorArtworkGallery');assert gallery.hasActiveFocus()
        controller.inputAction.emit('confirm');done();assert gallery.property('count')==12
        for action in ['right','down']:controller.inputAction.emit(action)
        assert gallery.property('currentIndex')==3
        window.grabWindow().save('/tmp/estante-editor-single-gallery.png')
        assert find('saveEditorArtwork').property('visible')
        controller.inputAction.emit('save');done();same_panel('overview')
    editor.setProperty('metadataSearch',True);editor.setProperty('page','artwork');pump();same_panel('artwork')
    with patch('qt_app.management.GameMetadata.search',return_value=[{'id':'Q123','name':'Updated Example'}]), patch('qt_app.management.GameMetadata.fetch',return_value={'description':'New online description'}):
        find('editorSearchArtwork').forceActiveFocus();controller.inputAction.emit('confirm');done()
        assert find('saveEditorArtwork').property('visible')
        controller.inputAction.emit('save');done();same_panel('overview')
    # Real images with unequal native dimensions must never determine column width.
    for width in (1280,1600,2560):
        window.resize(width,1440);pump(.2)
        previews=find('editorBackgroundPreviews')
        first=find('editorBackgroundPreview0');second=find('editorBackgroundPreview1')
        assert abs(first.width()-second.width())<1
        assert second.x()+second.width()<=previews.width()+1
        assert first.width()<editor.property('width')*.51
        for index in (0,1):
            image=find('editorBackgroundImage'+str(index))
            assert abs(image.height()-image.width()*9/16)<1
    editor.setProperty('metadataSearch',True);editor.setProperty('page','artwork');pump();same_panel('artwork')
    from metadata import MetadataRateLimitError
    with patch('qt_app.management.GameMetadata.search',side_effect=MetadataRateLimitError('limiting')),patch('qt_app.management.SteamArtwork.search',return_value=[{'id':42,'name':'Steam Example'}]),patch('qt_app.management.SteamArtwork.metadata',return_value={'developers':['Steam Studio'],'release_date':'2024-08-19','source':'https://store.steampowered.com/app/42/'}):
        before=Library(data_dir=root).games()[0]
        find('editorSearchArtwork').forceActiveFocus();controller.inputAction.emit('confirm');done()
        assert 'Steam' in controller.manager.message
        assert controller.manager.results[0]['provider']=='metadata_steam'
        assert Library(data_dir=root).games()[0]==before  # Search must never apply the first result automatically.
        controller.inputAction.emit('save');done();same_panel('overview')
        stored=Library(data_dir=root).games()[0]
        assert stored['metadata']['developers']==['Steam Studio']
        assert stored['metadata']['description']=='New online description'
        assert stored['categories']==['Fav'] and stored['banner']==before['banner']
    QMetaObject.invokeMethod(editor,'showManual');pump();same_panel('manual')
    assert find('description').property('text')=='New online description'

    controller.inputAction.emit('back');pump();same_panel('overview')
    QMetaObject.invokeMethod(editor,'showCategories');pump();same_panel('categories')
    assert find('saveGameCategories').property('visible')
    controller.inputAction.emit('back');pump();same_panel('overview')
    for page in ['execution','activity']:
        editor.setProperty('page',page);pump();same_panel(page)
        if page=='execution':
            assert find('saveGameExecution').property('visible')
            controller.inputAction.emit('save');done()
            assert controller.manager.message=='Juego guardado',controller.manager.message
        controller.inputAction.emit('back');pump();same_panel('overview')
    window.grabWindow().save('/tmp/estante-editor-single-overview.png')
    for profile,label in [('sony','△'),('xbox','Y'),('nintendo','X')]:
        controller.settings['controller_type']=profile
        assert label in controller.editorSaveHint
    before=library.file.read_bytes()
    controller.inputAction.emit('save');pump();assert not controller.editing
    assert library.file.read_bytes()==before  # Artwork is already persisted; never overwrite online metadata.
    controller.edit();pump();QMetaObject.invokeMethod(editor,'showCategories');pump()
    assert find('editorSave').property('visible')
    controller.inputAction.emit('save');pump();assert not controller.editing
    assert Library(data_dir=root).games()[0]['categories']==['Fav']
    controller.manager.shutdown();controller.idle_timer.stop();window.close();pump();del engine
assert not errors,'\n'.join(errors)
print('QT_SINGLE_EDITOR_PANEL_OK: artwork gallery/controller/import, metadata/manual/categories/execution/activity, one window, no network')
