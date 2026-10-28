"""Decode display-sized images and share a bounded set of CPU textures."""
from collections import OrderedDict
from pathlib import Path
from threading import RLock, Condition, Thread, get_native_id
from types import SimpleNamespace
from profiling import timed, count
import os
import hashlib
import tempfile
import struct
import zlib
import re
import gi

gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GdkPixbuf, GLib


def memory_usage():
    """Read current process memory, distinguishing resident and shared pages."""
    try:
        values = {}
        for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
            key, _, value = line.partition(':')
            if key in ('Rss', 'Pss', 'Anonymous', 'Private_Clean', 'Private_Dirty', 'Shared_Clean', 'Shared_Dirty'):
                values[key] = int(value.split()[0]) / 1024
        return {key: round(value, 1) for key, value in values.items()}
    except (OSError, ValueError, IndexError):
        return {}


def reclaim_unused_memory():
    """Collect discarded widgets and return free native heap pages on glibc."""
    import ctypes
    import gc
    def resident_mib():
        try:
            pages = int(Path('/proc/self/statm').read_text().split()[1])
            return round(pages * os.sysconf('SC_PAGE_SIZE') / 1048576, 1)
        except (OSError, ValueError, IndexError):
            return None
    before = resident_mib()
    collected = gc.collect()
    supported = False
    try:
        trim = ctypes.CDLL(None).malloc_trim
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        trim(0)
        supported = True
    except (AttributeError, OSError):
        pass
    return {'before_mib': before, 'after_mib': resident_mib(),
            'collected': collected, 'native_trim': supported}


def thumbnail_dimensions(path):
    """Read cache headers without starting an image decoder."""
    with Path(path).open('rb') as stream:
        header = stream.read(33)
    if header[:3] == b'\xff\xd8\xff':
        size = jpeg_dimensions(path)
        if size is None:
            raise ValueError('Invalid cached JPEG header')
        width, height = size
    else:
        if (len(header) != 33 or header[:8] != b'\x89PNG\r\n\x1a\n' or
                header[8:16] != b'\x00\x00\x00\x0dIHDR' or
                zlib.crc32(header[12:29]) != struct.unpack('>I', header[29:33])[0]):
            raise ValueError('Invalid cached PNG header')
        width, height = struct.unpack('>II', header[16:24])
    if not (0 < width <= 3840 and 0 < height <= 3840 and width * height <= 3840 * 2160):
        raise ValueError('Invalid cached image dimensions')
    return width, height


def jpeg_dimensions(path):
    """Read JPEG frame dimensions without importing a decoder or reading pixels."""
    frames = {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
              0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}
    with Path(path).open('rb') as stream:
        if stream.read(2) != b'\xff\xd8':
            return None
        while stream.tell() < 16 * 1024 * 1024:
            if stream.read(1) != b'\xff':
                return None
            code = stream.read(1)
            while code == b'\xff':
                code = stream.read(1)
            if not code or code[0] in (0xda, 0xd9):
                return None
            if code[0] == 1 or 0xd0 <= code[0] <= 0xd8:
                continue
            length = stream.read(2)
            if len(length) != 2:
                return None
            size = int.from_bytes(length, 'big')
            if size < 2:
                return None
            if code[0] in frames:
                frame = stream.read(5)
                if size < 8 or len(frame) != 5:
                    return None
                width, height = int.from_bytes(frame[3:5], 'big'), int.from_bytes(frame[1:3], 'big')
                return (width, height) if width and height else None
            stream.seek(size - 2, 1)
    return None


def decode_pixbuf(path, width, height):
    """Use GDK's in-process codecs when bundled Glycin cannot be started."""
    if not os.environ.get('ESTANTE_APPDIR'):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height, True)
        except GLib.Error:
            pass
    # JPEG can be reduced by its decoder, before creating any original-size
    # texture. Keep the existing PNG decoder: Pillow's full PNG buffer and
    # module overhead increased the measured peak instead of reducing it.
    with Path(path).open('rb') as source:
        jpeg = source.read(3) == b'\xff\xd8\xff'
    if jpeg:
        # Importing another decoder has a resident cost of its own. Use it only
        # where a large original and substantial downscale justify that cost.
        size = jpeg_dimensions(path)
        jpeg = bool(size and size[0] * size[1] >= 16_000_000
                    and size[0] >= width * 2 and size[1] >= height * 2)
    if jpeg:
        try:
            from PIL import Image
        except ImportError:
            pass  # Existing source installations need no new mandatory dependency.
        else:
            with Image.open(path) as image:
                image.draft('RGB', (width, height))
                image.thumbnail((width, height), Image.Resampling.LANCZOS, reducing_gap=3.0)
                rgba = image.convert('RGBA')
                w, h = rgba.size
                return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(rgba.tobytes()),
                    GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
    # PNG and compatibility fallback retain GDK's in-process codecs.
    texture = Gdk.Texture.new_from_filename(str(path))
    pixbuf = Gdk.pixbuf_get_from_texture(texture)
    ratio = min(1, width / pixbuf.get_width(), height / pixbuf.get_height())
    scaled_width = max(1, round(pixbuf.get_width() * ratio))
    scaled_height = max(1, round(pixbuf.get_height() * ratio))
    if (scaled_width, scaled_height) != (pixbuf.get_width(), pixbuf.get_height()):
        pixbuf = pixbuf.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
    return pixbuf


def validate_image(path):
    """Validate pixels in a worker without populating the display texture cache."""
    decode_pixbuf(path, 64, 64)
    return str(path)


class ImageCache:
    def __init__(self, max_bytes=64 * 1024 * 1024, disk_dir=None, disk_bytes=128 * 1024 * 1024):
        self.suspended = False
        self.generation = 0
        self.retention_revision = 0
        self.retained_paths = None
        self.max_bytes = max_bytes
        self.disk_dir = Path(disk_dir) if disk_dir is not None else None
        self.disk_bytes = disk_bytes
        self.bytes = 0
        self.entries = OrderedDict()
        self.entry_roles = {}
        self.lock = RLock()
        self.condition = Condition(self.lock)
        self.pending = {}
        self.loading = {}
        self.worker = None
        self.sequence = 0
        self.prepared_values = OrderedDict()
        self.write_condition = Condition(self.lock)
        self.write_queue = OrderedDict()
        self.write_worker = None
        self.write_active = None
        self.write_bytes = 0
        self.max_write_bytes = 32 * 1024 * 1024
        self.max_write_jobs = 4

    def suspend(self):
        with self.lock:
            self.suspended = True
            self.generation += 1
            for job in self.pending.values():
                for ticket, _, _ in job[2]:
                    ticket.cancelled = True
            self.pending.clear()
            self.entries.clear()
            self.entry_roles.clear()
            self.prepared_values.clear()
            self.bytes = 0
            for _, size in self.write_queue.values():
                self.write_bytes -= size
            self.write_queue.clear()

    def resume(self):
        with self.lock:
            self.suspended = False

    def prepared(self, kind, path, work):
        """Retain only tiny derived values, never textures, across focus changes."""
        path = Path(path)
        stat = path.stat()
        key = (kind, str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        with self.lock:
            if key in self.prepared_values:
                self.prepared_values.move_to_end(key)
                return self.prepared_values[key]
        generation = self.generation
        value = work()
        with self.lock:
            if self.suspended or generation != self.generation:
                return value
            self.prepared_values[key] = value
            while len(self.prepared_values) > 128:
                self.prepared_values.popitem(last=False)
        return value

    def _evict(self, key, reason):
        self.bytes -= self.entries.pop(key)[1]
        kind = self.entry_roles.pop(key, 'other')
        count('images.' + kind + '.evicted_' + reason)

    def retain_paths(self, paths):
        allowed = {str(Path(path).resolve()) for path in paths if path}
        with self.lock:
            self.retention_revision += 1
            self.retained_paths = allowed
            for key in list(self.pending):
                if key[0] not in allowed:
                    callbacks = self.pending.pop(key)[2]
                    for ticket, _, _ in callbacks:
                        ticket.cancelled = True
                    count('images.' + callbacks[0][0].kind + '.queue_discarded')
            for key in list(self.entries):
                if key[0] not in allowed:
                    self._evict(key, 'window')

    def load(self, path, width=1920, height=1080, kind='other'):
        source = Path(path)
        stat = source.stat()
        with self.condition:
            key = (str(source.resolve()), stat.st_mtime_ns, stat.st_size,
                   round(width), round(height), self.generation)
            existing = self.loading.get(key)
            if existing is not None:
                self.condition.wait_for(lambda: existing.done)
                if existing.error is not None:
                    raise existing.error
                return existing.texture
            state = SimpleNamespace(done=False, texture=None, error=None)
            self.loading[key] = state
        try:
            state.texture = timed('worker.image_load.' + kind)(self._load)(path, width, height, kind)
            return state.texture
        except Exception as error:
            state.error = error
            raise
        finally:
            with self.condition:
                state.done = True
                del self.loading[key]
                self.condition.notify_all()

    def request_picture(self, picture, path, width, height, kind='settings'):
        previous = getattr(picture, 'image_ticket', None)
        if previous:
            previous.cancelled = True
        if not path:
            picture.set_paintable(None)
            picture.image_ticket = None
            return None
        def ready(texture, error):
            if error is None:
                picture.set_paintable(texture)
            else:
                picture.set_paintable(None)
        picture.image_ticket = self.request(path, width, height, ready, kind=kind)
        return picture.image_ticket

    def request(self, path, width, height, done, priority=1, prepare=None, kind='other'):
        ticket = SimpleNamespace(cancelled=False, kind=kind)
        key = (str(Path(path).resolve()), round(width), round(height))
        with self.condition:
            if self.suspended:
                ticket.cancelled = True
                return ticket
            self.sequence += 1
            if key in self.pending:
                job = self.pending[key]
                job[0] = min(job[0], priority)
                job[2].append((ticket, done, prepare))
            else:
                self.pending[key] = [priority, self.sequence, [(ticket, done, prepare)]]
            if self.worker is None:
                self.worker = Thread(target=self._run, daemon=True, name='estante-images')
                self.worker.start()
            self.condition.notify()
        return ticket

    def _run(self):
        while True:
            with self.condition:
                while not self.pending:
                    self.condition.wait()
                key = min(self.pending, key=lambda k: self.pending[k][:2])
                _, _, callbacks = self.pending.pop(key)
                generation = self.generation
            if all(ticket.cancelled for ticket, _, _ in callbacks):
                callbacks = []
                continue
            try:
                texture, error = self.load(*key, kind=callbacks[0][0].kind), None
            except Exception as exception:
                texture, error = None, exception
            for ticket, done, prepare in callbacks:
                if generation != self.generation:
                    ticket.cancelled = True
                result, failure = texture, error
                if not ticket.cancelled and error is None and prepare:
                    try:
                        result = prepare(texture)
                    except Exception as exception:
                        result, failure = None, exception
                def deliver(ticket=ticket, done=done, texture=result, error=failure, generation=generation):
                    if not ticket.cancelled and generation == self.generation:
                        done(texture, error)
                    return False
                if not ticket.cancelled:
                    GLib.idle_add(deliver)
            # A waiting worker must not keep the last texture or UI closures alive.
            callbacks = []
            texture = result = done = prepare = deliver = error = failure = None

    @timed('worker.image_load')
    def _load(self, path, width, height, kind='other'):
        with self.lock:
            generation = self.generation
            retention_revision = self.retention_revision
        count('images.' + kind + '.loads')
        path = Path(path)
        stat = path.stat()
        width, height = max(1, round(width)), max(1, round(height))
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size, width, height)
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                count('images.' + kind + '.memory_hits')
                return self.entries[key][0]
        count('images.' + kind + '.memory_misses')
        thumbnail = None
        pixbuf = None
        if self.disk_dir is not None and width <= 3840 and height <= 3840 and width * height <= 3840 * 2160:
            name = hashlib.sha256(repr(('v1', key)).encode()).hexdigest()
            thumbnail = self.disk_dir / (name + '.png')
            # Prefer the converted opaque copy; old PNG cache entries remain valid.
            for cached in (thumbnail.with_suffix('.jpg'), thumbnail):
                if not cached.is_file():
                    continue
                try:
                    source_width, source_height = thumbnail_dimensions(cached)
                    ratio = min(1, width / source_width, height / source_height)
                    cached_width = max(1, round(source_width * ratio))
                    cached_height = max(1, round(source_height * ratio))
                    pixbuf = decode_pixbuf(cached, cached_width, cached_height)
                    cached.touch()
                    count('images.' + kind + '.disk_reads')
                    # Migrate old opaque PNG thumbnails in the background.
                    if cached.suffix == '.png' and not pixbuf.get_has_alpha():
                        self._queue_thumbnail(pixbuf, cached)
                    break
                except (GLib.Error, OSError, ValueError):
                    count('images.' + kind + '.disk_errors')
                    pixbuf = None
        if pixbuf is None:
            count('images.' + kind + '.original_decodes')
            # Decode only on a cache miss, preserving aspect ratio without enlarging.
            info = GdkPixbuf.Pixbuf.get_file_info(str(path))
            if info and info[0] is not None:
                _, original_width, original_height = info
                ratio = min(1, width / original_width, height / original_height)
                width, height = max(1, round(original_width * ratio)), max(1, round(original_height * ratio))
            pixbuf = decode_pixbuf(path, width, height)
            if thumbnail is not None:
                self._queue_thumbnail(pixbuf, thumbnail)
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        sample_size = 0
        if kind == 'background':
            # Sample before turning pixels into a texture: never download/copy the
            # full background texture just to calculate a tiny dominant colour.
            ratio = min(1, 64 / pixbuf.get_width(), 64 / pixbuf.get_height())
            sample = pixbuf.scale_simple(max(1, round(pixbuf.get_width() * ratio)),
                max(1, round(pixbuf.get_height() * ratio)), GdkPixbuf.InterpType.BILINEAR)
            texture.color_sample = sample
            sample_size = sample.get_rowstride() * sample.get_height()
        size = pixbuf.get_rowstride() * pixbuf.get_height() + sample_size
        with self.lock:
            # Drop stale versions of replaced files, even if they had a different size.
            for old in list(self.entries):
                if old[0] == key[0] and old[1:3] != key[1:3]:
                    self._evict(old, 'changed')
            still_retained = (retention_revision == self.retention_revision or
                              self.retained_paths is None or key[0] in self.retained_paths)
            if not self.suspended and generation == self.generation and still_retained and size <= self.max_bytes:
                while self.entries and (self.bytes + size > self.max_bytes or len(self.entries) >= 128):
                    self._evict(next(iter(self.entries)), 'budget')
                self.entries[key] = texture, size
                self.entry_roles[key] = kind
                self.bytes += size
        return texture

    def _queue_thumbnail(self, pixbuf, target):
        # Never flatten alpha: transparent logos and covers stay lossless PNG.
        target = target.with_suffix('.png' if pixbuf.get_has_alpha() else '.jpg')
        size = pixbuf.get_rowstride() * pixbuf.get_height()
        with self.write_condition:
            if self.suspended or target == self.write_active or target in self.write_queue:
                return
            if size > self.max_write_bytes:
                return
            while self.write_queue and (self.write_bytes + size > self.max_write_bytes or
                                        len(self.write_queue) + bool(self.write_active) >= self.max_write_jobs):
                _, (_, discarded_size) = self.write_queue.popitem(last=False)
                self.write_bytes -= discarded_size
            if self.write_bytes + size > self.max_write_bytes:
                return
            self.write_queue[target] = (pixbuf, size)
            self.write_bytes += size
            if self.write_worker is None:
                self.write_worker = Thread(target=self._write_loop, daemon=True, name='estante-thumbnails')
                self.write_worker.start()
            self.write_condition.notify()

    def writes_idle(self):
        with self.lock:
            return not self.write_queue and self.write_active is None

    def wait_for_writes(self, timeout=5):
        with self.write_condition:
            return self.write_condition.wait_for(self.writes_idle, timeout=timeout)

    def _write_loop(self):
        # Linux nice values are per thread: lower only this optional cache writer.
        if hasattr(os, 'setpriority') and hasattr(os, 'PRIO_PROCESS'):
            try:
                os.setpriority(os.PRIO_PROCESS, get_native_id(), 10)
            except OSError:
                pass
        while True:
            with self.write_condition:
                while not self.write_queue:
                    self.write_condition.wait()
                target, (pixbuf, size) = self.write_queue.popitem(last=False)
                self.write_active = target
            try:
                self._save_thumbnail(pixbuf, target)
            except Exception:
                # Optional cache failures must not terminate future writes.
                pass
            finally:
                del pixbuf
                with self.write_condition:
                    self.write_active = None
                    self.write_bytes -= size
                    self.write_condition.notify_all()

    @timed('worker.thumbnail_write')
    def _save_thumbnail(self, pixbuf, target):
        temporary = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix='.thumbnail-', dir=target.parent)
            os.close(descriptor)
            if target.suffix == '.jpg':
                pixbuf.savev(temporary, 'jpeg', ['quality'], ['95'])
            else:
                pixbuf.savev(temporary, 'png', ['compression'], ['3'])
            os.replace(temporary, target)
            temporary = None
            if target.suffix == '.jpg':
                # Delete only its superseded cache copy after a successful write.
                target.with_suffix('.png').unlink(missing_ok=True)
            files = sorted((*target.parent.glob('*.png'), *target.parent.glob('*.jpg')),
                           key=lambda item: item.stat().st_mtime_ns)
            total = sum(item.stat().st_size for item in files)
            count = len(files)
            for item in files:
                if total <= self.disk_bytes and count <= 512:
                    break
                size = item.stat().st_size
                item.unlink(missing_ok=True)
                total -= size
                count -= 1
        except (GLib.Error, OSError):
            # A full or read-only cache must not prevent displaying the original.
            pass
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass


images = ImageCache(disk_dir=Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'estante' / 'thumbnails')


def consume_cache_reset():
    """Clear only generated image cache files when explicitly requested locally."""
    request = Path(__file__).with_name('.reset-image-cache')
    if not request.is_file():
        return False
    try:
        removed = 0
        folder = images.disk_dir
        if folder is not None and folder.is_dir():
            for path in folder.iterdir():
                if (re.fullmatch(r'[0-9a-f]{64}\.(?:png|jpg)', path.name)
                        or path.name.startswith('.thumbnail-')) and path.is_file():
                    path.unlink()
                    removed += 1
        images.suspend()
        images.resume()
        request.unlink()
        print(f'Estante: caché de imágenes vaciada antes del arranque ({removed} archivos).', flush=True)
        return True
    except OSError as error:
        print(f'Estante: no se pudo vaciar la caché: {error}', flush=True)
        return False


def nearby_indices(count, selected, radius=1, wrap=False):
    """Unique selected/adjacent games, without inventing missing neighbours."""
    if count <= 0:
        return set()
    selected = max(0, min(count - 1, selected))
    if wrap:
        return {(selected + offset) % count for offset in range(-radius, radius + 1)}
    return set(range(max(0, selected - radius), min(count, selected + radius + 1)))
