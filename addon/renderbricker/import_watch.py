"""A model that arrives in the scene goes into the collection list by itself (UPDATES #41).

The importers put every model into a collection of its own. With the scope Collection that collection has to be in
the list before Apply does anything; up to 1.2.7 only the add-on's own button "Import from Mecabricks" put it there.
The maintainer imported through the importer's own panel and found the list empty (2026-10-11: "Nach dem Import
sollte wie im Gaussian Splat Addon automatisch eine Collection hinzugefügt werden, weil das Addon ja eine Collection
anlegt."). So the scene is watched, whoever imports: File > Import, the importer's panel, this add-on's button,
Mecabricks or LDraw.

What counts as an arrival: a collection the scene did not have, with mesh objects the scene did not have either. A
collection made by hand from parts that were there (M > New Collection) brings no new objects and is left alone - the
user decides about those with +. There is no test whether the meshes are LEGO parts (maintainer, the same day:
"Keine Erkennung."): a collection appended from another file is listed too, and the line under the panel says so.

The watch costs two numbers per depsgraph update (how many collections and objects the file has). Only when they
change does a timer wait until they stand still - importers add their objects over many updates, Mecabricks Advanced
links the collection at the end - and then compares the names once."""
import bpy
from bpy.app.handlers import persistent
from . import collection_list, props

SETTLE = 0.5                # seconds the numbers have to stand still before the scene is compared
_KNOWN = {}                 # scene name -> (collection names, object names) at the last comparison
_COUNTS = {}                # scene name -> (collections, objects) of the file at the last look
_PENDING = [None]           # the scene whose numbers are settling, and the numbers of the last tick


def _counts():
    return len(bpy.data.collections), len(bpy.data.objects)


def snapshot(scene):
    """Remember what the scene holds now - nothing of it counts as arrived later."""
    _KNOWN[scene.name] = ({c.name for c in collection_list.scene_collections(scene)}, {o.name for o in scene.objects})
    _COUNTS[scene.name] = _counts()


def arrived(scene):
    """The collections that came into the scene with mesh objects of their own since the last snapshot - the
    models, not their child collections. Empty without a snapshot."""
    known = _KNOWN.get(scene.name)
    if known is None:
        return []
    had_collections, had_objects = known
    new = []
    for c in collection_list.scene_collections(scene):
        if c.name in had_collections or c.name in props.OWN_COLLECTIONS:
            continue
        meshes = [o for o in c.all_objects if o.type == 'MESH']
        if meshes and not any(o.name in had_objects for o in meshes):
            new.append(c)
    return [c for c in new if not any(c in p.children_recursive for p in new)]


def check(scene):
    """Compare the scene with its snapshot, list what arrived and take a new snapshot. Returns the collections
    added to the list. While Apply or another run of the add-on works, only the snapshot is taken."""
    s = getattr(scene, "mecsub", None)
    added = []
    if s is not None and not s.running:
        new = arrived(scene)
        if new:
            added = props.list_collections(s, new)
            if added:
                s.summary = (f"{' and '.join(c.name for c in added)} added to the collection list - "
                             f"Apply converts every mesh in {'it' if len(added) == 1 else 'them'}")
    snapshot(scene)
    return added


def import_busy():
    """An importer's file dialog is open or its import runs (a modal operator named import_...)."""
    for win in bpy.context.window_manager.windows:
        if any(a.type == 'FILE_BROWSER' for a in win.screen.areas):
            return True
        if any(op.bl_idname.upper().startswith("IMPORT_") for op in win.modal_operators):
            return True
    return False


def _settle():
    """Timer: wait until the numbers stand still and no import runs, then compare once."""
    if _PENDING[0] is None:
        return None
    name, last = _PENDING[0]
    scene = bpy.data.scenes.get(name)
    if scene is None:
        _PENDING[0] = None
        return None
    now = _counts()
    if now != last or import_busy():
        _PENDING[0] = (name, now)
        return SETTLE
    _PENDING[0] = None
    if check(scene):
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    return None


@persistent
def on_depsgraph(scene, depsgraph=None):
    """Cheap unless something arrived or left: two lengths and a comparison."""
    if bpy.app.background or _PENDING[0] is not None:
        return
    if scene.name not in _KNOWN:            # the first look at this scene: what it holds is not an arrival
        snapshot(scene)
        return
    now = _counts()
    if now == _COUNTS.get(scene.name):
        return
    _PENDING[0] = (scene.name, now)
    bpy.app.timers.register(_settle, first_interval=SETTLE)


@persistent
def on_load(*_args):
    """Another file: nothing of the old one is known."""
    forget()


def forget():
    if bpy.app.timers.is_registered(_settle):
        bpy.app.timers.unregister(_settle)
    _KNOWN.clear()
    _COUNTS.clear()
    _PENDING[0] = None
