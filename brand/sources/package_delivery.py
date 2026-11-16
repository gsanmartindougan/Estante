"""Create local galleries and portable Spanish/English delivery ZIPs."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import argparse
import html
import json
import re
from promo_plan import CLIPS

ROOT=Path(__file__).resolve().parents[2];BRAND=ROOT/'brand'

def gallery(lang):
    es=lang=='es'
    words=dict(title='Estante · Biblioteca de recursos' if es else 'Estante · Asset library',
               intro='Diez temas, dos formatos. Clips de 20 segundos con subtítulos integrados.' if es else 'Ten topics, two formats. Twenty-second clips with burned-in captions.',
               brand='Identidad visual' if es else 'Visual identity',videos='Clips promocionales' if es else 'Promotional clips',
               guide='Guía de marca' if es else 'Brand guide',native='Fuente de FigCraft' if es else 'FigCraft source',
               notes='Notas de producción' if es else 'Production notes',download='Descargar MP4' if es else 'Download MP4',
               captions='Subtítulos SRT' if es else 'SRT captions',
               horizontal='Horizontal · 1920 × 1080' if es else 'Landscape · 1920 × 1080',vertical='Vertical · 1080 × 1920' if es else 'Portrait · 1080 × 1920')
    css='''body{margin:0;background:#101923;color:#f4f7fb;font:17px/1.6 system-ui,sans-serif}main{max-width:1260px;margin:auto;padding:48px 28px}h1{font-size:44px;line-height:1.15}h2{margin-top:56px}h3{font-size:22px;margin:0 0 16px}a{color:#85c6ff}nav,.links{display:flex;gap:20px;flex-wrap:wrap}.assets{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}.assets img{width:100%;height:250px;object-fit:contain;background:#192638}article{background:#192638;border-radius:16px;padding:24px;margin:24px 0}.formats{display:grid;grid-template-columns:1fr 1fr;gap:24px}video{display:block;width:100%;background:#101923;max-height:620px}summary{cursor:pointer;font-size:20px;font-weight:600;margin-bottom:20px}small,p{color:#aab8c9}select,button{font:inherit}footer{border-top:1px solid #667d96;margin-top:48px;padding-top:24px}@media(max-width:760px){.formats{grid-template-columns:1fr}h1{font-size:34px}}'''
    chunks=[f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{words["title"]}</title><style>{css}</style><main>',
            '<nav><a href="index.es.html">Español</a><a href="index.en.html">English</a></nav>',
            f'<h1>{words["title"]}</h1><p>{words["intro"]}</p>',
            f'<h2>{words["brand"]}</h2><div class="links"><a href="{lang}/brand-guide.md">{words["guide"]}</a><a href="{lang}/brand-tokens.json">Tokens JSON</a><a href="{lang}/sources/estante-identity.figcraft">{words["native"]}</a></div><div class="assets">']
    names=['Sistema visual','Portada','Anuncio','Producto','Firma'] if es else ['Visual system','Cover','Announcement','Product','Signature']
    for name,file in zip(names,['01-identidad','02-portada','03-anuncio','04-producto','05-firma']):
        chunks.append(f'<figure><a href="{lang}/exports/{file}.png"><img loading="lazy" src="{lang}/exports/{file}.png" alt="{name}"></a><figcaption>{name} · <a href="{lang}/exports/{file}.svg">SVG</a></figcaption></figure>')
    chunks.append(f'</div><h2>{words["videos"]}</h2><a href="promo/README.{lang}.md">{words["notes"]}</a>')
    for clip,titles,_ in CLIPS:
        title=titles[0 if es else 1];chunks.append(f'<article><details><summary>{clip[:2]} · {html.escape(title)}</summary><div class="formats">')
        for aspect in ['horizontal','vertical']:
            path=f'promo/{lang}/{aspect}/{clip}'
            chunks.append(f'<section><h3>{words[aspect]}</h3><video controls playsinline preload="none" poster="{path}.jpg" src="{path}.mp4" aria-label="{html.escape(title)}"></video><div class="links"><a href="{path}.mp4" download>{words["download"]}</a><a href="{path}.srt" download>{words["captions"]}</a></div></section>')
        chunks.append('</div></details></article>')
    chunks.append('<footer>Estante · 0.3.0 · 2026</footer></main></html>')
    (BRAND/f'index.{lang}.html').write_text('\n'.join(chunks))

def make_zip(path,items,language=None):
    with ZipFile(path,'w',ZIP_DEFLATED,compresslevel=5) as z:
        seen=set()
        for item in items:
            for f in ([item] if item.is_file() else sorted(item.rglob('*'))):
                if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ['.pyc','.log']:
                    name=str(f.relative_to(BRAND.parent))
                    if name not in seen:
                        if language and f.name==f'index.{language}.html':
                            text=f.read_text()
                            other='en' if language=='es' else 'es'
                            text=re.sub(r'<a href="index\.'+other+r'\.html">[^<]+</a>','',text)
                            z.writestr(name,text)
                        else:z.write(f,name)
                        seen.add(name)
    with ZipFile(path) as z:assert z.testzip() is None
    print(path.name,round(path.stat().st_size/1048576,1),'MiB',len(seen),'files')

def main():
    parser=argparse.ArgumentParser(description='Refresh current galleries; optionally export one current bundle.')
    parser.add_argument('--output',type=Path,help='Optional ZIP destination. No archive is created by default.')
    args=parser.parse_args()
    for lang in ['es','en']:gallery(lang)
    # Validate all local gallery media/file links before delivery.
    for lang in ['es','en']:
        for target in re.findall(r'(?:href|src|poster)="([^"]+)"',(BRAND/f'index.{lang}.html').read_text()):
            assert (BRAND/target).is_file(),target
    if args.output:
        destination=args.output.expanduser().resolve()
        items=[BRAND/name for name in ['es','en','originals','sources','promo','social',
               'index.es.html','index.en.html','brand-tokens.json','README.md','README.en.md']]
        if any(item.is_dir() and destination.is_relative_to(item) for item in items):
            parser.error('Place the output ZIP outside the directories being packaged.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        make_zip(destination,items)

if __name__=='__main__':main()
