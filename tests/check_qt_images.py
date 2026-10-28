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
