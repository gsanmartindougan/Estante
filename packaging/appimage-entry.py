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
    # Confirm critical libraries were loaded from the bundle, not the host.
    maps = Path('/proc/self/maps').read_text().splitlines()
    for name in ('libgtk-4.so', 'libadwaita-1.so', 'libgobject-2.0.so'):
        paths = [line.split(maxsplit=5)[-1] for line in maps if name in line]
        assert paths and all(str(root) in path for path in paths), name + ' externo al AppImage'
    print('AppImage: Python, GTK, libadwaita, SDL2, fondos PNG/JPEG, color y certificados OK.')
elif sys.argv[1:] == ['--version']:
    from version import __version__
    print('Estante ' + __version__)
else:
    from estante import App
    raise SystemExit(App().run(sys.argv))
