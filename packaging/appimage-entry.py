"""AppImage entry point, with a non-graphical dependency smoke test."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import atexit
import shutil

root = Path(os.environ['ESTANTE_APPDIR'])
cache_source = root / 'usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache'
if cache_source.is_file():
    cache_dir = Path(tempfile.mkdtemp(prefix='estante-pixbuf-'))
    atexit.register(shutil.rmtree, cache_dir, ignore_errors=True)
    cache = cache_dir / 'loaders.cache'
    text = cache_source.read_text().replace('/usr/lib/x86_64-linux-gnu/', str(root / 'usr/lib') + '/')
    cache.write_text(text.replace('"/usr/lib/', '"' + str(root / 'usr/lib') + '/'))
    os.environ['GDK_PIXBUF_MODULE_FILE'] = str(cache)
    os.environ['GDK_PIXBUF_MODULEDIR'] = str(cache_source.parent / 'loaders')

# Resolve codec paths at runtime so an extracted or mounted AppImage is relocatable.
glycin = root / 'usr/share/glycin-loaders'
if glycin.is_dir():
    config_dir = Path(tempfile.mkdtemp(prefix='estante-glycin-'))
    atexit.register(shutil.rmtree, config_dir, ignore_errors=True)
    for source in glycin.rglob('*.conf'):
        target = config_dir / 'glycin-loaders' / source.relative_to(glycin)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for line in source.read_text().splitlines():
            if line.startswith('Exec=/usr/lib/'):
                binary = root / line.removeprefix('Exec=/')
                line = 'Exec=' + str(binary) + '.wrapper'
            lines.append(line)
        target.write_text('\n'.join(lines) + '\n')
    os.environ['GLYCIN_DATA_DIR'] = str(config_dir)

JPEG_FIXTURE = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD0Giiivmj6c//Z'

if sys.argv[1:] == ['--self-test']:
    import ssl
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    gi.require_version('Gsk', '4.0')
    from gi.repository import Gtk, Adw, Gdk, Gio, Gsk, Graphene, GdkPixbuf, Pango
    from estante import App, BlurredBackdrop
    from i18n import set_language, get_language, tr
    original_language = get_language()
    for language, label in (('es', 'Ajustes'), ('en', 'Settings')):
        set_language(language)
        assert tr('Ajustes') == label
    set_language(original_language)
    ctypes.CDLL(str(root / 'usr/lib/libSDL2-2.0.so.0'))
    assert Path(sys.prefix).is_relative_to(root), 'Python externo al AppImage'
    assert (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 10)
    assert ssl.create_default_context().cert_store_stats()['x509_ca'] > 0
    assert Path(gi.__file__).is_relative_to(root), 'PyGObject externo al AppImage'
    # Test decoding without requiring Glycin's image-encoding subprocess.
    # PNG and JPEG are loaded by GDK's built-in decoders.
    import struct
    import zlib
    import base64
    from gi.repository import GLib
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(b'\x00\xff\xb0\x77')) + chunk(b'IEND', b''))
    jpeg = base64.b64decode(JPEG_FIXTURE)
    for data in (png, jpeg):
        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        assert texture.get_width() == 1 and texture.get_height() == 1
        # Exercise the actual background path as well as texture decoding.
        # The file path intentionally does not exist: reuse the decoded pixels.
        color = BlurredBackdrop.dominant_color('/unused/hero.img', texture)
        assert color.red > .9 and color.green > .5 and color.blue > .3
    from backgrounds import BUNDLED_BACKGROUNDS, DEFAULT_BACKGROUND, resolve_background
    from image_cache import ImageCache
    from steam_import import read_vdf, is_faugus_steam
    from scraping import scrape_game
    from appearance import list_side_for
    assert len(BUNDLED_BACKGROUNDS) == 6, 'Faltan fondos incluidos'
    assert Path(resolve_background(DEFAULT_BACKGROUND)).is_relative_to(root), 'Fondo externo al AppImage'
    for background in BUNDLED_BACKGROUNDS:
        texture = Gdk.Texture.new_from_filename(str(background))
        assert texture.get_width() > 0 and texture.get_height() > 0
    # Exercise the same scaled loader used by covers and Settings previews.
    with tempfile.TemporaryDirectory(prefix='estante-image-check-') as directory:
        decoder = ImageCache(disk_dir=Path(directory))
        for background in BUNDLED_BACKGROUNDS:
            texture = decoder.load(background, 480, 270)
            assert 0 < texture.get_width() <= 480
            assert 0 < texture.get_height() <= 270
        for extension, data in (('png', png), ('jpg', jpeg)):
            fixture = Path(directory) / ('fixture.' + extension)
            fixture.write_bytes(data)
            assert decoder.load(fixture, 64, 64).get_width() == 1
        assert decoder.wait_for_writes(15), 'La caché de miniaturas no terminó'
        decoder.retain_paths([])
        assert decoder.load(BUNDLED_BACKGROUNDS[0], 480, 270).get_width() > 0
        assert decoder.wait_for_writes(15), 'La última miniatura no terminó'
    assert is_faugus_steam({'runner': 'Steam'})
    assert list_side_for({}) == 'left'
    from backgrounds import paint_hero_pair
    import cairo
    first = Gdk.MemoryTexture.new(1, 1, Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(bytes((255, 0, 0, 255))), 4)
    second = Gdk.MemoryTexture.new(1, 1, Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(bytes((0, 0, 255, 255))), 4)
    for split in ('horizontal', 'vertical', 'diagonal'):
        snapshot = Gtk.Snapshot.new()
        paint_hero_pair(snapshot, (first, second), 120, 80, 'full', split)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
        snapshot.to_node().draw(cairo.Context(surface))
        surface.flush()
        pixels = surface.get_data()
        assert tuple(pixels[10 * surface.get_stride() + 10 * 4:10 * surface.get_stride() + 10 * 4 + 4]) == (0, 0, 255, 255)
        assert tuple(pixels[70 * surface.get_stride() + 110 * 4:70 * surface.get_stride() + 110 * 4 + 4]) == (255, 0, 0, 255)
    # Exercise the SVG-to-PNG path used by Bootstrap Icons and Iconify.
    from metadata import CategoryIcons
    with tempfile.TemporaryDirectory(prefix='estante-svg-check-') as directory:
        target = Path(directory) / 'icon.png'
        CategoryIcons.render_svg(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path fill="currentColor" d="M4 4h8v8H4z"/></svg>', target)
        icon = Gdk.Texture.new_from_filename(str(target))
        assert (icon.get_width(), icon.get_height()) == (128, 128)
        pixbuf = Gdk.pixbuf_get_from_texture(icon)
        center = 64 * pixbuf.get_rowstride() + 64 * 4
        assert tuple(pixbuf.get_pixels()[center:center + 4]) == (255, 255, 255, 255)
        assert pixbuf.get_pixels()[3] == 0
    # Confirm critical libraries were loaded from the bundle, not the host.
    maps = Path('/proc/self/maps').read_text().splitlines()
    for name in ('libgtk-4.so', 'libadwaita-1.so', 'libgobject-2.0.so', 'librsvg-2.so'):
        paths = [line.split(maxsplit=5)[-1] for line in maps if name in line]
        assert paths and all(str(root) in path for path in paths), name + ' externo al AppImage'
    print('AppImage: Python, GTK, libadwaita, SDL2, fondos PNG/JPEG, iconos SVG, color y certificados OK.')
elif sys.argv[1:] == ['--version']:
    from version import __version__
    print('Estante ' + __version__)
else:
    from estante import App
    raise SystemExit(App().run(sys.argv))
