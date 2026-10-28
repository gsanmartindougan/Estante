"""Display-sized Qt decodes and compressed disk thumbnails, preserving originals."""
import hashlib
from pathlib import Path
from urllib.parse import unquote
from PySide6.QtCore import QSize, Qt, QSaveFile, QIODevice
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQuick import QQuickImageProvider


def trim_logo(image):
    """Remove transparent canvas padding without touching any visible pixels."""
    if not image.hasAlphaChannel(): return image
    rgba=image.convertToFormat(QImage.Format_RGBA8888)
    alpha=bytes(rgba.constBits())[3::4]
    width,height=rgba.width(),rgba.height()
    left,right,top,bottom=width,0,height,0
    for y in range(height):
        row=alpha[y*width:(y+1)*width]
        end=len(row.rstrip(b'\x00'))
        if not end: continue
        left=min(left,len(row)-len(row.lstrip(b'\x00')))
        right=max(right,end)
        top=min(top,y)
        bottom=y+1
    return image.copy(left,top,right-left,bottom-top) if right>left else image


class ArtworkProvider(QQuickImageProvider):
    def __init__(self, cache):
        super().__init__(QQuickImageProvider.Image, QQuickImageProvider.ForceAsynchronousImageLoading)
        self.cache=Path(cache)
        self.writes=0

    def requestImage(self, identity, size, requestedSize):
        logo=identity.startswith('@logo/')
        if logo: identity=identity.removeprefix('@logo/')
        dominant=identity.startswith('@dominant/')
        if dominant: identity=identity.removeprefix('@dominant/')
        path=Path(unquote(identity))
        try:
            stat=path.stat()
            reader=QImageReader(str(path))
            original=reader.size()
            if not original.isValid(): return QImage()
            target=QSize(min(2560,requestedSize.width() if requestedSize.width()>0 else 1920),min(1440,requestedSize.height() if requestedSize.height()>0 else 1080))
            if dominant: target=QSize(64,64)
            scaled=original.scaled(QSize(2560,1440) if logo else target,Qt.KeepAspectRatio)
            if scaled.width()>original.width() or scaled.height()>original.height(): scaled=original
            variant=f'logo:{target.width()}x{target.height()}:v1' if logo else f'{dominant}:v3'
            key=hashlib.sha256(f'{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{scaled.width()}x{scaled.height()}:{variant}'.encode()).hexdigest()
            base=self.cache/key
            for suffix in ('.jpg','.png'):
                cached=Path(str(base)+suffix)
                if cached.is_file():
                    image=QImage(str(cached))
                    if not image.isNull():
                        size.setWidth(image.width());size.setHeight(image.height())
                        return image
            reader.setScaledSize(scaled)
            reader.setAutoTransform(True)
            image=reader.read()
            if image.isNull(): return image
            if image.size()!=scaled: image=image.scaled(scaled,Qt.KeepAspectRatio,Qt.SmoothTransformation)
            if logo:
                image=trim_logo(image)
                image=image.scaled(image.size().scaled(target,Qt.KeepAspectRatio),Qt.KeepAspectRatio,Qt.SmoothTransformation)
            if dominant:
                buckets={}
                for y in range(image.height()):
                    for x in range(image.width()):
                        color=image.pixelColor(x,y)
                        if color.alpha()<128: continue
                        r,g,b=color.red(),color.green(),color.blue()
                        bucket=buckets.setdefault((r//32,g//32,b//32),[0,0,0,0])
                        bucket[0]+=1;bucket[1]+=r;bucket[2]+=g;bucket[3]+=b
                color=(32,32,32)
                if buckets:
                    n,r,g,b=max(buckets.values(),key=lambda row:row[0])
                    color=(round(r/n),round(g/n),round(b/n))
                from PySide6.QtGui import QColor
                # Qt Quick can drop a 1x1 provider texture stretched over the backdrop.
                # Keep a tiny real texture; the color is still constant across every pixel.
                image=QImage(16,16,QImage.Format_RGB32);image.fill(QColor(*color))
            transparent=image.hasAlphaChannel()
            if transparent:
                sample=image.convertToFormat(QImage.Format_RGBA8888)
                alpha=bytes(sample.constBits())[3::4]
                transparent=alpha.count(b'\xff') != sample.width()*sample.height()
            try:
                self.cache.mkdir(parents=True,exist_ok=True)
                targetfile=QSaveFile(str(base)+('.png' if transparent else '.jpg'))
                if targetfile.open(QIODevice.WriteOnly):
                    if image.save(targetfile,'PNG' if transparent else 'JPEG',-1 if transparent else 88): targetfile.commit()
                    else: targetfile.cancelWriting()
                self.writes+=1
                if self.writes%16==0:
                    files=sorted(self.cache.glob('*'),key=lambda p:p.stat().st_mtime,reverse=True)
                    total=0
                    for index,cached in enumerate(files):
                        total+=cached.stat().st_size
                        if total>128*1024*1024 or index>=1024: cached.unlink(missing_ok=True)
            except OSError:
                pass  # A read-only cache must not hide successfully decoded artwork.
            size.setWidth(image.width());size.setHeight(image.height())
            return image
        except (OSError,ValueError):
            return QImage()
