"""Verify qt6ct palette compatibility without changing desktop configuration."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette
from qt_app.theme import apply_system_palette
app=QApplication([])
app.setDesktopFileName("io.github.estante.Test")
with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'QT_QPA_PLATFORMTHEME':'qt6ct'}):
    root=Path(folder)/'qt6ct'; (root/'colors').mkdir(parents=True)
    colors=['#131313']*22;colors[0]='#e2e2e2';colors[12]='#7e2a2b';colors[13]='#ffdad8';colors[21]='#ffb3b0'
    scheme=root/'colors/test.conf'
    scheme.write_text('[ColorScheme]\n'+'\n'.join(key+'='+','.join(colors) for key in ('active_colors','inactive_colors','disabled_colors')))
    assert apply_system_palette(app,folder)
    assert app.palette().color(QPalette.Highlight).name()=='#7e2a2b'
    assert app.palette().color(QPalette.Accent).name()=='#ffb3b0'
    (root/'qt6ct.conf').write_text('[Appearance]\ncustom_palette=false\n')
    assert not apply_system_palette(app,folder)
    (root/'qt6ct.conf').write_text('[Appearance]\ncustom_palette=true\ncolor_scheme_path=colors/test.conf\n')
    assert apply_system_palette(app,folder)
    scheme.write_text('[ColorScheme]\nactive_colors=invalid\n')
    before=app.palette()
    assert not apply_system_palette(app,folder)
    assert app.palette()==before
print('QT_THEME_OK: configured palette, accent, disabled override, invalid palette preservation')
