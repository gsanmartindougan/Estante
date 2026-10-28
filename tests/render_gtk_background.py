"""Render the original GTK hero widget as a reference for Qt parity checks."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from estante import Gtk,Gdk,Graphene,TopAlignedPicture
Gtk.init()
width,height=int(sys.argv[3]),int(sys.argv[4])
picture=TopAlignedPicture()
picture.set_paintable(Gdk.Texture.new_from_filename(sys.argv[1]))
picture.position=sys.argv[5]
picture.split_mode=sys.argv[6]
if sys.argv[2]!='-': picture.secondary_texture=Gdk.Texture.new_from_filename(sys.argv[2])
window=Gtk.Window();window.set_child(picture);window.realize()
picture.allocate(width,height,-1,None)
snapshot=Gtk.Snapshot();picture.do_snapshot(snapshot)
texture=window.get_renderer().render_texture(snapshot.to_node(),Graphene.Rect().init(0,0,width,height))
texture.save_to_png(sys.argv[7])
window.destroy()
