"""Verify bounded decodes, opaque JPEG caching, transparency and invalidation."""
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QColor
from qt_app.images import ArtworkProvider
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);provider=ArtworkProvider(root/'cache')
    path=root/'opaque #1.png'
    source=QImage(1600,900,QImage.Format_RGBA8888);source.fill(QColor('red'));source.save(str(path))
    original=path.read_bytes();size=QSize()
    image=provider.requestImage(quote(str(path),safe=''),size,QSize(400,300))
    assert image.size()==QSize(400,225) and size==image.size()
    assert len(list((root/'cache').glob('*.jpg')))==1
    assert not list((root/'cache').glob('*.png'))
    assert path.read_bytes()==original
    image=provider.requestImage(quote(str(path),safe=''),QSize(),QSize(400,300))
    assert not image.isNull() and image.size()==QSize(400,225)
    color=provider.requestImage('@dominant/'+quote(str(path),safe=''),QSize(),QSize(1000,1000))
    assert color.size()==QSize(16,16) and color.pixelColor(0,0).red()>240
    source.fill(QColor(0,0,0,0));source.save(str(path))
    image=provider.requestImage(quote(str(path),safe=''),QSize(),QSize(400,300))
    assert image.pixelColor(0,0).alpha()==0 and len(list((root/'cache').glob('*.png')))==1
    # Identical visible logos on different, asymmetric transparent canvases
    # must yield the same size and centering, including after a cache hit.
    for index,(width,height,x,y) in enumerate([(800,400,10,20),(1400,700,850,450)]):
        logo=QImage(width,height,QImage.Format_RGBA8888);logo.fill(QColor(0,0,0,0))
        from PySide6.QtGui import QPainter
        painter=QPainter(logo);painter.fillRect(x,y,400,100,QColor('coral'));painter.end()
        path=root/f'logo-{index}.png';assert logo.save(str(path))
        before=path.read_bytes()
        for _ in range(2):
            decoded=provider.requestImage('@logo/'+quote(str(path),safe=''),QSize(),QSize(360,80))
            assert decoded.size()==QSize(320,80),decoded.size()
            assert decoded.pixelColor(0,0).alpha()==255
            assert decoded.pixelColor(decoded.width()-1,decoded.height()-1).alpha()==255
        assert path.read_bytes()==before
    assert provider.requestImage('/missing/image',QSize(),QSize(100,100)).isNull()
print('QT_IMAGES_OK: resized JPEG, transparent PNG, unchanged originals, invalidation and disk reuse')

# First-layout requests can have zero or single-pixel dimensions. Test actual
# decoding, the second logo resize, and subsequent disk-cache reads.
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);provider=ArtworkProvider(root/'cache')
    for extension in ('png','jpg','webp'):
        for kind,width,height,requests in (
                ('cover',600,900,[(0,1),(1,1),(1,0),(2,1),(240,360)]),
                ('wide',900,200,[(1,1),(0,1),(1,0),(1,1440)]),
                ('logo',800,200,[(1,42),(1,1),(0,1),(360,80)])):
            source=QImage(width,height,QImage.Format_RGB32);source.fill(QColor('coral'))
            path=root/f'{kind}.{extension}';assert source.save(str(path))
            before=path.read_bytes()
            identity=('@logo/' if kind=='logo' else '')+quote(str(path),safe='')
            for w,h in requests:
                for _ in range(2):
                    size=QSize();decoded=provider.requestImage(identity,size,QSize(w,h))
                    assert not decoded.isNull(),(extension,kind,w,h)
                    assert decoded.width()>=1 and decoded.height()>=1
                    assert size==decoded.size()
                    assert decoded.width()<=width and decoded.height()<=height
            assert path.read_bytes()==before
print('QT_IMAGE_EDGE_REGRESSION_OK: PNG/JPEG/WebP, tiny/zero dimensions, portrait/wide/logo, cache hits, originals preserved')
