import argparse,json,tempfile,sys
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSize,Qt
from PySide6.QtGui import QImage,QColor
from qt_app.images import ArtworkProvider
parser=argparse.ArgumentParser(description='Probe small artwork requests without changing application code.')
parser.add_argument('--output',type=Path,default=Path('/tmp/estante-image-edges.json'))
args=parser.parse_args()
rows=[]
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);provider=ArtworkProvider(root/'cache')
 for kind,width,height,requests in [('cover',600,900,[(240,360),(0,1),(1,1)]),('logo',800,200,[(360,80),(1,42)])]:
  source=QImage(width,height,QImage.Format_RGB32);source.fill(QColor('coral'));path=root/(kind+'.png');assert source.save(str(path))
  identity=('@logo/' if kind=='logo' else '')+quote(str(path),safe='')
  for w,h in requests:
   result=provider.requestImage(identity,QSize(),QSize(w,h))
   rows.append(dict(kind=kind,original=[width,height],requested=[w,h],returned=[result.width(),result.height()],is_null=result.isNull()))
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
