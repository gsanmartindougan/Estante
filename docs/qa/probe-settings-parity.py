"""Read-only parity observations apart from a disposable settings profile."""
import os,sys,tempfile,json
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PySide6.QtWidgets import QApplication
from qt_app.main import LibraryController
from core.library import Library
app=QApplication([])
observations=[]
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);game=dict(id='probe',title='QA',kind='custom');Library(data_dir=root).put(game)
 c=LibraryController([game],{},root,allow_launch=False)
 for label,values in [
  ('missing-global-image',[dict(path=['background_source'],value='global'),dict(path=['global_background'],value=str(root/'missing.png'))]),
  ('invalid-ring-color',[dict(path=['selection_rings','grid','focus_ring_color'],value='not-a-color')])]:
  c.manager.saveSettingValues(values)
  saved=json.loads((root/'settings.json').read_text())
  observations.append(dict(case=label,message=c.manager.message,persisted=(saved.get('background_source')=='global' and saved.get('global_background')==str(root/'missing.png')) if label=='missing-global-image' else saved['selection_rings']['grid']['focus_ring_color']=='not-a-color'))
 c.manager.shutdown();c.idle_timer.stop()
print(json.dumps(observations,indent=2,ensure_ascii=False))
