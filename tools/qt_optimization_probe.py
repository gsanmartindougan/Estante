"""Repeatable CPU/allocation probe for Qt model projection; never opens a window."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,json,time,tempfile,statistics,tracemalloc,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from qt_app.main import LibraryController
from library import Library
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',required=True)
args=parser.parse_args()
app=QApplication([]);app.setDesktopFileName('io.github.estante.Test')
results=[]
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);image=QImage(120,180,QImage.Format_RGB32);image.fill(0xff556677);image.save(str(root/'cover.png'))
 for count in (100,1000):
  games=[{'id':str(i),'title':chr(65+i%26)+f' Game {i:04d}','kind':'custom','cover':str(root/'cover.png'),
          'square_cover':str(root/'cover.png'),'logo':str(root/'cover.png'),'banner':str(root/'cover.png'),
          'metadata':{'description':'Example description. '*12,'genres':['Action','Adventure'],'developers':['Studio']}}
         for i in range(count)]
  lib=Library(data_dir=root);lib.put_many(games)
  c=LibraryController(games,{},root,allow_launch=False)
  c.entries
  def measure(work,repeats):
   values=[]
   for _ in range(3):
    start=time.perf_counter()
    for i in range(repeats):work(i)
    values.append((time.perf_counter()-start)*1000)
   return round(statistics.median(values),3)
  model_ms=measure(lambda _:c.entries,20)
  def cold(_):
   if hasattr(c,'invalidateEntries'):c.invalidateEntries()
   return c.entries
  cold_ms=measure(cold,20)
  nav_ms=measure(lambda i:(c.move(1),c.letters,c.letterIndex,c.selected),500)
  tracemalloc.start()
  for _ in range(20):model=c.entries
  _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
  row=dict(games=count,model_20_reads_ms=model_ms,model_20_rebuilds_ms=cold_ms,navigation_500_steps_ms=nav_ms,
           model_json_KiB=round(len(json.dumps(model).encode())/1024,2),model_20_reads_python_peak_KiB=round(peak/1024,2))
  results.append(row);print(json.dumps(row),flush=True)
  c.manager.shutdown();c.idle_timer.stop()
Path(args.output).write_text(json.dumps(results,indent=2)+'\n')
