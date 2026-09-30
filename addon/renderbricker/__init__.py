"""Renderbricker - Blender add-on for Mecabricks imports (registration; the code is in the modules)."""
bl_info = {
    "name": "Renderbricker",
    "author": "Renderbricks® – Prof. Michael Klein",
    "version": (1, 0, 1),
    "blender": (4, 5, 0),
    "location": "3D Viewport > Sidebar > Renderbricker",
    "description": "Creases and subdivision for imported Mecabricks parts: each mesh is processed once, "
                   "its links use the subdivided copy - the original mesh stays untouched",
    "doc_url": "https://github.com/Renderbricks/Renderbricker",
    "tracker_url": "https://github.com/Renderbricks/Renderbricker/issues",
    "category": "Object",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import PointerProperty
from . import rbcore as core
# Reload Scripts / re-enabling runs this file again, but Python keeps the modules in memory: the header
# showed 1.5.4 while the rules of 1.5.3 ran (run 42). So every module is reloaded explicitly.
if "props" in locals():
    import importlib
    core.reload_all()
    for _m in (common, props, render, camera_ui, logfile, widgets, convert, operators, guide, panels):
        importlib.reload(_m)
from . import common, props, render, camera_ui, logfile, widgets, convert, operators, guide, panels

# the package reads and writes like one module: renderbricker.NAME finds NAME in the module that holds it,
# renderbricker.NAME = value sets it there (the tests replace open_file and start_script)
import sys as _sys, types as _types


def _owners(modules):
    """name -> module that defines it: everything a module binds itself (functions and classes defined
    there, its constants); names it imported (bpy, other modules, their functions) are left out."""
    out = {}
    for m in modules:
        short = m.__name__.rsplit(".", 1)[1]
        for name, value in vars(m).items():
            if name.startswith("__") or isinstance(value, _types.ModuleType):
                continue
            home = getattr(value, "__module__", None)
            if callable(value) and home is not None and home != m.__name__:
                continue
            out.setdefault(name, short)
    return out


OWNER = _owners((common, props, render, camera_ui, logfile, widgets, convert, operators, guide, panels))


class _Package(_types.ModuleType):
    def __getattr__(self, name):
        m = OWNER.get(name)
        if m is None:
            raise AttributeError(f"renderbricker has no {name!r}")
        return getattr(_sys.modules[__name__ + "." + m], name)

    def __setattr__(self, name, value):
        m = OWNER.get(name) if name != "OWNER" else None
        if m is not None and m != name:
            setattr(_sys.modules[__name__ + "." + m], name, value)
        else:
            super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _Package


classes = (props.MECSUB_Problem, props.MECSUB_CollectionItem, props.MECSUB_Settings, props.MECSUB_UL_collections,
           props.MECSUB_OT_collection_add, props.MECSUB_OT_collection_remove, logfile.MECSUB_OT_open_log, convert.MECSUB_OT_apply, convert.MECSUB_OT_check, convert.MECSUB_OT_levels, operators.MECSUB_OT_toggle,
           operators.MECSUB_OT_remove, operators.MECSUB_OT_select, operators.MECSUB_OT_headless, panels.MECSUB_PT_panel, operators.MECSUB_OT_move_cache, operators.MECSUB_OT_copy_cache,
           operators.MECSUB_OT_cache_switch, render.MECSUB_OT_render, panels.MECSUB_PT_about,
           guide.MECSUB_OT_guide_start, guide.MECSUB_OT_guide_nav, guide.MECSUB_OT_guide_exit, props.MECSUB_OT_level_confirm,
           camera_ui.MECSUB_OT_frame_camera, camera_ui.MECSUB_OT_render_camera, camera_ui.MECSUB_OT_camera_view, camera_ui.MECSUB_OT_samples,
           render.MECSUB_OT_render_views, camera_ui.MECSUB_OT_sun_follow,
           camera_ui.MECSUB_OT_transparent)


@persistent
def _unlock(*args):
    """A progress state saved or left behind by a crashed or stuck run must not lock the
    panel: nothing can be running when a file is loaded or the add-on is (re)registered.
    A missing cache file (moved or deleted): the objects show their originals (run 62)."""
    for sc in bpy.data.scenes:
        if getattr(sc, "mecsub", None) and sc.mecsub.running:
            sc.mecsub.running = False
        if getattr(sc, "mecsub", None) and sc.mecsub.collection is not None and not len(sc.mecsub.collections):
            sc.mecsub.collections.add().collection = sc.mecsub.collection
    try:
        relinked = core.relink_cache_on_load()      # scene and cache moved or renamed together
    except Exception:
        relinked = False
    try:
        n = core.cache_missing_fix()
    except Exception:
        n = 0
    try:
        core.override_materials()               # cache copies: materials of the original on the mesh
    except Exception:
        pass
    try:
        props.refresh_state()
    except Exception:
        pass
    if relinked:
        for sc in bpy.data.scenes:
            if getattr(sc, "mecsub", None):
                sc.mecsub.summary = "Cache file found next to the scene and linked again - save the scene to keep it"
    if n:
        for sc in bpy.data.scenes:
            if getattr(sc, "mecsub", None):
                sc.mecsub.summary = (f"Cache file missing: {n} objects show their original mesh, "
                                     f"Apply again to rebuild it")
    return None


HANDLERS = ((bpy.app.handlers.render_pre, render._render_pre), (bpy.app.handlers.render_post, render._render_post),
            (bpy.app.handlers.render_cancel, render._render_post), (bpy.app.handlers.load_post, _unlock),
            (bpy.app.handlers.render_cancel, render._views_cancelled))


def register():
    # always load the rule module fresh: re-enabling or Reload Scripts kept the old one
    # in memory (header 1.5.4, rules of 1.5.3 - run 42)
    core.reload_all()
    import os
    import bpy.utils.previews
    pc = bpy.utils.previews.new()
    logo = os.path.join(os.path.dirname(__file__), "icons", "renderbricks_logo.png")
    if os.path.isfile(logo):
        pc.load("logo", logo, 'IMAGE')
    panels._icons["main"] = pc
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.mecsub = PointerProperty(type=props.MECSUB_Settings)
    for lst, fn in HANDLERS:
        if fn not in lst:
            lst.append(fn)
    bpy.app.timers.register(_unlock, first_interval=0.1)     # after (re)installing in a stuck session
    bpy.types.TOPBAR_MT_render.prepend(render._render_menu)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:                                   # F12 / Ctrl+F12 switch the level in the main thread (run 72)
        km = kc.keymaps.new(name="Screen", space_type='EMPTY')
        kmi = km.keymap_items.new(render.MECSUB_OT_render.bl_idname, 'F12', 'PRESS')
        kmi.properties.use_viewport = True
        render._keymaps.append((km, kmi))
        kmi = km.keymap_items.new(render.MECSUB_OT_render.bl_idname, 'F12', 'PRESS', ctrl=True)
        kmi.properties.animation = True
        kmi.properties.use_viewport = True
        render._keymaps.append((km, kmi))


def unregister():
    import bpy.utils.previews
    for pc in panels._icons.values():
        bpy.utils.previews.remove(pc)
    panels._icons.clear()
    for km, kmi in render._keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    render._keymaps.clear()
    if bpy.app.timers.is_registered(render._views_tick):
        bpy.app.timers.unregister(render._views_tick)
    render._VIEWS.clear()
    bpy.types.TOPBAR_MT_render.remove(render._render_menu)
    for lst, fn in HANDLERS:
        if fn in lst:
            lst.remove(fn)
    del bpy.types.Scene.mecsub
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
