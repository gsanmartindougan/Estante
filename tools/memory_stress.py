"""Exercise controller repetition, settings and all library layouts in a temporary profile.

Run from the graphical desktop. The window closes automatically. Original images
are read through symlinks; library/settings writes and caches stay in temporary
storage unless a dedicated --cache-dir is explicitly supplied.
"""
import argparse, collections, gc, json, os, shutil, sys, tempfile, traceback, weakref
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
parser=argparse.ArgumentParser(description='Isolated GTK memory stress test; leaves the user library unchanged.')
parser.add_argument('--cycles',type=int,default=3)
parser.add_argument('--output',default='/tmp/estante-memory-stress.jsonl')
parser.add_argument('--cache-dir',type=Path,help='Dedicated diagnostic cache to reuse between runs')
parser.add_argument('--skip-idle-reclaim',action='store_true',help='Baseline comparison without idle cleanup')
parser.add_argument('--expand-settings',action='store_true')
parser.add_argument('--games',type=int,help='Synthetic game count, with independent copies of original artwork')
parser.add_argument('--manual',action='store_true',help='Keep the isolated library open for controller testing')
args=parser.parse_args()
if args.cycles < 1:parser.error('--cycles must be positive')
if args.games is not None and args.games < 1:parser.error('--games must be positive')
source=Path(os.environ.get('ESTANTE_DATA_DIR', Path.home()/'.local/share/estante'))
temporary=tempfile.TemporaryDirectory(prefix='estante-memory-debug-')
root=Path(temporary.name);data=root/'data';data.mkdir()
shutil.copyfile(source/'library.json',data/'library.json')
settings=json.loads((source/'settings.json').read_text());settings.update(check_updates_on_start=False,screensaver_enabled=False)
(data/'settings.json').write_text(json.dumps(settings));(data/'settings.json').chmod(0o600)
for path in source.iterdir():
 if path.is_dir():(data/path.name).symlink_to(path.resolve(),target_is_directory=True)
if args.games:
 from library import Library
 from tools.memory_fixture import populate_test_games
 populate_test_games(Library(data_dir=data),args.games)
os.environ['ESTANTE_DATA_DIR']=str(data)
os.environ['ESTANTE_MEMORY_DIAGNOSTICS']='0'
# Separate cache permits cold/warm observations without deleting the user's cache.
os.environ['XDG_CACHE_HOME']=str(args.cache_dir.resolve() if args.cache_dir else root/'cache')
from estante import App, Shelf, Gtk, GLib
if args.skip_idle_reclaim: Shelf.schedule_artwork_reclaim=lambda self: None
from image_cache import images,memory_usage,reclaim_unused_memory
app=App();app.set_application_id('io.github.estante.MemoryDebugP'+str(os.getpid()))
refs=[];state={'steps':0,'failed':False};output=Path(args.output);output.write_text('')
def children(widget):
 yield widget
 child=widget.get_first_child()
 while child:
  yield from children(child)
  child=child.get_next_sibling()
def sample(label):
 shelf=app.window
 counts=collections.Counter(type(obj).__name__ for obj in gc.get_objects() if isinstance(obj,Gtk.Widget))
 row={'label':label,'library_games':len(shelf.library_games),'category_tiles':len(shelf.tiles()),'visited_games':len(state.get('visited',set())),**memory_usage(),'cache_MiB':round(images.bytes/1048576,2),'writer_MiB':round(images.write_bytes/1048576,2),'cache_entries':len(images.entries),'pending':len(images.pending),'active':len(images.loading),'weak_settings_alive':sum(ref() is not None for ref in refs),'widget_wrappers':dict(counts.most_common(12))}
 renderer=shelf.get_renderer();row['renderer']=renderer.__gtype__.name if renderer else None
 with output.open('a') as stream:stream.write(json.dumps(row)+'\n')
 print(json.dumps(row),flush=True)
def after(delay,callback):
 def invoke():
  try:callback()
  except Exception:
   state['failed']=True;traceback.print_exc();app.quit()
  return False
 GLib.timeout_add(delay,invoke)
def finish():
 sample('final_before_gc');reclaim_unused_memory();sample('final_after_gc');app.quit()
def hold(cycle):
 shelf=app.window;shelf.focus_library();state['steps']=0;state['visited']={shelf.selected_game}
 def step():
  shelf.navigate('right',True);state['steps']+=1;state['visited'].add(shelf.selected_game)
  if state['steps']>=max(50,args.games or 0):
   after(2000,lambda:post_hold(cycle));return False
  return True
 GLib.timeout_add(130,step)
def post_hold(cycle):
 sample(f'{cycle}_after_dpad');after(300,lambda:open_settings(cycle))
def open_settings(cycle):
 app.window.preferences();refs.append(weakref.ref(app.window.preferences_view))
 if args.expand_settings:
  for widget in children(app.window.preferences_view):
   if isinstance(widget,Gtk.Revealer):widget.set_reveal_child(True)
 after(1500,lambda:settings_sections(cycle))
def settings_sections(cycle):
 sample(f'{cycle}_settings_global')
 view=app.window.preferences_view
 view.show_section('list');view.show_section('global')
 after(750,lambda:close_settings(cycle))
def close_settings(cycle):
 app.window.leave_preferences();after(2000,lambda:post_settings(cycle))
def post_settings(cycle):
 sample(f'{cycle}_after_settings');switch_mode(cycle,0)
def switch_mode(cycle,index):
 modes=('grid','ps5','carousel','list')
 if index==len(modes):
  if cycle+1<args.cycles:after(300,lambda:hold(cycle+1))
  else:after(1000,finish)
  return
 shelf=app.window;shelf.view_mode=modes[index];shelf.configure_view();shelf.reload();shelf.focus_library()
 after(800,lambda:(sample(f'{cycle}_mode_{modes[index]}'),switch_mode(cycle,index+1)))
def setup():
 shelf=app.window;shelf.set_title('Estante · diagnóstico de memoria')
 if args.manual:
  shelf.set_title(f'Estante · prueba manual · {len(shelf.library_games)} juegos')
  print('Perfil temporal de prueba; cierra esta ventana para terminar.',flush=True)
  after(2500,lambda:sample('manual_baseline'))
 else:
  if shelf.gamepad_timer:GLib.source_remove(shelf.gamepad_timer);shelf.gamepad_timer=None
  if shelf.gamepad:shelf.gamepad.close();shelf.gamepad=None
  after(2500,lambda:(sample('baseline'),hold(0)))
app.connect('activate',lambda *_:GLib.idle_add(lambda:(setup(),False)[1]))
app.run([sys.argv[0]])
print('DEBUG_DONE',args.output,flush=True)
temporary.cleanup()
sys.exit(int(state['failed']))
