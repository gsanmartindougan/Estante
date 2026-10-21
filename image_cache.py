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
import gi

gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GdkPixbuf, GLib


def thumbnail_dimensions(path):
    """Read only our PNG cache's IHDR, without starting an image decoder."""
    with Path(path).open('rb') as stream:
        header = stream.read(33)
    if (len(header) != 33 or header[:8] != b'\x89PNG\r\n\x1a\n' or
            header[8:16] != b'\x00\x00\x00\x0dIHDR' or
            zlib.crc32(header[12:29]) != struct.unpack('>I', header[29:33])[0]):
        raise ValueError('Invalid cached PNG header')
    width, height = struct.unpack('>II', header[16:24])
    if not (0 < width <= 3840 and 0 < height <= 3840 and width * height <= 3840 * 2160):
        raise ValueError('Invalid cached PNG dimensions')
    return width, height


class ImageCache:
    def __init__(self, max_bytes=64 * 1024 * 1024, disk_dir=None, disk_bytes=128 * 1024 * 1024):
        self.max_bytes = max_bytes
        self.disk_dir = Path(disk_dir) if disk_dir is not None else None
        self.disk_bytes = disk_bytes
        self.bytes = 0
        self.entries = OrderedDict()
        self.entry_roles = {}
        self.lock = RLock()
        self.condition = Condition(self.lock)
        self.pending = {}
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

    def prepared(self, kind, path, work):
        """Retain only tiny derived values, never textures, across focus changes."""
        path = Path(path)
        stat = path.stat()
        key = (kind, str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        with self.lock:
            if key in self.prepared_values:
                self.prepared_values.move_to_end(key)
                return self.prepared_values[key]
        value = work()
        with self.lock:
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
            for key in list(self.pending):
                if key[0] not in allowed:
                    callbacks = self.pending.pop(key)[2]
                    count('images.' + callbacks[0][0].kind + '.queue_discarded')
            for key in list(self.entries):
                if key[0] not in allowed:
                    self._evict(key, 'window')

    def load(self, path, width=1920, height=1080, kind='other'):
        return timed('worker.image_load.' + kind)(self._load)(path, width, height, kind)

    def request(self, path, width, height, done, priority=1, prepare=None, kind='other'):
        ticket = SimpleNamespace(cancelled=False, kind=kind)
        key = (str(Path(path).resolve()), round(width), round(height))
        with self.condition:
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
            if all(ticket.cancelled for ticket, _, _ in callbacks):
                continue
            try:
                texture, error = self.load(*key, kind=callbacks[0][0].kind), None
            except Exception as exception:
                texture, error = None, exception
            for ticket, done, prepare in callbacks:
                result, failure = texture, error
                if not ticket.cancelled and error is None and prepare:
                    try:
                        result = prepare(texture)
                    except Exception as exception:
                        result, failure = None, exception
                def deliver(ticket=ticket, done=done, texture=result, error=failure):
                    if not ticket.cancelled:
                        done(texture, error)
                    return False
                if not ticket.cancelled:
                    GLib.idle_add(deliver)

    @timed('worker.image_load')
    def _load(self, path, width, height, kind='other'):
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
            name = hashlib.sha256(repr(('v1', key)).encode()).hexdigest() + '.png'
            thumbnail = self.disk_dir / name
            if thumbnail.is_file():
                try:
                    source_width, source_height = thumbnail_dimensions(thumbnail)
                    ratio = min(1, width / source_width, height / source_height)
                    cached_width = max(1, round(source_width * ratio))
                    cached_height = max(1, round(source_height * ratio))
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(thumbnail), cached_width, cached_height, True)
                    thumbnail.touch()
                    count('images.' + kind + '.disk_reads')
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
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height, True)
            if thumbnail is not None:
                self._queue_thumbnail(pixbuf, thumbnail)
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        size = pixbuf.get_rowstride() * pixbuf.get_height()
        with self.lock:
            # Drop stale versions of replaced files, even if they had a different size.
            for old in list(self.entries):
                if old[0] == key[0] and old[1:3] != key[1:3]:
                    self._evict(old, 'changed')
            if size <= self.max_bytes:
                while self.entries and (self.bytes + size > self.max_bytes or len(self.entries) >= 128):
                    self._evict(next(iter(self.entries)), 'budget')
                self.entries[key] = texture, size
                self.entry_roles[key] = kind
                self.bytes += size
        return texture

    def _queue_thumbnail(self, pixbuf, target):
        size = pixbuf.get_rowstride() * pixbuf.get_height()
        with self.write_condition:
            if target == self.write_active or target in self.write_queue:
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
            pixbuf.savev(temporary, 'png', ['compression'], ['3'])
            os.replace(temporary, target)
            temporary = None
            files = sorted(target.parent.glob('*.png'), key=lambda item: item.stat().st_mtime_ns)
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


def nearby_indices(count, selected, radius=1, wrap=False):
    """Unique selected/adjacent games, without inventing missing neighbours."""
    if count <= 0:
        return set()
    selected = max(0, min(count - 1, selected))
    if wrap:
        return {(selected + offset) % count for offset in range(-radius, radius + 1)}
    return set(range(max(0, selected - radius), min(count, selected + radius + 1)))
