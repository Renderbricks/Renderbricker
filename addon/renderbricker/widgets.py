"""Panel pieces used by the panel and the Start Guide: summary, bullets, levels, Apply button."""
import bpy
from . import rbcore as core
from . import props


# ---------------------------------------------------------------- guide for new users
def draw_summary(L, s):
    """Result of the last operator and the problem list (select button per entry)."""
    if not s.summary or s.running:
        return
    import bpy as _bpy
    box = L.box()
    bullets(box, s.summary.split(", "), _bpy.context)
    if len(s.problems):
        col = box.column(align=True)
        col.scale_y = 0.9
        for p in list(s.problems)[:12]:
            r = col.row(align=True)
            r.alert = True
            r.label(text=f"•  {p.obj}: {p.info}")
            r.operator("mecsub.select", text="", icon='RESTRICT_SELECT_OFF').obj = p.obj
        if len(s.problems) > 12:
            col.label(text=f"   ... {len(s.problems) - 12} more" + (" - all in the log file" if s.use_log else ""))


def bullets(layout, items, context, prefix="•  "):
    """Explanations as bullet points, wrapped to the sidebar width."""
    import textwrap
    width = context.region.width if context.region else 300
    chars = max(20, int(width / (7.5 * context.preferences.system.ui_scale)))
    col = layout.column(align=True)
    col.scale_y = 0.8
    for text in items:
        for line in textwrap.wrap(text, chars, initial_indent=prefix, subsequent_indent=" " * len(prefix)):
            col.label(text=line)


def status(layout, ok, text):
    row = layout.row()
    row.alert = not ok
    row.label(text=text, icon='CHECKMARK' if ok else 'INFO')


def draw_levels(L, s, context):
    """Viewport / render level with a warning above 2 (user, 2026-09-28): every level multiplies the
    faces by three to four - level 3 costs a lot of memory and time for hardly visible gain."""
    col = L.column(align=True)
    col.label(text="Subdivision levels")
    col.prop(s, "view_level")
    col.prop(s, "render_level")
    if s.view_level > 2 or s.render_level > 2:
        box = L.box()
        box.alert = True
        bullets(box, ("Levels above 2 multiply the faces again by three to four: memory, file size and "
                      "conversion time grow a lot, the visible gain is small. 2 is enough for close-ups.",),
                context, prefix="")


def scope_state(context):
    """(ok, text) for the choice of parts - cheap enough for draw(): stops at the first mesh."""
    s = context.scene.mecsub
    if s.scope == 'SELECTED':
        ok = any(o.type == 'MESH' for o in context.selected_objects)
        return ok, "Parts selected" if ok else "Select the parts to convert"
    cols = props.scope_collections(s)
    if not cols:
        return False, "Add a collection"
    ok = any(o.type == 'MESH' for c in cols for o in c.all_objects)
    return ok, (f"Parts in {', '.join(c.name for c in cols)}" if ok else "The collections have no parts")


_AFTER_SAVE = []          # the one pending "continue after the first save" handler (UPDATES #21)


def continue_after_save(context, idname, **kwargs):
    """Run the operator `idname` again once the scene has been saved for the first time - Apply, Write cache and
    Convert headless open Save As on an unsaved scene and continue by themselves afterwards (maintainer
    2026-10-06). One shot: removed after the next save; a save more than ten minutes later (the dialog was
    cancelled and the scene saved some other time) does not start it."""
    import time
    for h in _AFTER_SAVE:
        if h in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.remove(h)
    _AFTER_SAVE.clear()
    win, area, region, t0 = context.window, context.area, context.region, time.time()

    def handler(*_args):
        if handler in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.remove(handler)
        _AFTER_SAVE.clear()
        if time.time() - t0 > 600:
            return

        def run():
            op = getattr(getattr(bpy.ops, idname.split(".")[0]), idname.split(".")[1])
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    op('INVOKE_DEFAULT', **kwargs)
            except Exception:                      # the window or area went away: any 3D view
                from . import edit
                try:
                    with bpy.context.temp_override(**edit._context_override()):
                        op('INVOKE_DEFAULT', **kwargs)
                except Exception:
                    import traceback
                    traceback.print_exc()
            return None
        bpy.app.timers.register(run, first_interval=0.2)

    _AFTER_SAVE.append(handler)
    bpy.app.handlers.save_post.append(handler)


def save_as_name(context):
    """File name offered when the scene is saved the first time: the name of the imported model - the
    top collection with the most mesh objects, as a Mecabricks import brings one (user, 2026-09-29)."""
    import re
    best, n = None, 0
    for c in context.scene.collection.children:
        k = sum(1 for o in c.all_objects if o.type == 'MESH')
        if k > n:
            best, n = c, k
    name = re.sub(r'[\\/:*?"<>|]+', "_", best.name).strip(" .") if best else ""
    return (name or "untitled") + ".blend"


def draw_low_memory(L, s):
    sp = L.split(factor=0.4)                # the label in full, the three buttons beside it
    sp.active = s.use_cores
    sp.label(text="Low Memory")
    sp.row(align=True).prop(s, "low_memory", expand=True)


APPLIED_KEY = "rb_applied"      # scene: what the last Apply covered (apply_key)


def apply_key(context):
    """Settings, scope and the number of meshes and objects - when it is the same as after the last
    Apply, there is nothing to do (cheap enough for drawing; new parts change the numbers)."""
    s = context.scene.mecsub
    scope = s.scope
    if scope == 'SELECTED':
        scope += f":{len(context.selected_objects)}:{getattr(context.active_object, 'name', '')}"
    else:
        scope += ":" + ",".join(sorted(c.collection.name for c in s.collections if c.collection))
    objs = context.scene.objects
    n = len(objs) - (1 if objs.get(core.CAMERA_NAME) else 0)     # the render camera is not a part
    return f"{s.variant}|{s.view_level}|{s.render_level}|{scope}|{core.RULES_VERSION}|{len(bpy.data.meshes)}|{n}"


def apply_button(L, context, **kw):
    """Apply, or "Apply: up to date" when the last Apply covered the same (user, 2026-09-29)."""
    if context.scene.get(APPLIED_KEY) == apply_key(context):
        return L.operator("mecsub.apply", text="Apply: up to date", icon='CHECKMARK', **kw)
    return L.operator("mecsub.apply", icon='MOD_SUBSURF', **kw)
