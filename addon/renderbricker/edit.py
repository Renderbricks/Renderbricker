"""Editing a converted part (UPDATES #18, maintainer 2026-10-06).

A converted part shows its subdivided copy; with the cache file the copy is linked from the cache and Blender refuses
Edit Mode on it ("error changing modes"), without the cache an edit of the copy is lost on the next Apply. Edits
belong on the import. The workflow:

1. Tab on a converted part: every link of its import that shows a copy switches to the import (Subdivision OFF for
   them) and Blender enters Edit Mode on it (MECSUB_OT_edit_mode, an add-on keymap entry for Tab in Object Mode).
2. Leaving Edit Mode - by Tab or any other way - converts that import again and switches the same links back ON
   (_watch notices the mode change, _reconvert runs on a timer). An import that was not changed only gets its links
   back on its existing copies.
3. With the cache file, the new copies stay in the scene until the scene is saved: then they are written into the
   cache by themselves (_cache_on_save; the other copies are carried over unchanged, cache.write_cache_steps) and the
   scene is saved once more. Until then the panel names them under Apply ("Update cache" does it at once).
An import edited with Subdivision OFF (or through the Mode menu) is converted again too when Edit Mode is left - its
links stay OFF.

Entering Edit Mode from the header's Mode menu cannot be intercepted (an add-on cannot step in front of Blender's own
operator); on a copy in the scene file it succeeds, and _watch then switches to the import as well. On a copy from the
cache Blender refuses before anything happens - only Tab works there."""
import bpy
from . import rbcore as core

EDITING = {}              # import name -> names of the objects switched to it for editing
_PENDING = [False]        # a timer for _reconvert / _swap is registered


def _settings(context):
    """The core's settings from the scene panel, as Apply sets them (convert.MECSUB_OT_apply.collect)."""
    s = context.scene.mecsub
    core.LEVELS = s.render_level
    core.VIEW_LEVEL, core.RENDER_LEVEL = s.view_level, s.render_level
    core.SHADING = "mecabricks" if s.variant == 'A' else "geometric"


def on_copy(ob):
    return ob is not None and ob.type == 'MESH' and ob.data is not None and bool(ob.data.get("rb_original"))


def begin(objs):
    """Switch every link that shows a copy of the imports of `objs` to its import; remember them. Returns the
    imports."""
    origs = {}
    for ob in objs:
        if on_copy(ob):
            orig = core.original_of(ob.data)
            if orig is not ob.data:
                origs[orig.name] = orig
    for name, orig in origs.items():
        copies = set(core.all_copies(orig))
        links = [o for o in bpy.data.objects if o.type == 'MESH' and o.data in copies]
        for o in links:
            o.data = orig
        EDITING.setdefault(name, [])
        EDITING[name] = sorted(set(EDITING[name]) | {o.name for o in links})
    return list(origs.values())


def finish_one(context, name):
    """Convert the import `name` again (or only switch its links back when it did not change). Returns a text."""
    import time
    me = bpy.data.meshes.get((name, None))
    names = EDITING.pop(name, [])
    if me is None:
        return ""
    # the links switched by Tab; none when the import was edited with Subdivision OFF - they stay OFF
    obs = [bpy.data.objects[n] for n in names if n in bpy.data.objects and bpy.data.objects[n].data == me]
    s = context.scene.mecsub
    if core.up_to_date(me, s.view_level, s.render_level):     # not changed: back on its copies
        if obs:
            core.point_links(obs, me, "view")
        return f"{me.name}: not changed" if obs else ""
    t = time.time()
    _settings(context)
    rep = core.process(me, obs)
    folds = rep.get("flipped", 0)
    return f"{me.name}: converted again ({time.time() - t:.1f} s{f', {folds} folds left' if folds else ''})"


def uncached(context=None):
    """Imports whose copies in use are in the scene file while the scene uses a cache file (edited parts)."""
    st = core.cache_state()
    if st is None:
        return []
    out = set()
    for m in bpy.data.meshes:
        if m.library is None and m.override_library is None and m.users and m.get("rb_original"):
            out.add(m["rb_original"])
    return sorted(out)


class MECSUB_OT_edit_mode(bpy.types.Operator):
    bl_idname = "mecsub.edit_mode"
    bl_label = "Edit the import"
    bl_description = ("Tab on a converted part: switch it to its import (Subdivision OFF for its links) and enter "
                      "Edit Mode - leaving Edit Mode converts it again")
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):              # (scripts and tests: invoke needs a window)
        if context.mode != 'OBJECT':
            return {'PASS_THROUGH'}
        vl = context.view_layer                      # (context.selected_objects is empty without a window)
        objs = [o for o in vl.objects.selected if o.type == 'MESH']
        if vl.objects.active is not None and vl.objects.active not in objs:
            objs.append(vl.objects.active)
        if not any(on_copy(o) for o in objs):
            return {'PASS_THROUGH'}                  # not ours: Blender's own Tab
        origs = begin(objs)
        bpy.ops.object.mode_set(mode='EDIT')
        names = ", ".join(o.name for o in origs[:3]) + (" ..." if len(origs) > 3 else "")
        self.report({'INFO'}, f"Renderbricker: editing the import of {names} - leaving Edit Mode converts it again")
        return {'FINISHED'}


class MECSUB_OT_edit_finish(bpy.types.Operator):
    bl_idname = "mecsub.edit_finish"
    bl_label = "Convert edited parts"
    bl_description = "Convert the parts edited in Edit Mode again and switch their links back on"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        texts = [t for t in (finish_one(context, n) for n in list(EDITING)) if t]
        if not texts:
            return {'CANCELLED'}
        s = context.scene.mecsub
        left = uncached(context)
        s.summary = "Edited: " + "; ".join(texts) + (
            f" - {len(left)} edited part{'s' if len(left) != 1 else ''} not in the cache yet (Update cache)" if left else "")
        from . import props
        props.refresh_state(context)
        self.report({'INFO'}, "Renderbricker: " + s.summary)
        return {'FINISHED'}


def _context_override():
    wm = bpy.context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                return dict(window=win, screen=win.screen, area=area, region=region)
    return dict(window=wm.windows[0]) if wm.windows else {}


def _run_finish():
    _PENDING[0] = False
    if not EDITING:
        return None
    if bpy.context.mode != 'OBJECT':                 # still (or again) editing
        return None
    try:
        with bpy.context.temp_override(**_context_override()):
            bpy.ops.mecsub.edit_finish()
    except Exception:
        import traceback
        traceback.print_exc()
    return None


def _run_swap():
    """Edit Mode entered on a copy in the scene file (the Mode menu): leave it, switch to the import, enter again."""
    _PENDING[0] = False
    ob = bpy.context.active_object
    if not (on_copy(ob) and ob.mode == 'EDIT'):
        return None
    try:
        with bpy.context.temp_override(**_context_override()):
            bpy.ops.object.mode_set(mode='OBJECT')
            objs = [o for o in bpy.context.view_layer.objects.selected if o.type == 'MESH'] or [ob]
            if ob not in objs:
                objs.append(ob)
            begin(objs)
            bpy.ops.object.mode_set(mode='EDIT')
    except Exception:
        import traceback
        traceback.print_exc()
    return None


@bpy.app.handlers.persistent
def _watch(scene, depsgraph=None):
    """After every update: Edit Mode left while parts are being edited -> convert them; Edit Mode on a copy in
    the scene file -> switch to its import. Cheap when nothing is being edited."""
    if _PENDING[0]:
        return
    try:
        mode = bpy.context.mode
        ob = bpy.context.active_object
    except AttributeError:
        return
    if EDITING and mode == 'OBJECT':
        _PENDING[0] = True
        bpy.app.timers.register(_run_finish, first_interval=0.05)
    elif mode == 'EDIT_MESH' and on_copy(ob):
        _PENDING[0] = True
        bpy.app.timers.register(_run_swap, first_interval=0.05)
    elif mode == 'EDIT_MESH' and ob is not None and ob.type == 'MESH' and ob.data is not None             and ob.data.library is None and (ob.data.get("rb_view") or ob.data.get("rb_render"))             and ob.data.name not in EDITING:
        EDITING[ob.data.name] = []             # a converted import edited with Subdivision OFF: convert it after


_CACHING = [False]


def _run_cache_update():
    """Write the edited parts into the cache and save again (after a save, UPDATES #18: automatic, the user
    would forget the button)."""
    if _CACHING[0] or not uncached():
        return None
    _CACHING[0] = True
    try:
        with bpy.context.temp_override(**_context_override()):
            bpy.ops.mecsub.cache_switch('EXEC_DEFAULT', target=True, save_after=True)
    except Exception:
        _CACHING[0] = False
        import traceback
        traceback.print_exc()
    return None


@bpy.app.handlers.persistent
def _cache_on_save(*_args):
    """After a save: edited parts whose copies are still in the scene file go into the cache file, then the scene
    is saved once more. Not for a cache of another scene (Save As elsewhere: Move / Copy cache decide that)."""
    if bpy.app.background or _CACHING[0]:
        return
    st = core.cache_state()
    if st is None or not st[3] or st[1] != st[2] or not uncached():
        return
    bpy.app.timers.register(_run_cache_update, first_interval=0.2)


@bpy.app.handlers.persistent
def _forget(*_args):
    """A file was loaded: nothing of the old one is being edited."""
    EDITING.clear()
    _PENDING[0] = False


_keymaps = []


def register_keymap():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        # Blender's own Tab (object.mode_set, toggle) lives in "Object Non-modal"; an add-on entry there is tried
        # first and passes the key on when the part is not converted
        km = kc.keymaps.new(name="Object Non-modal", space_type='EMPTY')
        kmi = km.keymap_items.new(MECSUB_OT_edit_mode.bl_idname, 'TAB', 'PRESS')
        _keymaps.append((km, kmi))


def unregister_keymap():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
