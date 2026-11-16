"""Record genuine UI shots in isolated profiles; no imports, launches or user writes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
for key in ('QT_QPA_PLATFORMTHEME','QT_STYLE_OVERRIDE','QT_QUICK_CONTROLS_CONF'):
    os.environ.pop(key,None)
os.environ.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Fusion',QT_SCALE_FACTOR='1')
from PySide6.QtCore import QObject,QUrl,QPointF
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression
from core.library import Library
from core.i18n import set_language,tr
from qt_app.main import LibraryController
from qt_app.images import ArtworkProvider
from qt_app.translation import Translator
from qt_app.launcher_processes import running_clients,CLIENT_NAMES
from tools.showcase import Recorder,rgba_pixels,descendants

def main():
    parser=argparse.ArgumentParser();parser.add_argument('language',choices=['es','en']);parser.add_argument('--only',nargs='*');args=parser.parse_args()
    out=ROOT/'brand/promo/media'/args.language;out.mkdir(parents=True,exist_ok=True)
    profile=Path.home()/'.local/share/estante'
    original={name:(profile/name).read_bytes() for name in ['library.json','settings.json']}
    app=QApplication([]);app.setStyle('Fusion');app.setPalette(app.style().standardPalette())
    set_language(args.language);translator=Translator(app);app.installTranslator(translator)
    with tempfile.TemporaryDirectory(prefix='estante-promo-') as temp:
        data=Path(temp);(data/'library.json').write_bytes(original['library.json'])
        settings=dict(layout='list',language=args.language,ui_color_mode='pastel',
                      cover_radii={m:0 for m in ['list','grid','carousel','ps5']},
                      show_launcher_details={m:False for m in ['list','grid','carousel','ps5']},
                      check_updates_on_start=False,onscreen_keyboard='builtin',keyboard_fallback=True)
        (data/'settings.json').write_text(json.dumps(settings))
        library=Library(data_dir=data)
        c=LibraryController(library.games(),settings,data,allow_launch=False,allow_edit=True)
        running=running_clients();c.launchers.apply_snapshot({k:'open' if k in running else 'closed' for k in CLIENT_NAMES},'')
        engine=QQmlApplicationEngine();engine.addImageProvider('artwork',ArtworkProvider(data/'cache'));c.use_image_provider=True
        engine.rootContext().setContextProperty('libraryController',c);engine.load(QUrl.fromLocalFile(str(ROOT/'qt_app/Library.qml')))
        assert engine.rootObjects();w=engine.rootObjects()[0];c.window=w;w.resize(1920,1080)
        def find(name):
            obj=w.findChild(QObject,name);assert obj is not None,name;return obj
        def pump(seconds=.3):
            end=time.monotonic()+seconds
            while time.monotonic()<end:app.processEvents();time.sleep(.005)
        pump(1)
        management=find('managementPanel');editor=find('gameEditor');keyboard=find('virtualKeyboard')
        blood=next(i for i,g in enumerate(c.catalog.visible) if g['title'].casefold()=='bloodborne')
        def reset(mode='list'):
            c.recordActivity();management.close();editor.close();c.cancelEdit();c.search('');c.category(0);c.changeView(mode);c.select(blood);pump(.2)
        def section(n,groups=()):
            management.openSection(n,False);pump(.15)
            wanted={tr(g) for g in groups}
            for item in descendants(w.contentItem()):
                if item.objectName().startswith('settingsGroup:'):
                    item.setProperty('expanded',item.objectName().split(':',1)[1] in wanted)
                if item.objectName().startswith('categoryHeader:') and groups==('categories',):
                    item.parent().setProperty('expanded',True)
            pump(.15)
        def edit_page(page):
            c.edit();pump(.1)
            if page=='manual':editor.showManual()
            else:editor.setProperty('page',page)
            pump(.1)
        def configure(values):
            c.settings.update(values);c.appearanceChanged.emit()
        def search_text(value):
            find('search').setProperty('text',value);c.search(value)
        def show_keyboard():
            keyboard.openBuiltin(find('search'))
        def keyboard_step(action):keyboard.navigate(action)
        # Each raw shot is six seconds at real speed. No source range is stretched.
        scenes=[
            ('list',lambda:reset('list'),[(2,lambda:c.move(1)),(4,lambda:c.move(-1))]),
            ('grid',lambda:reset('grid'),[(2,lambda:c.move(1)),(4,lambda:c.inputAction.emit('grid_page_next'))]),
            ('carousel',lambda:reset('carousel'),[(2,lambda:c.move(1)),(4,lambda:c.move(1))]),
            ('sense',lambda:reset('ps5'),[(2,lambda:c.move(1)),(4,lambda:c.move(-1))]),
            ('search',lambda:reset('list'),[(1,lambda:search_text('D')),(1.5,lambda:search_text('Da')),(2,lambda:search_text('Dark')),(4.5,lambda:search_text(''))]),
            ('categories',lambda:(reset(),section(3,('categories',))),[]),
            ('imports',lambda:(reset(),section(2)),[]),
            ('local',lambda:(reset(),section(0)),[]),
            ('editor',lambda:(reset(),edit_page('overview')),[(3,lambda:edit_page('manual'))]),
            ('artwork',lambda:(reset(),edit_page('overview')),[(3,lambda:editor.artwork(0,False))]),
            ('activity',lambda:(reset(),edit_page('activity')),[]),
            ('controls',lambda:(reset(),section(4,('Idioma','Tipo de mando','Teclado'))),[]),
            ('keyboard',lambda:(reset(),show_keyboard()),[(2,lambda:keyboard_step('right')),(2.6,lambda:keyboard_step('right')),(3.2,lambda:keyboard_step('confirm'))]),
            ('appearance',lambda:(reset(),section(7,('Posición de la lista','Logos','Carátulas','Anillo de selección'))),[]),
            ('background',lambda:(reset(),section(7,('Imagen de fondo','Posición del hero','División de los fondos'))),[]),
            ('startup',lambda:(reset(),section(4,('Inicio',))),[]),
            ('playing',lambda:(reset(),section(4,('Mientras juegas',))),[]),
            ('screensaver',lambda:(reset(),configure(dict(screensaver_slide_value=2,screensaver_slide_unit='seconds')),c.previewScreensaver()),[]),
            ('updates',lambda:(reset(),section(4,('Actualizaciones','Idioma'))),[]),
        ]
        results=[]
        try:
            for name,setup,actions in scenes:
                if args.only and name not in args.only: continue
                setup();pump(.6)
                if name=='list':
                    cover=find('detailCover');assert cover.property('visible') and cover.width()>0 and cover.property('source').toString()
                path=out/(name+'.mp4');path.unlink(missing_ok=True)
                recorder=Recorder(path,1920,1080,24,6)
                started=time.monotonic();actions=list(actions);next_frame=started
                try:
                    while (elapsed:=time.monotonic()-started)<6:
                        while actions and actions[0][0]<=elapsed:
                            _,action=actions.pop(0);action()
                        app.processEvents()
                        if time.monotonic()>=next_frame:
                            recorder.submit(elapsed,rgba_pixels(w.grabWindow(),1920,1080));next_frame+=1/24
                        else:time.sleep(.002)
                    recorder.finish()
                    image=w.grabWindow();assert image.save(str(out/(name+'.png')))
                    if name=='list':
                        dest=ROOT/'brand/originals'/('estante-list-default-en.png' if args.language=='en' else 'estante-list-default.png')
                        image.save(str(dest))
                    results.append(dict(scene=name,duration=6,fps=24,droppedSamples=recorder.dropped,language=args.language))
                    print(args.language,name,'recorded',flush=True)
                finally:
                    if name=='keyboard':keyboard.navigate('back')
            (out/'recording.json').write_text(json.dumps(results,indent=2)+'\n')
        finally:
            c.manager.shutdown();c.idle_timer.stop()
            del engine
    for name,value in original.items():assert (profile/name).read_bytes()==value
    print(args.language,'USER_PROFILE_UNCHANGED',flush=True)

if __name__=='__main__':main()
