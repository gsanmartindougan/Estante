"""Console theme and responsive navigation checks with an isolated library."""
import sys,time,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QObject,QUrl,QPointF
from PySide6.QtGui import QColor,QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression
from qt_app.main import LibraryController
app=QApplication([])
light=QPalette();light.setColor(QPalette.Window,QColor('white'));light.setColor(QPalette.Text,QColor('black'));app.setPalette(light)
errors=[]
def pump():
    end=time.monotonic()+.25
    while time.monotonic()<end:app.processEvents();time.sleep(.005)
with tempfile.TemporaryDirectory() as tmp:
    games=[dict(id=str(i),title=title,kind='custom',cover=str(ROOT/'assets/backgrounds/6.png'),banner=str(ROOT/'assets/backgrounds/6.png'),metadata={'description':'Elige tu próxima aventura. Todos tus juegos, en un mismo lugar.','genres':['Aventura','Exploración']}) for i,title in enumerate(['Horizonte','Órbita','Eclipse','Aurora','Origen','Nébula'])]
    c=LibraryController(games,{},Path(tmp),allow_launch=False)
    engine=QQmlApplicationEngine();engine.warnings.connect(lambda ws:errors.extend(w.toString() for w in ws))
    engine.rootContext().setContextProperty('libraryController',c);engine.load(QUrl.fromLocalFile(str(ROOT/'qt_app/Library.qml')))
    assert engine.rootObjects(),errors
    w=engine.rootObjects()[0];c.window=w
    def check_palette(expected):
        pump()
        background=w.property('color')
        assert background==expected.color(QPalette.Window)
        shade=w.findChild(QObject,'backdropShade')
        assert shade.property('shadeColor')==QColor('black')
        management=w.findChild(QObject,'managementPanel')
        dialog_color,error=QQmlExpression(engine.rootContext(),management,'background.color').evaluate()
        assert not error and dialog_color==expected.color(QPalette.Window)
        for role,name in [(QPalette.Text,'text'),(QPalette.Highlight,'highlight'),(QPalette.HighlightedText,'highlightedText'),(QPalette.Accent,'accent')]:
            actual,error=QQmlExpression(engine.rootContext(),w,'palette.'+name).evaluate()
            assert not error and actual==expected.color(role),(name,actual,expected.color(role))
        for name in ['libraryToolbar','heroSurface']:
            panel=w.findChild(QObject,name)
            assert panel.property('color')!=expected.color(QPalette.Window)
            assert panel.property('color').hslSaturationF()>0.1
            assert abs(panel.property('color').hslHueF()-expected.color(QPalette.Accent).hslHueF())<0.1
            assert panel.property('color').alpha()==(184 if name=='heroSurface' else 255)
            assert panel.opacity()==1
    check_palette(light)
    light_background=w.property('color')
    dark=QPalette(light)
    for role,color in [(QPalette.Window,'#24211f'),(QPalette.WindowText,'#f6eadd'),(QPalette.Base,'#161312'),(QPalette.Text,'#f6eadd'),(QPalette.Button,'#39302a'),(QPalette.Highlight,'#d07b39'),(QPalette.HighlightedText,'#18120c'),(QPalette.Accent,'#edb063')]:
        dark.setColor(role,QColor(color))
    app.setPalette(dark)
    check_palette(dark)
    assert w.property('color').lightnessF()<light_background.lightnessF()
    assert w.property('color').hslHueF()!=light_background.hslHueF()
    app.setPalette(light)
    check_palette(light)
    import json
    for mode in ['system','pastel','system','pastel']:
        c.manager.saveSettingValues([dict(path=['ui_color_mode'],value=mode)])
        pump()
        assert c.settingsMap['ui_color_mode']==mode
        assert json.loads((Path(tmp)/'settings.json').read_text())['ui_color_mode']==mode
        toolbar=w.findChild(QObject,'libraryToolbar')
        hero=w.findChild(QObject,'heroSurface')
        if mode=='system':
            assert w.property('color')==app.palette().color(QPalette.Window)
            assert toolbar.property('color')==app.palette().color(QPalette.Window)
            assert hero.property('color').rgb()==app.palette().color(QPalette.Window).rgb()
        else:
            check_palette(light)
        assert hero.property('color').alpha()==184 and hero.opacity()==1
    def check_details(mode):
        heading=w.findChild(QObject,'selectionHeading')
        actions=w.findChild(QObject,'gameActions')
        details=w.findChild(QObject,'detailLayout')
        cover=w.findChild(QObject,'detailCover')
        assert heading.property('visible')
        assert heading.y()+heading.height()<=actions.y()
        assert actions.y()+actions.height()<details.y()
        assert abs(heading.x()+heading.width()/2-actions.x()-actions.width()/2)<1
        assert details.x()==heading.x() and details.width()==heading.width()
        if mode=='carousel':
            assert abs(heading.x()+heading.width()/2-w.width()/2)<1
            assert heading.height()>=min(64,w.height()*0.1)
        assert not cover.property('visible')
        toolbar=w.findChild(QObject,'libraryToolbar')
        if w.height()>=900:
            original,error=QQmlExpression(engine.rootContext(),w,'originalPanelTop').evaluate()
            assert not error
            if original>=toolbar.y()+toolbar.height()+heading.height()+actions.height()+48:
                assert abs(details.y()-original)<1
        if mode=='carousel':
            strip=w.findChild(QObject,'libraryStrip')
            assert abs(strip.height()-min(420,w.height()*0.4))<1
            tile,error=QQmlExpression(engine.rootContext(),strip,'selectedItem()').evaluate()
            assert not error and tile is not None
            assert tile.width()>=min(280,strip.height()*0.7,strip.width()*0.24)-1
            center=tile.mapToScene(QPointF(tile.width()/2,tile.height()/2))
            assert abs(center.x()-w.width()/2)<2,(center,w.width())
    for width,height in [(800,600),(1280,720),(1440,900)]:
        w.resize(width,height)
        toolbar=w.findChild(QObject,'libraryToolbar')
        assert toolbar.height()==52
        assert toolbar.width()<width-31
        for mode in ['list','grid','carousel','ps5']:
            c.changeView(mode);pump()
            for name in ['search','settingsToolbarButton','playButton','editButton','libraryStrip']:
                item=w.findChild(QObject,name);assert item is not None,name
                assert item.width()>0 and item.height()>0,(name,width,mode)
                point=item.mapToScene(item.boundingRect().topLeft())
                assert point.x()>=0 and point.x()+item.width()<=width+1,(name,width,mode,point.x(),item.width())
                assert point.y()>=0 and point.y()+item.height()<=height+1,(name,height,mode,point.y(),item.height())
            c.move(1);pump()
            if mode in ['grid','carousel']:
                check_details(mode)
            if mode=='carousel':
                c.settings['carousel_position']='bottom'
                c.appearanceChanged.emit();pump()
                check_details(mode)
                c.settings['carousel_position']='top'
                c.appearanceChanged.emit();pump()
    c.changeView('ps5');pump()
    c.search('no-results');pump();assert c.selected==-1
    c.search('');pump();c.inputAction.emit('menu');pump()
    assert w.findChild(QObject,'managementPanel').property('visible')
    assert not errors,errors
    c.manager.shutdown();c.idle_timer.stop();w.close();del engine
print('CONSOLE_OK: live light/dark system palettes, custom accent, saved pastel/system choice, translucent info panel and compact toolbar, 3 sizes, 4 layouts, navigation and settings')
