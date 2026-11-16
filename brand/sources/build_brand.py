"""Rebuild the proposed identity with FigCraft 0.11.2; no generated media.

FIGCRAFT_CLI=/path/to/figcraft-cli python brand/sources/build_brand.py
Needs the installed Noto Sans Regular and Bold fonts. Run from any directory.
"""
import base64
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / 'brand'
CLI = os.environ.get('FIGCRAFT_CLI', str(ROOT / '.artcraft-work/figcraft-0.11.2/squashfs-root/usr/bin/figcraft-cli'))
OUT = BRAND / 'sources/estante-identity.figcraft'
DEST = BRAND
LANGUAGE = 'es'
EN = {
 'Estante':'Estante',
 'SISTEMA VISUAL / PROPUESTA 01':'VISUAL SYSTEM / PROPOSAL 01',
 'Tu biblioteca.\nTu próxima partida.':'Your library.\nYour next game.',
 'Una biblioteca de juegos para Linux.':'A game library for Linux.',
 '01 / COLOR CON FUNCIÓN':'01 / COLOR WITH A PURPOSE',
 'Noche':'Night','Superficie':'Surface','Azul del icono¹':'Icon blue¹',
 'Azul accesible':'Accessible blue','Niebla':'Mist','Papel':'Paper',
 '02 / TIPOGRAFÍA':'02 / TYPOGRAPHY','03 / DOS DIRECCIONES':'03 / TWO DIRECTIONS',
 'Biblioteca · Acción · ¿Jugamos?\nÑñ / 0123456789 / ¡A jugar!':'Library · Action · Ready to play?\nÑñ / 0123456789 / Let’s play!',
 'A · Biblioteca nocturna':'A · Night library','Recomendada':'Recommended',
 'La colección ocupa el centro.':'The collection takes center stage.',
 'B · Catálogo claro':'B · Light catalog','Variante editorial':'Editorial variant',
 'Guías y documentación.':'Guides and documentation.',
 '¹ Muestra modal del azul raster; el original contiene variaciones. Icono existente conservado.':'¹ Modal blue sample from the raster icon; original colors vary. Existing icon preserved.',
 'ESTANTE / IDENTIDAD PROPUESTA / 28 OCT 2026':'ESTANTE / PROPOSED IDENTITY / 28 OCT 2026',
 'BIBLIOTECA DE JUEGOS PARA LINUX':'GAME LIBRARY FOR LINUX',
 'Tu biblioteca.\nTu próxima\npartida.':'Your library.\nYour next\ngame.',
 'Steam · Faugus · Heroic · Juegos locales':'Steam · Faugus · Heroic · Local games',
 'Mando, teclado y ratón.':'Gamepad, keyboard and mouse.',
 'TU COLECCIÓN, A TU MANERA':'YOUR COLLECTION, YOUR WAY',
 'Un lugar\npara volver\na jugar.':'A place\nto come back\nand play.',
 'Reúne tus juegos en Linux.':'Bring your games together on Linux.',
 'Y tus juegos locales.':'And your local games.',
 'ESTANTE 0.3.0 / VISTA LISTA':'ESTANTE 0.3.0 / LIST VIEW',
 'La colección es la protagonista.':'Your collection takes center stage.',
 'Cuatro apariencias. Una biblioteca.':'Four layouts. One library.',
 'Captura real · Lista · Tonos pastel predeterminados · Sin tema Qt personalizado.':'Real capture · List view · Default pastel colors · No custom Qt theme.',
 'Tu biblioteca. Tu próxima partida.':'Your library. Your next game.',
}
C = {k: v['hex'] for k, v in json.loads((BRAND / 'brand-tokens.json').read_text())['colors'].items()}
FRAMES = [
    ('01-identidad', 1600, 1200, C['paper']),
    ('02-portada', 1600, 900, C['ink']),
    ('03-anuncio', 1080, 1080, C['ink']),
    ('04-producto', 1600, 1320, C['ink']),
    ('05-firma', 1000, 280, C['ink']),
]

def run(commands, initial=False):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', encoding='utf-8') as f:
        json.dump(commands, f, ensure_ascii=False); f.flush()
        args = [CLI, 'run', f.name, '--out', str(OUT)]
        if not initial: args += ['--in', str(OUT)]
        r = subprocess.run(args, text=True, capture_output=True, check=True)
        rows = [json.loads(s) for s in r.stdout.splitlines() if s.startswith('{')]
        assert all(row.get('ok') for row in rows), r.stdout
        return rows

def make():
    commands = []
    x = 0
    for name, w, h, bg in FRAMES:
        commands.append(dict(command='frame.create', params=dict(name=name, x=x, y=0, width=w, height=h, props=dict(fill=bg))))
        x += w + 120
    ids = [r['result']['id'] for r in run(commands, initial=True)]
    commands = []

    def rect(p, x, y, w, h, fill, radius=0, stroke=None):
        props = dict(fill=fill, cornerRadius=radius)
        if stroke: props.update(stroke=stroke, strokeWeight=2)
        commands.append(dict(command='node.create', params=dict(type='rectangle', name='Superficie', parent=p, x=x, y=y, width=w, height=h, props=props)))

    def text(p, s, x, y, size=24, color=None, bold=False, width=None):
        if LANGUAGE == 'en': s = EN.get(s,s)
        props = dict(fontFamily='Noto Sans', fontStyle='Bold' if bold else 'Regular', fontSize=size, lineHeight=round(size*1.24), fill=color or C['paper'])
        params = dict(text=s, x=x, y=y, parent=p, props=props)
        if width: params['width'] = width
        commands.append(dict(command='text.create', params=params))

    def image(p, path, x, y, w, h):
        data = base64.b64encode(Path(path).read_bytes()).decode()
        commands.append(dict(command='image.place', params=dict(data=data, x=x, y=y, width=w, height=h, parent=p, mode='fit')))

    def mark(p, x, y, size=108, title=48):
        image(p, BRAND/'originals/estante-icon-original.png', x, y, size, size*1226/1283)
        text(p, 'Estante', x+size+20, y+size*.19, title, bold=True)

    def label(p, s, x, y, dark=False):
        text(p, s, x, y, 18, C['blueLight'] if dark else C['muted'], True)

    def shelf(p, x, y, scale=1):
        # Explicit rectangular geometry: editorial motif, not an alternative logo.
        for i, (h, fill) in enumerate([(140,C['panel']),(220,C['blue']),(170,C['paper']),(120,C['panel'])]):
            rect(p, x+i*110*scale, y+(240-h)*scale, 92*scale, h*scale, fill, 12*scale)
            if i != 2: rect(p,x+(i*110+15)*scale,y+(260-h)*scale,38*scale,5*scale,C['paper'],2*scale)
        rect(p,x,y+258*scale,430*scale,5*scale,C['border'],2*scale)

    # Brand board, including a concrete alternative direction.
    p=ids[0]
    rect(p,0,0,1600,520,C['ink'])
    mark(p,64,42,104,48)
    label(p,'SISTEMA VISUAL / PROPUESTA 01',1040,68)
    text(p,'Tu biblioteca.\nTu próxima partida.',64,190,72,bold=True)
    text(p,'Una biblioteca de juegos para Linux.',68,400,28,C['muted'])
    shelf(p,1090,202,.98)
    label(p,'01 / COLOR CON FUNCIÓN',64,560,True)
    swatches=[('Noche','ink'),('Superficie','panel'),('Azul del icono¹','blue'),('Azul accesible','blueLight'),('Niebla','muted'),('Papel','paper')]
    for i,(name,key) in enumerate(swatches):
        xx=64+i*248
        rect(p,xx,608,232,96,C[key],12,C['border'] if key=='paper' else None)
        text(p,name,xx,720,19,C['ink'],True)
        text(p,C[key],xx,750,19,C['blueLight'])
    label(p,'02 / TIPOGRAFÍA',64,814,True)
    text(p,'Noto Sans',64,850,52,C['ink'],True)
    text(p,'Regular 400 · Bold 700',66,920,23,C['ink'])
    text(p,'Biblioteca · Acción · ¿Jugamos?\nÑñ / 0123456789 / ¡A jugar!',66,970,24,C['ink'])
    rect(p,630,814,1,250,C['muted'])
    label(p,'03 / DOS DIRECCIONES',680,814,True)
    rect(p,680,858,398,188,C['ink'],16)
    text(p,'A · Biblioteca nocturna',704,880,23,bold=True)
    text(p,'Recomendada',704,924,20,C['blue'])
    text(p,'La colección ocupa el centro.',704,978,18,C['muted'])
    rect(p,1100,858,436,188,'#FFFFFF',16,C['border'])
    text(p,'B · Catálogo claro',1124,880,23,C['ink'],True)
    text(p,'Variante editorial',1124,924,20,C['blueLight'])
    text(p,'Guías y documentación.',1124,978,18,C['ink'])
    text(p,'¹ Muestra modal del azul raster; el original contiene variaciones. Icono existente conservado.',64,1090,18,C['blueLight'])
    text(p,'ESTANTE / IDENTIDAD PROPUESTA / 28 OCT 2026',64,1150,16,C['ink'],True)

    # Landscape communication composition: no external platform claims.
    p=ids[1]
    mark(p,72,54,108,50)
    label(p,'BIBLIOTECA DE JUEGOS PARA LINUX',72,240)
    text(p,'Tu biblioteca.\nTu próxima\npartida.',64,290,100,bold=True)
    shelf(p,985,310,1.13)
    text(p,'Steam · Faugus · Heroic · Juegos locales',72,772,26,C['muted'])
    rect(p,72,838,1456,2,C['border'])
    text(p,'Mando, teclado y ratón.',1050,792,22,C['muted'])

    # Square recomposition with different hierarchy, not a scaled landscape.
    p=ids[2]
    mark(p,64,44,104,48)
    label(p,'TU COLECCIÓN, A TU MANERA',64,230)
    text(p,'Un lugar\npara volver\na jugar.',58,288,92,bold=True)
    text(p,'Reúne tus juegos en Linux.',64,680,32,C['muted'])
    for i,s in enumerate(['Steam','Faugus','Heroic']):
        rect(p,64+i*304,770,280,82,C['panel'],14)
        text(p,s,88+i*304,791,28,bold=True)
    rect(p,64,890,952,4,C['blue'])
    text(p,'Y tus juegos locales.',64,936,24,C['muted'])

    # Real product screenshot kept intact, with explicit editorial framing.
    p=ids[3]
    mark(p,64,42,104,48)
    label(p,'ESTANTE 0.3.0 / VISTA LISTA',1100,78)
    text(p,'La colección es la protagonista.',64,204,58,bold=True)
    text(p,'Cuatro apariencias. Una biblioteca.',66,298,28,C['muted'])
    rect(p,56,376,1488,845,C['panel'],18)
    image(p,BRAND/'originals'/('estante-list-default-en.png' if LANGUAGE=='en' else 'estante-list-default.png'),96,384,1408,792)
    text(p,'Captura real · Lista · Tonos pastel predeterminados · Sin tema Qt personalizado.',64,1240,20,C['muted'])

    p=ids[4]
    mark(p,64,40,188,88)
    text(p,'Tu biblioteca. Tu próxima partida.',272,180,27,C['muted'])
    run(commands)
    for (name,*_), fid in zip(FRAMES,ids):
        for fmt in ['png','svg']:
            subprocess.run([CLI,'export',str(OUT),'--node',str(fid),'--format',fmt,'-o',str(DEST/'exports'/f'{name}.{fmt}')],check=True)
    subprocess.run([CLI,'info',str(OUT),'--json'],check=True,stdout=open(DEST/'sources/figcraft-info.json','w'))
    print(f'Created {OUT}; {len(commands)} editable operations.')

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--language',choices=['es','en'],default='es');args=parser.parse_args()
    if args.language:
        LANGUAGE=args.language;DEST=BRAND/LANGUAGE
        for folder in ['exports','sources']: (DEST/folder).mkdir(parents=True,exist_ok=True)
        OUT=DEST/'sources/estante-identity.figcraft'
    make()
