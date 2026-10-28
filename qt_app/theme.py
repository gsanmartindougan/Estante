"""Read qt6ct palettes when wheel-provided Qt cannot load its platform plugin."""
import configparser
import os
from pathlib import Path
from PySide6.QtGui import QColor, QPalette


def apply_system_palette(app, config_root=None):
    if os.environ.get('QT_QPA_PLATFORMTHEME', '').split(':')[0] != 'qt6ct':
        return False
    root = Path(config_root or os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'qt6ct'
    config = configparser.ConfigParser(interpolation=None)
    config.read(root/'qt6ct.conf')
    appearance = config['Appearance'] if config.has_section('Appearance') else {}
    if appearance.get('custom_palette', 'true').lower() == 'false':
        return False
    selected = appearance.get('color_scheme_path', '')
    if selected:
        path = Path(selected).expanduser()
        if not path.is_absolute(): path = root/path
    elif not (root/'qt6ct.conf').exists():
        # Generated desktop palettes may exist without the qt6ct settings utility.
        candidates = list((root/'colors').glob('*.conf'))
        if len(candidates) != 1: return False
        path = candidates[0]
    else:
        return False
    scheme = configparser.ConfigParser(interpolation=None)
    scheme.read(path)
    if not scheme.has_section('ColorScheme'): return False
    palette = QPalette(app.palette())
    groups = [('active_colors', QPalette.Active), ('inactive_colors', QPalette.Inactive), ('disabled_colors', QPalette.Disabled)]
    for key, group in groups:
        values = scheme['ColorScheme'].get(key, '').split(',')
        if len(values) < 21: return False
        for index, value in enumerate(values[:22]):
            if index == 17: continue  # NoRole is not a color role.
            color = QColor(value.strip())
            if not color.isValid(): return False
            palette.setColor(group, QPalette.ColorRole(index), color)
    app.setPalette(palette)
    return True
