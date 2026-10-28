"""Settings descriptors keep Qt and GTK on the same existing keys."""
from copy import deepcopy
from pathlib import Path
import math
from i18n import tr


def specs(settings):
    rows=[]
    def add(path,label,default,kind='text',options=None,values=None,minimum=None,maximum=None,secret=False):
        current=settings
        for key in path:
            current=current.get(key, {}) if isinstance(current,dict) else {}
        value=default if current == {} else current
        rows.append(dict(path=path,label=tr(label),value=value,type=kind,options=[tr(v) for v in options or []],values=values or [],
                         minimum=minimum,maximum=maximum,secret=secret))
    add(['layout'],'Aspecto de la biblioteca','grid','choice',['Grid','Carousel','Sense','Lista'],['grid','carousel','ps5','list'])
    add(['ui_color_mode'],'Colores de la interfaz','pastel','choice',['Tonos pastel','Tema Qt (negro/blanco)'],['pastel','system'])
    add(['language'],'Idioma','system','choice',['Idioma del sistema','Español','English'],['system','es','en'])
    add(['controller_type'],'Tipo de mando','xbox','choice',['Sony','Xbox','Nintendo'],['sony','xbox','nintendo'])
    add(['onscreen_keyboard'],'Teclado en pantalla','auto','choice',['Automático (sistema instalado)','Método de entrada del sistema','COSMIC OSK','KDE / Maliit / Plasma Keyboard','Teclado de Estante (mando)','Desactivado (teclado físico)'],['auto','system','cosmic','kde','builtin','disabled'])
    add(['keyboard_fallback'],'Usar el teclado de Estante si el del sistema no está disponible',True,'bool')
    add(['start_fullscreen'],'Iniciar a pantalla completa',True,'bool')
    add(['close_steam_on_exit'],'Cerrar Steam al salir de Estante',False,'bool')
    add(['start_heroic_on_start'],'Abrir Heroic en segundo plano al iniciar Estante',False,'bool')
    add(['close_heroic_on_exit'],'Cerrar Heroic al salir de Estante',False,'bool')
    add(['close_faugus_on_exit'],'Cerrar Faugus al salir de Estante',False,'bool')
    add(['start_faugus_on_start'],'Abrir Faugus en segundo plano al iniciar Estante',False,'bool')
    add(['start_steam_on_start'],'Abrir Steam en segundo plano al iniciar Estante',False,'bool')
    add(['show_session_history'],'Mostrar historial de sesiones',True,'bool')
    add(['check_updates_on_start'],'Comprobar actualizaciones al iniciar',False,'bool')
    add(['playing_behavior'],'Durante una partida','none','choice',['Mantener abierto','Cerrar y restaurar','Salvapantallas','Bandeja'],['none','hide','screensaver','tray'])
    add(['background_source'],'Origen del fondo','game','choice',['Juego','Global'],['game','global'])
    add(['global_background'],'Fondo global · ruta o bundled:6.png','bundled:6.png')
    add(['background_fill'],'Relleno del fondo','blur','choice',['Desenfoque','Color dominante'],['blur','dominant'])
    add(['steamgriddb_key'],'Clave SteamGridDB','','text',secret=True)
    add(['igdb_client_id'],'IGDB Client ID','')
    add(['igdb_client_secret'],'IGDB Client Secret','','text',secret=True)
    add(['screensaver_enabled'],'Activar salvapantallas',False,'bool')
    for prefix,label,default in [('screensaver_idle','Inactividad',5),('screensaver_slide','Intervalo de diapositivas',15)]:
        add([prefix+'_value'],label,default,'number',minimum=1,maximum=60)
        add([prefix+'_unit'],label+' · unidad','minutes' if prefix.endswith('idle') else 'seconds','choice',['Segundos','Minutos'],['seconds','minutes'])
    add(['screensaver_dim'],'Oscurecimiento del salvapantallas',35,'number',minimum=0,maximum=100)
    add(['screensaver_source'],'Fondos del salvapantallas','games','choice',['Juegos','Fondo de la aplicación'],['games','application'])
    backgrounds=sorted((Path(__file__).resolve().parents[1]/'assets/backgrounds').glob('*'))
    add(['screensaver_background'],'Fondo del salvapantallas','bundled:6.png','background',
        [f'Fondo {i+1}' for i,_ in enumerate(backgrounds)],['bundled:'+p.name for p in backgrounds])
    for mode,label in [('list','Lista'),('grid','Cuadrícula'),('carousel','Carrusel'),('ps5','Sense')]:
        add(['minimal_views',mode],label+' · presentación mínima',False,'bool')
        add(['background_dim',mode],label+' · oscurecimiento (%)',50,'number',minimum=0,maximum=100)
        add(['background_blur',mode],label+' · desenfoque (px)',0,'number',minimum=0,maximum=40)
        add(['cover_formats',mode],label+' · formato','square' if mode=='ps5' else 'portrait','choice',['Vertical','Cuadrado'],['portrait','square'])
        add(['hero_positions',mode],label+' · posición del fondo','full','choice',['Completo','Arriba','Abajo'],['full','top','lower'])
        add(['background_splits',mode],label+' · división del fondo','single','choice',['Único','Horizontal','Vertical','Diagonal'],['single','horizontal','vertical','diagonal'])
        add(['cover_radii',mode],label+' · redondeado',12,'number',minimum=0,maximum=40)
        add(['selection_rings',mode,'focus_ring_enabled'],label+' · borde de selección',True,'bool')
        add(['selection_rings',mode,'focus_ring_color'],label+' · color del borde','#ffffff')
        add(['selection_rings',mode,'focus_ring_width'],label+' · grosor del borde',3,'number',minimum=0,maximum=12)
        add(['selection_rings',mode,'focus_ring_radius'],label+' · radio del borde',18,'number',minimum=0,maximum=50)
        add(['show_launcher_details',mode],label+' · datos del lanzador',True,'bool')
    for key,label,default,low,high in [('list_zoom','Lista · tamaño de logos',100,50,200),('list_focus_zoom','Lista · ampliación seleccionada',150,100,250),('list_cover_zoom','Lista · tamaño de carátula',100,50,175),('carousel_zoom','Carrusel · ampliación',100,100,175),('grid_zoom','Cuadrícula · tamaño',100,50,200),('ps5_focus_size','Sense · tamaño seleccionado',250,104,320)]:
        add([key],label,default,'number',minimum=low,maximum=high)
    add(['list_side'],'Lista · posición','bottom','choice',['Izquierda','Derecha','Arriba','Abajo'],['left','right','top','bottom'])
    add(['grid_page_size'],'Cuadrícula · juegos por página',10,'number',minimum=1,maximum=100)
    add(['carousel_position'],'Posición del carrusel','top','choice',['Arriba','Abajo'],['top','bottom'])
    add(['ps5_motion'],'Sense · animación',True,'bool')
    modes={'list':'Lista','grid':'Cuadrícula','carousel':'Carrusel','ps5':'Sense'}
    for row in rows:
        path=row['path']; key=path[0]
        mode=path[1] if len(path)>1 and path[1] in modes else next((mode for mode in modes if key.startswith(mode+'_')),None)
        row['groupId']=mode or ('scan' if key.startswith(('steamgriddb','igdb')) else 'general')
        if mode:
            row['area']='background' if key in ('background_dim','background_blur','hero_positions','background_splits') else 'selection' if key=='selection_rings' else 'information' if key=='show_launcher_details' else 'presentation'
        else:
            row['area']='screensaver' if key.startswith('screensaver_') else 'services' if key.startswith(('steamgriddb','igdb')) else 'background' if key in ('background_source','global_background','background_fill') else 'general'
        if mode and ' · ' in row['label']: row['label']=row['label'].split(' · ',1)[1].capitalize()
        row['group']=tr(modes[mode]) if mode else tr('Salvapantallas' if key.startswith('screensaver_') else 'Servicios de imágenes' if key.startswith(('steamgriddb','igdb')) else 'Fondo' if key in ('background_source','global_background','background_fill') else 'General')
    order=[tr(v) for v in ['General','Fondo','Servicios de imágenes','Salvapantallas','Lista','Cuadrícula','Carrusel','Sense']]
    rows.sort(key=lambda row:order.index(row['group']))
    previous=None
    for row in rows:
        row['sectionStart']=row['group']!=previous
        previous=row['group']
    return rows


def merge_values(settings, values):
    result=deepcopy(settings)
    allowed={tuple(row['path']):row for row in specs(settings)}
    for row in values:
        path=tuple(row['path'])
        if path not in allowed: raise ValueError('Ajuste desconocido')
        rule=allowed[path]; value=row['value']
        if rule['type']=='number':
            number=float(value)
            if not math.isfinite(number) or not rule['minimum'] <= number <= rule['maximum']:
                raise ValueError(rule['label']+': valor fuera de rango')
            value=round(number)
        elif rule['type']=='choice' and value not in rule['values']: raise ValueError('Opción no válida')
        elif rule['type']=='bool': value=bool(value)
        elif rule['type'] in ('text','background'): value=str(value)
        current=result
        for key in path[:-1]:
            current=current.setdefault(key,{})
        current[path[-1]]=value
    return result


def groups(settings, mode='global'):
    """GTK settings cards, in the same columns and order as SettingsView."""
    rows=specs(settings)
    bypath={tuple(row['path']):row for row in rows}
    def group(title, keys, column=0, hint=''):
        selected=[bypath[tuple(key) if isinstance(key,list) else (key,)] for key in keys if (tuple(key) if isinstance(key,list) else (key,)) in bypath]
        return dict(title=tr(title),rows=selected,column=column,hint=tr(hint) if hint else '')
    if mode=='global':
        return [
            group('Idioma',['language'],hint='El idioma se aplicará al volver a abrir Estante.'),
            group('Tipo de mando',['controller_type']),
            dict(**group('Teclado',['onscreen_keyboard','keyboard_fallback']),keyboard=True),
            group('Inicio',['start_fullscreen','start_steam_on_start','start_faugus_on_start','start_heroic_on_start','check_updates_on_start','close_steam_on_exit','close_faugus_on_exit','close_heroic_on_exit']),
            group('Mientras juegas',['playing_behavior']),
            dict(**group('Salvapantallas',['screensaver_enabled','screensaver_idle_value','screensaver_idle_unit','screensaver_slide_value','screensaver_slide_unit','screensaver_dim','screensaver_source','screensaver_background']),compact=True),
            group('Actividad',['show_session_history'],1),
            group('Aspecto de la biblioteca',['layout','ui_color_mode'],1),
            group('Origen del fondo',['background_source','global_background'],1),
            group('Relleno del fondo',['background_fill'],1),
            dict(title=tr('Actualizaciones'),rows=[],column=1,hint='',updates=True),
        ]
    if mode=='scan':
        return [group('SteamGridDB',['steamgriddb_key']),group('IGDB · fondos 16:9',['igdb_client_id','igdb_client_secret'],1)]
    selected=[r for r in rows if r['groupId']==mode]
    def paths(*keys): return [r['path'] for r in selected if r['path'][0] in keys]
    result=[]
    if mode=='list': result.append(group('Posición de la lista',['list_side']))
    if mode=='grid': result.append(group('Paginación',['grid_page_size']))
    if mode=='carousel': result.append(group('Posición del carrusel',['carousel_position']))
    result += [group('Imagen de fondo',paths('background_dim','background_blur')),
               group('Posición del hero',paths('hero_positions')),
               group('División de los fondos',paths('background_splits'))]
    if mode=='list': result.append(group('Logos',paths('list_zoom','list_focus_zoom')))
    result += [group('Información del juego',paths('show_launcher_details'),1),
               group('Presentación',paths('minimal_views','ps5_motion'),1),
               group('Carátulas',paths('cover_formats','cover_radii','grid_zoom','carousel_zoom','ps5_focus_size','list_cover_zoom'),1),
               group('Anillo de selección',paths('selection_rings'),1)]
    return [card for card in result if card['rows']]
