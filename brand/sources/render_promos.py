"""Reproducible silent bilingual promos, native FilmCraft caption projects and SRT.

The clean master contains the montage/layout. FilmCraft captions stay editable.
Raw UI shots and this plan retain the original cuts. Final caption burn: FFmpeg.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import textwrap
from fractions import Fraction
from PIL import Image,ImageDraw,ImageFont
from promo_plan import CLIPS

ROOT=Path(__file__).resolve().parents[2];BRAND=ROOT/'brand';BASE=BRAND/'promo'
FONT='/usr/share/fonts/noto/NotoSans-Regular.ttf';BOLD='/usr/share/fonts/noto/NotoSans-Bold.ttf'
FILM=ROOT/'.artcraft-work/filmcraft-0.13.0/squashfs-root/usr/bin/filmcraft-cli'
FPS=24;TICKS=254016000000

def call(args,**kw):
    return subprocess.run([str(a) for a in args],check=True,text=True,capture_output=True,**kw)

def timecode(seconds,ass=False):
    h=int(seconds//3600);m=int(seconds//60)%60;s=int(seconds)%60
    return f'{h}:{m:02}:{s:02}.00' if ass else f'{h:02}:{m:02}:{s:02},000'

def card(path,title,lang,aspect,closing=False):
    w,h=(1920,1080) if aspect=='horizontal' else (1080,1920)
    im=Image.new('RGB',(w,h),'#101923');d=ImageDraw.Draw(im)
    icon=Image.open(BRAND/'originals/estante-icon-original.png').convert('RGBA');icon.thumbnail((150,145))
    xx=96 if aspect=='horizontal' else 72
    im.paste(icon,(xx,90),icon);d.text((xx+175,105),'Estante',font=ImageFont.truetype(BOLD,64),fill='#F4F7FB')
    size=86 if aspect=='horizontal' else 78;maxchars=32 if aspect=='horizontal' else 20
    lines=textwrap.wrap(title,maxchars)
    y=410 if aspect=='horizontal' else 620
    for line in lines:d.text((xx,y),line,font=ImageFont.truetype(BOLD,size),fill='#F4F7FB');y+=size*1.23
    sub=('Tu biblioteca. Tu próxima partida.' if lang=='es' else 'Your library. Your next game.') if closing else ('Una biblioteca de juegos para Linux.' if lang=='es' else 'A game library for Linux.')
    sublines=textwrap.wrap(sub,60 if aspect=='horizontal' else 32)
    y+=45
    for line in sublines:d.text((xx,y),line,font=ImageFont.truetype(FONT,36),fill='#AAB8C9');y+=48
    d.rectangle((xx,h-140,w-xx,h-136),fill='#0B91FF')
    im.save(path)

def native_project(master,project,caption_path,lang):
    result=call([FILM,'--compact','--save-as',project,'import',master])
    item=json.loads(result.stdout)['items'][0]
    w,h=Image.open(master.with_suffix('.png')).size if master.with_suffix('.png').exists() else ((1920,1080) if 'horizontal' in str(master) else (1080,1920))
    cmds=[dict(id='file.newSequence',params=dict(name=project.stem,width=w,height=h,fps=FPS,video=1,audio=0)),
          dict(id='timeline.place',params=dict(item=item,track='V1',seconds=0,insert=False,sourceIn=0,duration=20*TICKS,video=True,audio=False)),
          dict(id='captions.import',params=dict(path=str(caption_path),name=lang)),
          dict(id='captions.setStyle',params=dict(track='C1',font='Noto Sans',size=42 if w>h else 46,color='#F4F7FB',background=True,backgroundColor='#101923FF',anchor='bottom',margin=.03 if w>h else .25))]
    script=project.with_suffix('.jsonl');script.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in cmds)+'\n')
    r=call([FILM,'--compact','--project',project,'--save','run',script]);rows=[json.loads(s) for s in r.stdout.splitlines() if s.startswith('{')];assert all(row['ok'] for row in rows)
    # Keep media paths relative to the saved project for a portable package.
    p=json.loads(project.read_text())
    def relative(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if isinstance(v,str) and v==str(master):obj[k]=master.name
                else:relative(v)
        elif isinstance(obj,list):
            for v in obj:relative(v)
    relative(p);project.write_text(json.dumps(p,ensure_ascii=False,separators=(',',':')))
    return str(project.relative_to(BRAND))

def render_one(spec):
    clip,title,shots,lang,aspect=spec
    out=BASE/lang/aspect;out.mkdir(parents=True,exist_ok=True)
    project_dir=BASE/'projects'/lang/aspect;project_dir.mkdir(parents=True,exist_ok=True)
    work=BASE/'work'/lang/aspect/clip;work.mkdir(parents=True,exist_ok=True)
    width,height=(1920,1080) if aspect=='horizontal' else (1080,1920)
    intro=work/'intro.png';ending=work/'ending.png'
    card(intro,title,lang,aspect);card(ending,'Estante',lang,aspect,True)
    srt=out/(clip+'.srt');ass=out/(clip+'.ass')
    caplist=[]
    for i,(_,es,en) in enumerate(shots):
        value=es if lang=='es' else en
        assert len(value)/4<21,(clip,value)
        caplist.append(dict(start=2+i*4,end=6+i*4,text=value))
    srt.write_text('\n\n'.join(f'{i+1}\n{timecode(c["start"])} --> {timecode(c["end"])}\n'+ '\n'.join(textwrap.wrap(c['text'],76 if aspect=='horizontal' else 38)) for i,c in enumerate(caplist))+'\n')
    margin=70 if aspect=='horizontal' else 480
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,{42 if aspect=='horizontal' else 46},&H00FBF7F4,&H00FBF7F4,&H00231910,&H00231910,0,0,0,0,100,100,0,0,3,10,0,2,64,64,{margin},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    for c in caplist:
        text='\\N'.join(textwrap.wrap(c['text'],76 if aspect=='horizontal' else 38))
        events.append(f'Dialogue: 0,{timecode(c["start"],True)},{timecode(c["end"],True)},Default,,0,0,0,,{text}')
    ass.write_text(header+'\n'.join(events)+'\n')
    titlefile=work/'title.txt';titlefile.write_text(title)
    args=['ffmpeg','-hide_banner','-loglevel','error','-y','-loop','1','-framerate',str(FPS),'-t','2','-i',str(intro)]
    for scene,*_ in shots:
        args+=['-t','4','-i',str(BASE/'media'/lang/(scene+'.mp4'))]
    args+=['-loop','1','-framerate',str(FPS),'-t','2','-i',str(ending)]
    filters=[f'[0:v]trim=duration=2,setpts=PTS-STARTPTS,fps={FPS},setsar=1,format=yuv420p[v0]']
    for i,(scene,*_) in enumerate(shots,1):
        if aspect=='horizontal':
            filters.append(f'[{i}:v]trim=duration=4,setpts=PTS-STARTPTS,fps={FPS},scale=1536:864,pad=1920:1080:192:84:color=0x101923,setsar=1,drawtext=fontfile={BOLD}:text=Estante:expansion=none:fontcolor=0xF4F7FB:fontsize=30:x=64:y=24,drawtext=fontfile={FONT}:textfile={titlefile}:expansion=none:fontcolor=0xAAB8C9:fontsize=26:x=300:y=29,format=yuv420p[v{i}]')
        else:
            # One complete application window; no crop, duplicate view or zoom.
            filters.append(f'[{i}:v]trim=duration=4,setpts=PTS-STARTPTS,fps={FPS},scale=1008:567,pad=1080:1920:36:600:color=0x101923,setsar=1,drawtext=fontfile={BOLD}:text=Estante:expansion=none:fontcolor=0xF4F7FB:fontsize=52:x=64:y=90,drawtext=fontfile={FONT}:textfile={titlefile}:expansion=none:fontcolor=0xAAB8C9:fontsize=38:x=64:y=210,drawbox=x=60:y=410:w=960:h=4:color=0x0B91FF:t=fill,format=yuv420p[v{i}]')
    filters.append(f'[5:v]trim=duration=2,setpts=PTS-STARTPTS,fps={FPS},setsar=1,format=yuv420p[v5]')
    filters.append(''.join(f'[v{i}]' for i in range(6))+'concat=n=6:v=1:a=0,split=2[master][captions]')
    filters.append(f'[captions]ass={ass}[final]')
    master=project_dir/(clip+'-base.mp4');final=out/(clip+'.mp4')
    enc=['-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-threads','2','-an','-movflags','+faststart','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709']
    args+=['-filter_complex_threads','2','-filter_complex',';'.join(filters),'-map','[master]',*enc,str(master),'-map','[final]',*enc,str(final)]
    call(args)
    native=native_project(master,project_dir/(clip+'.fcproj'),srt,lang)
    call(['ffmpeg','-v','error','-i',final,'-f','null','-'])
    data=json.loads(call(['ffprobe','-v','error','-show_streams','-show_format','-of','json',final]).stdout)
    stream=data['streams'][0];assert (stream['width'],stream['height'])==(width,height)
    assert abs(float(data['format']['duration'])-20)<.05
    assert Fraction(stream['avg_frame_rate'])==FPS
    assert not any(s['codec_type']=='audio' for s in data['streams'])
    call(['ffmpeg','-v','error','-y','-ss','3','-i',final,'-frames:v','1',out/(clip+'.jpg')])
    result=dict(clip=clip,title=title,language=lang,aspect=aspect,width=width,height=height,fps=FPS,duration=20,
                video=str(final.relative_to(BRAND)),project=native,captions=caplist,decoded=True,audio=False,
                shots=[dict(scene=s[0],sourceStart=0,duration=4,at=2+i*4) for i,s in enumerate(shots)])
    if aspect=='vertical': result['layout']='single full application window, uncropped, no duplicate detail or zoom'
    (out/(clip+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(lang,aspect,clip,'verified',flush=True)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--language',nargs='+',default=['es','en']);p.add_argument('--aspect',nargs='+',choices=['horizontal','vertical'],default=['horizontal','vertical']);p.add_argument('--only');p.add_argument('--workers',type=int,default=2);args=p.parse_args()
    specs=[]
    for lang in args.language:
        for aspect in args.aspect:
            for clip,titles,shots in CLIPS:
                if args.only and args.only!=clip:continue
                specs.append((clip,titles[0 if lang=='es' else 1],shots,lang,aspect))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:results=list(pool.map(render_one,specs))
    report=BASE/'verification.json'
    merged={r['video']:r for r in json.loads(report.read_text())} if report.exists() else {}
    merged.update({r['video']:r for r in results})
    report.write_text(json.dumps(list(merged.values()),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
