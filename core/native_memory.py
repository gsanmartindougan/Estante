"""Configure glibc before GTK starts workers, keeping large image buffers releasable."""
import ctypes
import os


def configure_native_allocator():
    """Keep glibc's initial 128 KiB thresholds; tolerate other allocators."""
    if os.environ.get('ESTANTE_NATIVE_ALLOCATOR') == '0':
        return False
    # Explicit process allocator tuning belongs to the caller.
    if any(name in os.environ for name in ('MALLOC_MMAP_THRESHOLD_', 'MALLOC_TRIM_THRESHOLD_')):
        return False
    if 'glibc.malloc.' in os.environ.get('GLIBC_TUNABLES', ''):
        return False
    try:
        libc = ctypes.CDLL(None)
        libc.gnu_get_libc_version  # These parameter values are glibc-specific.
        mallopt = libc.mallopt
        mallopt.argtypes = [ctypes.c_int, ctypes.c_int]
        mallopt.restype = ctypes.c_int
        # M_MMAP_THRESHOLD and M_TRIM_THRESHOLD. Setting these prevents the
        # adaptive threshold growing after decoding large PNGs. Freed large
        # buffers can then be unmapped instead of fragmenting the native heap.
        mapped = mallopt(-3, 128 * 1024)
        trimmed = mallopt(-1, 128 * 1024)
        return bool(mapped and trimmed)
    except (AttributeError, OSError):
        return False
