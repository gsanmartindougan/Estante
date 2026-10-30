"""Opt-in, bounded timing samples for the graphical profiling tool."""
from collections import deque
from functools import wraps
import os
from threading import Lock
from time import perf_counter

ENABLED = os.environ.get('ESTANTE_PROFILE') == '1'
_samples = {}
_counters = {}
_lock = Lock()


def timed(name):
    def decorate(function):
        if not ENABLED:
            return function
        @wraps(function)
        def measured(*args, **kwargs):
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = (perf_counter() - started) * 1000
                with _lock:
                    entry = _samples.setdefault(name, [0, 0., 0., deque(maxlen=10000)])
                    entry[0] += 1
                    entry[1] += elapsed
                    entry[2] = max(entry[2], elapsed)
                    entry[3].append(elapsed)
        return measured
    return decorate


def count(name, amount=1):
    if ENABLED:
        with _lock:
            _counters[name] = _counters.get(name, 0) + amount


def counters():
    with _lock:
        return dict(sorted(_counters.items()))


def reset():
    with _lock:
        _samples.clear()
        _counters.clear()


def report():
    with _lock:
        result = {}
        for name, (count, total, maximum, samples) in sorted(_samples.items()):
            ordered = sorted(samples)
            result[name] = {
                'calls': count, 'total_ms': round(total, 3),
                'mean_ms': round(total / count, 3), 'max_ms': round(maximum, 3),
                'p95_ms': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 3),
                'sample_count': len(ordered),
            }
        return result
