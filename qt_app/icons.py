"""Render category icon providers with Qt, without loading GTK/Cairo."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from metadata import CategoryIcons, IconifyIcons


class QtSvgRenderer:
    @staticmethod
    def render_svg(data, target):
        renderer=QSvgRenderer(data.replace(b'currentColor',b'#ffffff'))
        if not renderer.isValid(): raise ValueError('Icono SVG no válido')
        image=QImage(128,128,QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter=QPainter(image)
        renderer.render(painter,QRectF(0,0,128,128))
        painter.end()
        if not image.save(str(target),'PNG'): raise ValueError('No se pudo guardar el icono')


class BootstrapIcons(QtSvgRenderer, CategoryIcons): pass
class SearchIcons(QtSvgRenderer, IconifyIcons): pass
