"""Screensaver timing and legacy setting compatibility."""

def time_choice(settings, kind):
    """Editable 1–60 value/unit, including legacy seconds/minutes settings."""
    prefix = 'screensaver_' + kind
    if prefix + '_value' in settings:
        value = max(1, min(60, int(settings[prefix + '_value'])))
        unit = settings.get(prefix + '_unit', 'seconds')
        return value, 'minutes' if unit == 'minutes' else 'seconds'
    if kind == 'idle':
        return max(1, min(60, int(settings.get('screensaver_minutes', 5)))), 'minutes'
    seconds = max(1, int(settings.get('screensaver_interval', 20)))
    return (seconds, 'seconds') if seconds <= 60 else (min(60, max(1, round(seconds / 60))), 'minutes')


def time_seconds(settings, kind):
    if 'screensaver_' + kind + '_value' not in settings:
        return (max(1, int(settings.get('screensaver_minutes', 5))) * 60 if kind == 'idle'
                else max(1, int(settings.get('screensaver_interval', 20))))
    value, unit = time_choice(settings, kind)
    return value * (60 if unit == 'minutes' else 1)
