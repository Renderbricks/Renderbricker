bl_info = {
    "name": "Renderbricker",
    "author": "Renderbricks® – Prof. Michael Klein",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "3D Viewport > Sidebar > Renderbricker",
    "description": "Creases and subdivision for imported Mecabricks parts: each mesh is processed once, "
                   "its links use the subdivided copy - the original mesh stays untouched",
    "doc_url": "https://github.com/Renderbricks/Renderbricker",
    "tracker_url": "https://github.com/Renderbricks/Renderbricker/issues",
    "category": "Object",
}

import time
import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, IntProperty, StringProperty, CollectionProperty, PointerProperty
# Reload Scripts / re-enabling reloads this file but kept the old rule module in memory:
# the header showed 1.5.4 while the rules of 1.5.3 ran (run 42). Reload it explicitly.
if "core" in locals():
    import importlib
    core = importlib.reload(core)
else:
    from . import core


# ---------------------------------------------------------------- helpers
def targets(context):
    s = context.scene.mecsub
    if s.scope == 'SELECTED':
        obs = context.selected_objects
    elif s.scope == 'COLLECTION':           # the collection and its child collections, objects of this scene
        obs = [o for o in s.collection.all_objects if context.scene.objects.get(o.name) is o] if s.collection else []
    else:
        obs = context.scene.objects
    return [o for o in obs if o.type == 'MESH' and o.data.polygons and not core.is_master(o)
            and o.name != core.WORK_NAME]

def object_mode(context):
    """Mesh data in Edit Mode is empty from Python (attributes of length 0: 'foreach_set ...
    needed 0', run 39) - leave it before working on meshes."""
    if context.mode != 'OBJECT' and context.object:
        bpy.ops.object.mode_set(mode='OBJECT')

def by_mesh(obs):
    """Objects grouped by their original mesh (links of one mesh together)."""
    out = {}
    for o in obs:
        out.setdefault(core.original_of(o.data), []).append(o)
    return out

def seam_gaps(me, ev, level):
    """Largest distance between subdivided points that must coincide: at shared boundary
    vertices and along shared boundary edges (same check as verify_part). me: original,
    ev: its subdivided copy."""
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me)
    P = lambda co: tuple(round(c, 4) for c in co)
    gv = 0.0
    groups = {}
    for v in bm.verts:
        if v.is_boundary:
            groups.setdefault(P(v.co), []).append(v.index)
    for g in groups.values():
        if len(g) > 1:
            pts = [ev.vertices[i].co for i in g]
            gv = max(gv, max((a - b).length for a in pts for b in pts))
    ge = 0.0
    inner, nv = 2 ** level - 1, len(me.vertices)
    if len(ev.vertices) >= nv + inner * len(me.edges):
        pairs = {}
        for e in bm.edges:
            if e.is_boundary:
                pairs.setdefault(frozenset((P(e.verts[0].co), P(e.verts[1].co))), []).append((e.index, P(e.verts[0].co)))
        for es in pairs.values():
            if len(es) < 2:
                continue
            i0, a0 = es[0]
            ref = [ev.vertices[nv + inner * i0 + k].co for k in range(inner)]
            for i1, a1 in es[1:]:
                pts = [ev.vertices[nv + inner * i1 + k].co for k in range(inner)]
                if a1 != a0:
                    pts = pts[::-1]
                ge = max(ge, max((p - q).length for p, q in zip(ref, pts)))
    bm.free()
    return gv, ge


# ---------------------------------------------------------------- render switch
# Viewport and render level may differ: the links show the viewport copy and are switched
# to the render copy for the duration of a render (F12 and command line), then back.
# In a window Blender calls render_pre / render_post from the render thread: changing ob.data
# there crashed Blender (Dungeon, F12 with Cycles GPU, run 72). There F12 / Ctrl+F12 run
# MECSUB_OT_render, which switches in the main thread before the render starts and back when
# the render job has ended; the handlers only switch when they run in the main thread
# (command line renders).
_swapped = []
_RENDER_OP = [False]


def _main_thread():
    import threading
    return threading.current_thread() is threading.main_thread()


def _swap_to_render(scene):
    _swapped.clear()
    for ob in scene.objects:
        if ob.type != 'MESH' or ob.get("rb_off"):
            continue
        orig = core.original_of(ob.data)
        rc = core.copy_of(orig, "render")
        if rc is not None and ob.data != rc and ob.data in (orig, core.copy_of(orig, "view")):
            _swapped.append((ob, ob.data))
            ob.data = rc


def _swap_back():
    while _swapped:
        ob, data = _swapped.pop()
        try:
            ob.data = data
        except ReferenceError:
            pass


@persistent
def _render_pre(scene, *args):
    if _main_thread() and not _RENDER_OP[0]:
        _swap_to_render(scene)


@persistent
def _render_post(scene, *args):
    if _main_thread() and not _RENDER_OP[0]:
        _swap_back()


class MECSUB_OT_render(bpy.types.Operator):
    bl_idname = "mecsub.render"
    bl_label = "Render with the render level"
    bl_description = ("Render (F12 / Ctrl+F12): the links are switched to the copies of the render level "
                      "before the render starts and back to the viewport level when it has ended")
    animation: bpy.props.BoolProperty(default=False)
    use_viewport: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        _swap_to_render(context.scene)
        _RENDER_OP[0] = True
        try:
            r = bpy.ops.render.render('INVOKE_DEFAULT', animation=self.animation, use_viewport=self.use_viewport)
        except Exception as e:
            self.report({'ERROR'}, f"Renderbricker: {e}")
            r = {'CANCELLED'}
        if 'RUNNING_MODAL' not in r and not bpy.app.is_job_running('RENDER'):
            return self._done()
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER' and not bpy.app.is_job_running('RENDER'):
            context.window_manager.event_timer_remove(self._timer)
            self._done()
            return {'FINISHED'}
        return {'PASS_THROUGH'}             # Esc and everything else belong to the render

    def _done(self):
        _swap_back()
        _RENDER_OP[0] = False
        try:
            bpy.context.scene.mecsub.wt_rendered = True
        except (AttributeError, ReferenceError):
            pass
        return {'FINISHED'}


def _render_menu(self, context):
    layout = self.layout
    layout.operator(MECSUB_OT_render.bl_idname, text="Render Image (Renderbricker levels)", icon='RENDER_STILL')
    op = layout.operator(MECSUB_OT_render.bl_idname, text="Render Animation (Renderbricker levels)", icon='RENDER_ANIMATION')
    op.animation = True
    layout.separator()


_keymaps = []


# ---------------------------------------------------------------- properties
class MECSUB_Problem(bpy.types.PropertyGroup):
    obj: StringProperty()
    info: StringProperty()

def _processed_groups(context):
    idx = core.copy_index_begin() if core._COPY_INDEX[0] is None else core._COPY_INDEX[0]
    return [(me, obs) for me, obs in by_mesh(targets(context)).items() if idx.get(me.name)]


def _start_levels():
    """Run the level operator with its progress bar (from a timer: an update callback
    must not start a modal operator itself)."""
    wm = bpy.context.window_manager
    for win in wm.windows:
        area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
        if area:
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.mecsub.levels('INVOKE_DEFAULT')
            return None
    bpy.ops.mecsub.levels()
    return None


_LEVEL_GUARD = [False]      # the update itself resets a level
_LEVEL_OK = [False]         # a level above 2 confirmed in the dialog is being set


def _levels_update(self, context):
    """Viewport / Render changed: switch at once where the copies exist,
    compute missing ones with the progress bar (run 40). Raising a level above 2 asks first
    (user, 2026-09-28): until it is confirmed the old value stays, Cancel keeps it."""
    if self.running or _LEVEL_GUARD[0]:
        return
    for which in ("view", "render"):
        new, old = getattr(self, which + "_level"), getattr(self, "prev_" + which + "_level")
        if new > 2 and new > old and not _LEVEL_OK[0] and not bpy.app.background:
            _LEVEL_GUARD[0] = True
            try:
                setattr(self, which + "_level", old)
            finally:
                _LEVEL_GUARD[0] = False
            _ask_level(which, new)
            return
    self.prev_view_level, self.prev_render_level = self.view_level, self.render_level
    if not any(m.get("rb_original") for m in bpy.data.meshes if m.library is None):
        return                                   # nothing applied yet: the values count for Apply
    if not bpy.app.background:              # always with the progress bar (Dungeon: 2,769 meshes, run 72)
        bpy.app.timers.register(_start_levels, first_interval=0.01)
        return
    groups = _processed_groups(context)
    core.copy_index_end()
    if any(core.missing_levels(me, self.view_level, self.render_level) for me, _ in groups):
        bpy.ops.mecsub.levels()
    else:
        for me, obs in groups:
            core.set_levels(me, self.view_level, self.render_level, obs)


def _ask_level(which, value):
    """The question for a level above 2 (from a timer: an update callback must not open a dialog)."""
    def ask():
        wm = bpy.context.window_manager
        for win in wm.windows:
            area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
            if area:
                with bpy.context.temp_override(window=win, area=area):
                    bpy.ops.mecsub.level_confirm('INVOKE_DEFAULT', which=which, value=value)
                return None
        return None
    bpy.app.timers.register(ask, first_interval=0.01)


class MECSUB_OT_level_confirm(bpy.types.Operator):
    bl_idname = "mecsub.level_confirm"
    bl_label = "Subdivision level above 2"
    bl_description = "Confirm a subdivision level above 2"
    bl_options = {'INTERNAL'}
    which: StringProperty(default="render")
    value: IntProperty(default=3)

    def invoke(self, context, event):
        name = "Viewport" if self.which == "view" else "Render"
        return context.window_manager.invoke_confirm(
            self, event, title=f"{name} level {self.value}?",
            message="Each level has 3-4 times the faces: much more memory and time, little visible gain. "
                    "2 is enough for close-ups.",
            confirm_text=f"Use level {self.value}", icon='WARNING')

    def execute(self, context):
        _LEVEL_OK[0] = True
        try:
            setattr(context.scene.mecsub, self.which + "_level", self.value)
        finally:
            _LEVEL_OK[0] = False
        return {'FINISHED'}


_SWITCHING = [False]


def _cache_update(self, context):
    """The cache setting changed (run 68): with converted meshes in the scene the copies move
    into the cache or back into the scene - after a question; until it is confirmed the
    setting keeps its old value, so setting and scene always agree."""
    if _SWITCHING[0] or self.running:
        return
    target = self.use_cache
    if not core.processed_originals():
        return                                   # nothing converted yet: only the setting
    _SWITCHING[0] = True
    try:
        self.use_cache = not target
    finally:
        _SWITCHING[0] = False
    if bpy.app.background:
        return

    def start():
        wm = bpy.context.window_manager
        for win in wm.windows:
            area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
            if area:
                with bpy.context.temp_override(window=win, area=area):
                    bpy.ops.mecsub.cache_switch('INVOKE_DEFAULT', target=target)
                return None
        return None
    bpy.app.timers.register(start, first_interval=0.01)


def refresh_state(context=None):
    """ON / OFF / MIXED / NONE for the On/Off button (user, run 74): every processed object on a
    copy = ON, every one switched off = OFF. Computed after the operators and on load - not in
    draw(), which runs on every redraw (28,000 objects in Dungeon)."""
    on = off = False
    for ob in (context or bpy.context).scene.objects:
        if ob.type != 'MESH' or ob.data is None:
            continue
        if ob.get("rb_off"):
            off = True
        elif ob.data.get("rb_original"):
            on = True
        if on and off:
            break
    st = "MIXED" if on and off else "ON" if on else "OFF" if off else "NONE"
    for sc in ([context.scene] if context else bpy.data.scenes):
        if getattr(sc, "mecsub", None) and sc.mecsub.subdiv_state != st:
            sc.mecsub.subdiv_state = st
    return st


def setup_blend():
    """The Renderbricks setup scene (render settings, sky) shipped with the add-on."""
    import os
    return os.path.join(os.path.dirname(__file__), "setup", "renderbricks_setup.blend")


class MECSUB_OT_frame_camera(bpy.types.Operator):
    bl_idname = "mecsub.frame_camera"
    bl_label = "Frame camera"
    bl_description = ("Move the camera \"Renderbricks\" so that all visible parts fill the picture (its direction "
                      "stays); creates the camera when it is missing")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        object_mode(context)
        text = core.setup_scene(context.scene, "", context.evaluated_depsgraph_get(), frame_only=True)
        self.report({'INFO'}, "Renderbricker: " + text)
        return {'FINISHED'}


def log_path():
    import os
    return os.path.splitext(bpy.data.filepath)[0] + "_renderbricker.log" if bpy.data.filepath else ""


def write_log(context, label):
    """Append the result of an operator to <scene>_renderbricker.log (option Log file, user 2026-09-28):
    date, add-on and Blender version, scene, settings, the summary and the full problem list."""
    s = context.scene.mecsub
    path = log_path()
    if not s.use_log or not path or not s.summary:
        return
    import datetime
    scope = {"ALL": "all parts", "SELECTED": "selected parts",
             "COLLECTION": f"collection {s.collection.name if s.collection else '-'}"}[s.scope]
    lines = [f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {label}  "
             f"(Renderbricker {VERSION}, Blender {bpy.app.version_string})",
             f"scene: {bpy.data.filepath}",
             f"settings: {scope}, variant {s.variant}, viewport {s.view_level}, render {s.render_level}, "
             f"several cores {'on' if s.use_cores else 'off'}, cache file {'on' if s.use_cache else 'off'}"]
    lines += [f"  - {part}" for part in s.summary.split(", ")]
    if len(s.problems):
        lines.append(f"problems ({len(s.problems)}):")
        lines += [f"  - {p.obj}: {p.info}" for p in s.problems]
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n\n")
    except OSError as e:
        s.summary += f", log not written: {e}"


def save_after_cache(op, context):
    """After Apply / Levels wrote the cache file the scene is saved (user, run 74): the file
    on disk must link the copies that are now in the cache - an unsaved scene pointed to
    overrides the new cache no longer has."""
    part = getattr(op, "cache_part", None) or ""
    if not bpy.data.filepath or "copies in" not in part:
        return
    s = context.scene.mecsub
    if bpy.app.background:
        try:
            bpy.ops.wm.save_mainfile()
            s.summary += ", scene saved"
        except Exception as e:
            s.summary += f", scene not saved: {e}"
        return
    # in a window after the operator has ended: its undo step marks the file changed again
    s.summary += ", scene saved"
    def later():
        try:
            bpy.ops.wm.save_mainfile()
        except Exception as e:
            sc = bpy.context.scene
            if getattr(sc, "mecsub", None):
                sc.mecsub.summary = sc.mecsub.summary.replace(", scene saved", f", scene not saved: {e}")
        return None
    bpy.app.timers.register(later, first_interval=0.2)


def _scope_update(self, context):
    """Collection chosen without a collection yet: take the active one of the Outliner."""
    if self.scope == 'COLLECTION' and self.collection is None:
        c = context.collection
        if c is not None and c != context.scene.collection:
            self.collection = c


def scope_empty_text(context):
    s = context.scene.mecsub
    if s.scope == 'COLLECTION' and s.collection is None:
        return "Choose a collection first"
    return "No mesh objects in scope"


class MECSUB_Settings(bpy.types.PropertyGroup):
    scope: EnumProperty(name="Scope", items=[
        ('ALL', "All", "Every mesh object in the scene"),
        ('SELECTED', "Selected", "Selected mesh objects only"),
        ('COLLECTION', "Collection", "Mesh objects in the chosen collection and its child collections")],
        default='ALL', update=_scope_update)
    collection: PointerProperty(type=bpy.types.Collection, name="Collection",
                                description="Apply, Check, On/Off, Levels and Remove work on the parts in this "
                                            "collection and its child collections")
    variant: EnumProperty(name="Variant", items=[
        ('A', "A - Mecabricks normals", "Subdivision interpolates the imported custom normals (soft logo)"),
        ('B', "B - geometric normals", "Normals of the smoothed surface, creased edges sharp (crisp logo)")], default='A')
    view_level: IntProperty(name="Viewport", default=1, min=0, max=4, update=_levels_update,
                            description="Subdivision shown in the viewport (0: the original mesh - no viewport copy "
                                        "is stored, the file gets about a fifth smaller). Levels already baked "
                                        "switch at once, others are computed the first time. Above 2 rarely makes sense")
    render_level: IntProperty(name="Render", default=2, min=1, max=4, update=_levels_update,
                              description="Subdivision used for rendering (the checks use this level). 2 is enough even for "
                                          "close-ups; every further level multiplies the faces by three to four")
    prev_view_level: IntProperty(default=1)     # the confirmed levels (question above 2)
    prev_render_level: IntProperty(default=2)
    use_cores: bpy.props.BoolProperty(
        name="Use several cores", default=True,
        description="Apply on larger scenes (about 40 meshes and more) runs in background Blenders on "
                    "several cores and loads the result into this scene - the scene is saved first")
    use_cache: bpy.props.BoolProperty(
        name="Cache file next to the scene", default=True, update=_cache_update,
        description="The subdivided copies are kept in <scene>_rbcache.blend next to the scene and "
                    "linked into it (as library overrides that carry the scene's materials): the scene file "
                    "stays about as large as the import. Needs a saved scene")
    use_setup: bpy.props.BoolProperty(
        name="Renderbricks camera", default=True,
        description="On the first Apply: create the camera \"Renderbricks\" (the scene camera, clip end 1000) "
                    "framing all visible parts to fill the picture, and take over the render settings and the "
                    "sky of the Renderbricks setup scene. The camera icon frames the camera again")
    use_log: bpy.props.BoolProperty(
        name="Log file", default=False,
        description="Write the results of Apply, Check and Convert headless into <scene>_renderbricker.log "
                    "next to the scene (appended, with date, settings and the full problem list). "
                    "Needs a saved scene")
    summary: StringProperty(default="")
    problems: CollectionProperty(type=MECSUB_Problem)
    running: bpy.props.BoolProperty(default=False)
    subdiv_state: StringProperty(default="NONE")         # refresh_state(): ON / OFF / MIXED / NONE
    progress: bpy.props.FloatProperty(default=0.0, min=0.0, max=1.0, subtype='FACTOR')
    progress_text: StringProperty(default="")
    # guide for new users (user, 2026-09-28): step card instead of the full panel
    wt_active: bpy.props.BoolProperty(default=False)
    wt_step: IntProperty(default=0, min=0)
    wt_checked: bpy.props.BoolProperty(default=False)      # Check ran after the last Apply
    wt_bad: IntProperty(default=0)                         # parts with problems in that Check
    wt_compared: bpy.props.BoolProperty(default=False)     # switched OFF and back ON
    wt_rendered: bpy.props.BoolProperty(default=False)     # rendered through the add-on


# ---------------------------------------------------------------- operators
def fmt_time(sec):
    sec = int(round(sec))
    return f"{sec // 60} min {sec % 60:02d} s" if sec >= 90 else f"{sec} s"


def redraw(context):
    """Only the sidebar (the panel) and the status bar: a redraw of the whole 3D view on every
    progress update drew all 28,000 objects of Dungeon again (run 69)."""
    for area in (context.screen.areas if context.screen else []):
        if area.type == 'STATUSBAR':
            area.tag_redraw()
        elif area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'UI':
                    region.tag_redraw()


def work_budget(op, interval=0.0):
    """Seconds of work per timer tick (run 69): Blender spends a pause between two ticks on the
    whole scene (with new data-blocks it rebuilds the relations of all objects - Dungeon about
    1.1 s per tick, so 0.1 s pieces made 'cache off' take 227 s instead of 14 s). The pause is
    measured, and each tick works nine times as long: the progress display costs at most about
    10 %, small scenes still update several times a second."""
    now = time.time()
    last = getattr(op, "_tick_end", None)
    gap = max(0.0, now - last - interval) if last else 0.0       # minus the timer interval
    op._budget = min(15.0, max(0.1, 9.0 * gap, 0.7 * getattr(op, "_budget", 0.1)))
    return op._budget


def tick_done(op):
    op._tick_end = time.time()


def step_gen(gen, budget=0.1):
    """Advance a step generator of the core (yields (fraction, text[, waiting])) for about
    `budget` seconds, or until it only waits for a helper process. Returns (done, last step or
    result)."""
    t = time.time()
    last = None
    while True:
        try:
            last = next(gen)
        except StopIteration as e:
            return True, e.value
        if (len(last) > 2 and last[2]) or time.time() - t >= budget:
            return False, last


def link_text(path):
    """'linking the cache file (about N s)' from the size and the speed of the last link (run 70)."""
    import os
    try:
        est = os.path.getsize(path) / core.LINK_RATE[0]
    except OSError:
        return "linking the cache file"
    return f"linking the cache file (about {est:.0f} s)" if est >= 3 else "linking the cache file"


def show_step(context, label, st):
    s = context.scene.mecsub
    s.progress = max(0.0, min(1.0, st[0]))
    s.progress_text = f"{st[1]} ..."
    context.workspace.status_text_set(f"Renderbricker {label}: {st[1]} ... {100 * s.progress:.0f} %")
    redraw(context)


def phase(what, t0=None):
    """One line per phase in the console (run 66: the phases after the workers were invisible)."""
    print(f"RBPHASE {time.time():.1f} {what}" + (f" {time.time() - t0:.1f} s" if t0 else ""), flush=True)


def write_cache(context):
    """Copies into the cache file next to the scene (run 62). Returns a summary part."""
    import os
    s = context.scene.mecsub
    if not s.use_cache:
        n = core.uncache()                  # a scene converted with the cache before (1.9.0/1.9.1)
        return f", materials back on the meshes of {n} objects" if n else ""
    if not bpy.data.filepath:
        return ", copies kept in the scene (save the scene to use the cache file)"
    path = core.cache_path_for(bpy.data.filepath)
    t = time.time()
    n = core.write_cache(path)
    return f", {n} copies in {os.path.basename(path)} ({time.time() - t:.0f} s)" if n else ""


class _Stepped:
    """Work in small steps. From the panel (invoke) it runs modal on a timer so
    the progress bar can redraw and Esc cancels; from scripts (execute) it runs
    straight through. Subclasses: label, prepare(), item_name(), step(), finish()."""
    label = ""
    _timer = None

    def execute(self, context):
        self.cancelled = False
        if not self.prepare(context):
            return {'CANCELLED'}
        self.cache_part = None          # scripts: the cache is written in finish()
        for i in range(len(self.items)):
            try:
                self.step(context, i)
            except core.MemoryShortage as e:        # stop cleanly, processed meshes stay (run 49)
                self.cancelled = True
                self.finish(context)
                s = context.scene.mecsub
                s.summary = f"Stopped: {e}, " + s.summary
                self.report({'ERROR'}, f"Renderbricker: stopped: {e}")
                return {'CANCELLED'}
        self.finish(context)
        refresh_state(context)                 # before saving: it sets a scene property
        save_after_cache(self, context)
        write_log(context, self.label)
        return {'FINISHED'}

    def invoke(self, context, event):
        self.cancelled = False
        if not self.prepare(context):
            return {'CANCELLED'}
        self.i = 0
        # time estimate weighted by mesh size (a large panel takes far longer than a plate)
        w = [len(it[0].polygons) + 50 if isinstance(it, tuple) and hasattr(it[0], "polygons") else 1
             for it in self.items]
        self.cum = [0]
        for x in w:
            self.cum.append(self.cum[-1] + x)
        self.t_start = time.time()
        s = context.scene.mecsub
        s.running, s.progress, s.progress_text = True, 0.0, f"0 / {len(self.items)}"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.cancelled = True
            return self._end(context)
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}                  # block other input while working
        n = len(self.items)
        t = time.time()
        try:
            budget = work_budget(self)       # adaptive: the pause between ticks stays <= ~10 % (run 69)
            while self.i < n and time.time() - t < budget:
                self.step(context, self.i)
                self.i += 1
        except Exception as e:
            # an exception inside modal() ends the operator but left the timer running and
            # the panel locked, Esc no longer reached it (run 39) - end cleanly instead
            import traceback
            traceback.print_exc()
            if isinstance(e, core.MemoryShortage):
                self.error = str(e)
            else:
                self.error = f"{self.item_name(self.i)}: {type(e).__name__}: {e}"
            return self._end(context)
        s = context.scene.mecsub
        done, total = self.cum[self.i], self.cum[-1]
        s.progress = done / total if total else 1.0
        name = self.item_name(self.i - 1) if self.i else ""
        elapsed = time.time() - self.t_start
        left = (elapsed / done * (total - done) if done and elapsed > 10.0 and done >= 0.03 * total
                else None)                   # no wild guesses from the first meshes (run 69)
        eta = "" if left is None else f"   about {fmt_time(left)} left"
        tick_done(self)
        s.progress_text = f"{self.i} / {n}{eta}"
        context.workspace.status_text_set(f"Renderbricker {self.label}: {self.i} / {n}   {name}{eta}   (Esc: cancel)")
        redraw(context)
        if self.i >= n:
            return self._tail(context)
        return {'RUNNING_MODAL'}

    def _tail(self, context):
        """Phases after the steps (cache file ...): each is announced in the panel and the status
        bar on one timer tick and run on the next, so the text is on screen while Blender works
        (run 66: minutes of a busy cursor without any message)."""
        tail = getattr(self, "tail", None) or []
        if getattr(self, "tail_pending", None) is not None:
            text, fn = self.tail_pending
            try:
                if getattr(self, "tail_gen", None) is None:
                    self.tail_t0 = time.time()
                    r = fn(context)
                    if hasattr(r, "__next__"):          # a step generator: progress bar
                        self.tail_gen = r
                if getattr(self, "tail_gen", None) is not None:
                    done, st = step_gen(self.tail_gen, work_budget(self))
                    if not done:
                        show_step(context, self.label, st)
                        tick_done(self)
                        return {'RUNNING_MODAL'}
                    self.tail_gen = None
                    if hasattr(self, "tail_done"):
                        self.tail_done(context, st)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.tail_gen = None
                self.error = getattr(self, "error", None) or f"{text}: {type(e).__name__}: {e}"
                tail.clear()
            phase(text, getattr(self, "tail_t0", None))
            self.tail_pending = None
        if not tail:
            return self._end(context)
        text, fn = self.tail_pending = tail.pop(0)
        s = context.scene.mecsub
        s.progress_text = f"{text} ..."
        context.workspace.status_text_set(f"Renderbricker {self.label}: {text} ...")
        redraw(context)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        phase("operator end")
        s = context.scene.mecsub
        try:
            context.window_manager.event_timer_remove(self._timer)
        finally:
            s.running = False
            context.workspace.status_text_set(None)
        err = getattr(self, "error", None)
        try:
            self.finish(context)
        except Exception as e:              # the summary must never lock the panel either
            err = err or f"{type(e).__name__}: {e}"
        if err:
            what = "Stopped: " if "free memory" in err else "Stopped by an error at "
            s.summary = f"{what}{err}, " + s.summary
            self.report({'ERROR'}, "Renderbricker: " + what + err)
        refresh_state(context)                 # before saving: it sets a scene property
        if not err:
            save_after_cache(self, context)
        write_log(context, self.label)
        redraw(context)
        return {'FINISHED'}


class MECSUB_OT_apply(_Stepped, bpy.types.Operator):
    bl_idname = "mecsub.apply"
    bl_label = "Apply"
    bl_description = ("Set creases on each mesh once and write the subdivision into a copy of it that all its "
                      "links use (the original mesh stays in the file, unchanged). Parts already converted with "
                      "these settings are skipped - Shift+click converts all again. Esc cancels")
    bl_options = {'REGISTER', 'UNDO'}
    label = "Apply"
    force: bpy.props.BoolProperty(name="Convert all again", default=False, options={'SKIP_SAVE'})

    def collect(self, context):
        """(to do, up to date): meshes in scope, split by whether their copies already come from the
        current settings and rules. Sets the core's settings for the run."""
        s = context.scene.mecsub
        core.LEVELS = s.render_level                    # the checks run at the render level
        core.VIEW_LEVEL, core.RENDER_LEVEL = s.view_level, s.render_level
        core.SHADING = "mecabricks" if s.variant == 'A' else "geometric"
        items = list(by_mesh(targets(context)).items())
        if self.force:
            return items, []
        core.copy_index_begin()
        try:
            todo, fresh = [], []
            for me, obs in items:
                (fresh if core.up_to_date(me, s.view_level, s.render_level) else todo).append((me, obs))
        finally:
            core.copy_index_end()
        return todo, fresh

    def prepare(self, context):
        object_mode(context)
        s = context.scene.mecsub
        if not by_mesh(targets(context)):
            self.report({'WARNING'}, scope_empty_text(context))
            return False
        self.setup_note = ""
        if s.use_setup and bpy.data.objects.get(core.CAMERA_NAME) is None:
            try:
                self.setup_note = ", " + core.setup_scene(context.scene, setup_blend(),
                                                         context.evaluated_depsgraph_get())
            except Exception as e:           # the conversion goes on without the camera
                self.setup_note = f", camera not set up: {type(e).__name__}: {e}"
        self.items, fresh = self.collect(context)
        for me, obs in fresh:                  # up to date: only new or switched-off links join the copy
            for ob in obs:
                ob.pop("rb_off", None)
            core.point_links(obs, me, "view")
        self.skipped = len(fresh)
        if not self.items:
            s.summary = (f"All {self.skipped} parts are already converted with these settings, "
                         f"Shift+click on Apply converts all again" + self.setup_note)
            refresh_state(context)
            self.report({'INFO'}, "Renderbricker: " + s.summary)
            return False
        self.variant, self.levels = s.variant, (s.view_level, s.render_level)
        self.t0 = time.time()
        self.fans = self.unresolved = self.folds = self.done = 0
        s.problems.clear()
        s.wt_checked = False
        self.cache_part, self.tail_pending = None, None
        self.tail = [("writing the cache file" if s.use_cache and bpy.data.filepath else "finishing the copies",
                      self._cache_phase)]
        return True

    def _cache_phase(self, context):
        import os
        s = context.scene.mecsub
        self.cache_part = ""
        if not self.done:
            return None
        if s.use_cache and bpy.data.filepath:            # with a progress bar (run 69)
            self.cache_path = core.cache_path_for(bpy.data.filepath)
            return core.write_cache_steps(self.cache_path)
        try:
            self.cache_part = write_cache(context)
        except Exception as e:              # the copies stay in the scene then
            import traceback
            traceback.print_exc()
            self.cache_part = f", cache file not written: {type(e).__name__}: {e}"
        return None

    def tail_done(self, context, n):
        import os
        if getattr(self, "cache_path", None):
            self.cache_part = f", {n} copies in {os.path.basename(self.cache_path)}"

    def item_name(self, i):
        return self.items[i][0].name

    # ---- several cores (run 60): background Blenders bake, this one loads the copies
    def invoke(self, context, event):
        s = context.scene.mecsub
        self.workers = None
        if event.shift:
            self.force = True
        if s.use_cores and not bpy.app.background:
            object_mode(context)
            jobs = core.resolve_jobs("auto", len(self.collect(context)[0]))
            if jobs > 1:
                if not bpy.data.filepath:
                    self.report({'WARNING'}, "Save the scene first: Apply on several cores opens it from disk "
                                             "(or switch off 'Use several cores')")
                    bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
                    return {'CANCELLED'}
                return self._start_workers(context, jobs)
        return _Stepped.invoke(self, context, event)

    def _start_workers(self, context, jobs):
        s = context.scene.mecsub
        self.cancelled = False
        if not self.prepare(context):
            return {'CANCELLED'}
        for _me, obs in self.items:
            for ob in obs:
                ob.pop("rb_off", None)
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        opts = ["--view-level", str(s.view_level), "--render-level", str(s.render_level),
                "--shading", "mecabricks" if s.variant == 'A' else "geometric"]
        self.workers = core.Workers(dict(self.items), jobs, opts, [me.name for me, _ in self.items])
        self.jobs, self.merging, self.t_start = jobs, False, time.time()
        s.running, s.progress, s.progress_text = True, 0.0, f"0 / {len(self.items)}   starting {jobs} Blenders"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not getattr(self, "workers", None):
            return _Stepped.modal(self, context, event)
        w, s, n = self.workers, context.scene.mecsub, len(self.items)
        if event.type == 'ESC' and not self.merging:
            w.kill()
            self.cancelled, self.done = True, 0
            return self._end(context)
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if self.merging:                     # shown for one redraw, then the (blocking) merge
            return self._merge(context)
        if getattr(self, "tail_pending", None) is not None or getattr(self, "in_tail", False):
            return self._tail(context)
        w.poll()
        s.progress = w.done_w / w.total_w
        elapsed = time.time() - self.t_start
        left = (elapsed / w.done_w * (w.total_w - w.done_w)
                if w.done_w and elapsed > 10.0 and w.done_w >= 0.03 * w.total_w else None)
        eta = "" if left is None else f"   about {fmt_time(left)} left"
        short = f", {w.retired} stopped for memory" if w.retired else ""
        s.progress_text = f"{len(w.done)} / {n}   {self.jobs} cores{short}{eta}"
        context.workspace.status_text_set(
            f"Renderbricker Apply on {self.jobs} cores: {len(w.done)} / {n}{eta}   (Esc: cancel)")
        if not w.running():
            phase(f"workers ({self.jobs} Blenders)", self.t_start)
            self.merging = True
            what = ("writing the cache file and linking it" if s.use_cache and bpy.data.filepath
                    else "loading the copies into the scene")
            s.progress_text = f"{len(w.done)} / {n}   {what} ..."
            context.workspace.status_text_set(f"Renderbricker Apply: {what} ...")
        redraw(context)
        return {'RUNNING_MODAL'}

    def _merge(self, context):
        import os
        s = context.scene.mecsub
        try:
            def on_mesh(me, obs, rep):          # (a new function per tick; the generator keeps the first)
                self.tpoints = getattr(self, "tpoints", 0) + rep.get("t_verts", 0)
                if rep.get("flipped"):
                    self.folds += rep["flipped"]
                    p = s.problems.add(); p.obj = obs[0].name; p.info = f"{rep['flipped']} folded faces left"
                self.done += 1
            t0 = time.time()
            if s.use_cache and bpy.data.filepath:    # straight into the cache, never loaded here (run 66)
                path = core.cache_path_for(bpy.data.filepath)
                if getattr(self, "merge_gen", None) is None:
                    self.merge_gen, self.merge_t0 = self.workers.merge_to_cache_steps(path, on_mesh), t0
                done, st = step_gen(self.merge_gen, work_budget(self, 0.25))
                if not done:
                    show_step(context, "Apply", st)
                    tick_done(self)
                    return {'RUNNING_MODAL'}
                _reps, rest, n = st
                self.merge_gen = None
                self.cache_part = f", {n} copies in {os.path.basename(path)}"
                if not rest:
                    self.tail = []
                phase("cache file written and linked", self.merge_t0)
            else:
                _reps, rest = self.workers.merge(on_mesh)
                phase("loading the copies into the scene", t0)
            items = dict(self.items)
            for me in rest:                  # a worker failed: these meshes are done here
                on_mesh(me, items[me], core.process(me, items[me]))
            if self.workers.skipped:
                sk = self.workers.skipped
                self.error = f"{len(sk)} meshes skipped for memory ({', '.join(sk[:3])})"
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.workers.kill()
            self.merge_gen = None
            self.error = f"{type(e).__name__}: {e}"
            return self._end(context)
        self.merging, self.in_tail = False, True
        return self._tail(context)

    def step(self, context, i):
        s = context.scene.mecsub
        me, obs = self.items[i]
        core.check_memory(me, max(self.levels))   # stop cleanly instead of crashing (run 49)
        for ob in obs:
            ob.pop("rb_off", None)
        rep = core.process(me, obs)
        self.fans += rep.get("t_fans_creased", 0)
        self.unresolved += rep.get("t_fans_unresolved", 0)
        self.tpoints = getattr(self, "tpoints", 0) + rep.get("t_verts", 0)
        if rep.get("flipped"):
            self.folds += rep["flipped"]
            p = s.problems.add(); p.obj = obs[0].name; p.info = f"{rep['flipped']} folded faces left"
        self.done += 1

    def finish(self, context):
        s = context.scene.mecsub
        n = len(self.items)
        objs = sum(len(o) for _, o in self.items[:self.done])
        cores = f", {self.jobs} cores" if getattr(self, "workers", None) else ""
        skipped = getattr(self, "skipped", 0)
        s.summary = ((f"Cancelled after {self.done} of {n} meshes, " if self.cancelled else f"{n} mesh{'' if n == 1 else 'es'}, ")
                     + (f"{skipped} already up to date (skipped), " if skipped else "")
                     + f"{objs} objects, {time.time() - self.t0:.0f} s, variant {self.variant}, "
                     + f"viewport {self.levels[0]} / render {self.levels[1]}{cores}"
                     + (f", T points pinned {getattr(self, 'tpoints', 0)}" if core.METHOD == "weld"
                        else f", T fans creased {self.fans}")
                     + (f", unresolved {self.unresolved}" if self.unresolved else "")
                     + (f", folds left {self.folds}" if self.folds else "")
                     + getattr(self, "setup_note", ""))
        if self.done:
            if getattr(self, "cache_part", None) is None:     # scripts (execute): no tail phases
                try:
                    self.cache_part = write_cache(context)
                except Exception as e:              # the copies stay in the scene then
                    import traceback
                    traceback.print_exc()
                    self.cache_part = f", cache file not written: {type(e).__name__}: {e}"
            s.summary += self.cache_part
        self.report({'WARNING'} if self.cancelled else {'INFO'}, "Renderbricker: " + s.summary)


class MECSUB_OT_check(_Stepped, bpy.types.Operator):
    bl_idname = "mecsub.check"
    bl_label = "Check"
    bl_description = "Look for folded faces and seam gaps in the subdivided render copies. Esc cancels"
    label = "Check"

    def prepare(self, context):
        object_mode(context)
        s = context.scene.mecsub
        self.items = list(by_mesh(targets(context)).items())
        s.problems.clear()
        self.checked = self.bad = 0
        return True

    def item_name(self, i):
        return self.items[i][0].name

    def step(self, context, i):
        s = context.scene.mecsub
        me, obs = self.items[i]
        cp = core.copy_of(me, "render") or core.copy_of(me, "view")
        if cp is None:
            return
        self.checked += 1
        lv = int(cp.get("rb_level", 2))
        f = len(core.copy_folds(me, cp))
        if cp.get("rb_method") == "weld":          # rules 3.0: seams are welded, gaps only at T points
            gv = ge = core.weld_gap(core.original_of(me), cp)
        else:
            gv, ge = seam_gaps(me, cp, lv)
        if f or gv > 1e-3 or ge > 1e-3:
            self.bad += 1
            p = s.problems.add(); p.obj = obs[0].name
            p.info = f"folds {f}, seam gap {max(gv, ge):.3f}"

    def finish(self, context):
        s = context.scene.mecsub
        s.summary = (("Check cancelled: " if self.cancelled else "Check: ")
                     + f"{self.checked} meshes, {self.bad} with problems")
        s.wt_checked, s.wt_bad = not self.cancelled and self.checked > 0, self.bad
        self.report({'INFO'} if not self.bad else {'WARNING'}, s.summary)


class MECSUB_OT_levels(_Stepped, bpy.types.Operator):
    bl_idname = "mecsub.levels"
    bl_label = "Set levels"
    bl_description = ("Point the links to the copies of the chosen viewport / render level, computing copies "
                      "that do not exist yet (no rules run). Esc cancels")
    bl_options = {'REGISTER', 'UNDO'}
    label = "Levels"

    def prepare(self, context):
        object_mode(context)
        s = context.scene.mecsub
        self.items = _processed_groups(context)         # builds the copy index (run 72)
        self.view, self.render = s.view_level, s.render_level
        self.baked = 0
        self.t0 = time.time()
        self.cache_part, self.tail_pending = None, None
        need = any(core.missing_levels(core.original_of(me), self.view, self.render) for me, _ in self.items)
        self.tail = [("writing the cache file", self._cache_phase)] if need else []   # a pure switch writes nothing
        if not self.items:
            core.copy_index_end()
        return bool(self.items)

    def _cache_phase(self, context):
        try:
            self.cache_part = write_cache(context) if self.baked else ""
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.cache_part = f", cache file not written: {type(e).__name__}: {e}"

    def item_name(self, i):
        return self.items[i][0].name

    def step(self, context, i):
        me, obs = self.items[i]
        if core.missing_levels(core.original_of(me), self.view, self.render):
            core.check_memory(me, max(self.view, self.render))
        self.baked += core.set_levels(me, self.view, self.render, obs)
        if i == len(self.items) - 1:
            core.copy_index_end()                        # the cache write builds its own

    def finish(self, context):
        core.copy_index_end()
        s = context.scene.mecsub
        s.summary = ((f"Levels cancelled after {self.i if hasattr(self, 'i') else 0} meshes, " if self.cancelled else "")
                     + f"viewport {self.view} / render {self.render}, {len(self.items)} meshes, "
                     + f"{self.baked} copies computed, {time.time() - self.t0:.0f} s")
        if self.baked and getattr(self, "cache_part", None) is None:     # scripts: no tail phases
            try:
                self.cache_part = write_cache(context)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.cache_part = f", cache file not written: {type(e).__name__}: {e}"
        s.summary += getattr(self, "cache_part", None) or ""


class MECSUB_OT_toggle(bpy.types.Operator):
    bl_idname = "mecsub.toggle"
    bl_label = "Subdivision on/off"
    bl_description = "Switch the links between the subdivided copy and the original mesh (viewport and render)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        object_mode(context)
        groups = [(me, obs) for me, obs in by_mesh(targets(context)).items() if core.all_copies(me)]
        if not groups:
            self.report({'WARNING'}, "No subdivided meshes in scope")
            return {'CANCELLED'}
        on = any(o.get("rb_off") for _, obs in groups for o in obs)      # something is off: switch all on
        for me, obs in groups:
            for o in obs:
                if on:
                    o.pop("rb_off", None)
                    core.point_links([o], me, "view")
                    context.scene.mecsub.wt_compared = True
                else:
                    o["rb_off"] = True
                    o.data = me
        st = refresh_state(context)
        self.report({'INFO'}, f"Renderbricker: subdivision {'on' if on else 'off'}"
                              + (" (other objects outside the scope differ)" if st == "MIXED" else ""))
        redraw(context)
        return {'FINISHED'}


class MECSUB_OT_remove(bpy.types.Operator):
    bl_idname = "mecsub.remove"
    bl_label = "Remove"
    bl_description = "Links back to the original meshes; copies and crease attributes removed (plain import)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        object_mode(context)
        obs = targets(context)
        groups = by_mesh(obs)
        for me, gobs in groups.items():
            for o in gobs:
                core.unlink_instance(o)
                o.pop("rb_off", None)
                o.data = me
        for me in groups:
            copies = core.all_copies(me)
            if any(o.data in copies for o in bpy.data.objects if o.type == 'MESH'):
                continue            # still used by objects outside the scope
            core.drop_cache_links(me)      # object materials back to the mesh, cache hold released
            for c in copies:
                bpy.data.meshes.remove(c)
            core.remove_master(me)
            for a in ("crease_edge", "crease_vert"):
                if me.attributes.get(a):
                    me.attributes.remove(me.attributes[a])
            for k in ("rb_view", "rb_render"):
                me.pop(k, None)
            me.use_fake_user = False
        core.cleanup_libraries()
        context.scene.mecsub.summary = f"Removed from {len(obs)} objects"
        context.scene.mecsub.problems.clear()
        refresh_state(context)
        return {'FINISHED'}


class MECSUB_OT_move_cache(bpy.types.Operator):
    bl_idname = "mecsub.move_cache"
    bl_label = "Move cache to this scene"
    bl_description = ("Move the cache file next to this scene and rename it <scene>_rbcache.blend, update the "
                      "link and save the scene (after Save As under another name or in another folder). The "
                      "scene file the cache belonged to before then shows its original meshes")

    @classmethod
    def poll(cls, context):
        st = core.cache_state()
        return bool(bpy.data.filepath) and st is not None and st[1] != st[2]

    def invoke(self, context, event):
        import os
        st = core.cache_state()
        if os.path.exists(st[2]):
            return context.window_manager.invoke_confirm(
                self, event, title="Move cache",
                message=f"{os.path.basename(st[2])} exists already and will be replaced. Continue?")
        return self.execute(context)

    def execute(self, context):
        s = context.scene.mecsub
        if bpy.app.background or context.window is None:     # scripts: no timer, straight through
            self.ticks = 1
            self._timer = None
            return self.modal(context, type("E", (), {"type": 'TIMER'})())
        st = core.cache_state()
        s.running, s.progress = True, 0.5
        s.progress_text = f"moving the cache, {link_text(st[1] if st[3] else st[2])} ..."
        context.workspace.status_text_set(f"Renderbricker: {s.progress_text}")
        redraw(context)
        self.ticks = 0
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        import os
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        self.ticks += 1
        if self.ticks < 2:                     # the text is on screen first
            return {'RUNNING_MODAL'}
        s = context.scene.mecsub
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
        try:
            old, new = core.move_cache()
            bpy.ops.wm.save_mainfile()
            s.summary = f"Cache moved: {os.path.basename(old)} -> {os.path.basename(new)}, scene saved"
            err = False
        except Exception as e:
            s.summary, err = f"Moving the cache failed: {e}", True
        s.running = False
        context.workspace.status_text_set(None)
        self.report({'ERROR'} if err else {'INFO'}, "Renderbricker: " + s.summary)
        redraw(context)
        return {'CANCELLED'} if err else {'FINISHED'}


class MECSUB_OT_cache_switch(bpy.types.Operator):
    bl_idname = "mecsub.cache_switch"
    bl_label = "Switch the cache"
    bl_description = ("Cache on: write the copies into <scene>_rbcache.blend and link them. Cache off: take the "
                      "copies from the cache into the scene file")
    target: bpy.props.BoolProperty()
    _timer = None

    def invoke(self, context, event):
        import os
        n = len([m for m in bpy.data.meshes if m.get("rb_original") and m.library is None])
        if self.target:
            if not bpy.data.filepath:
                self.report({'WARNING'}, "Save the scene first: the cache file lies next to it")
                return {'CANCELLED'}
            msg = (f"Write the {n} subdivided copies into {os.path.basename(core.cache_path_for(bpy.data.filepath))} "
                   f"and link them? The scene file gets about as small as the import")
        else:
            st = core.cache_state()
            if st is None:                     # no cache linked: only the setting
                return self.execute(context)
            size = os.path.getsize(st[1]) / 1e9 if st[3] else 0
            msg = (f"Take the subdivided copies from {os.path.basename(st[1])} into the scene file? "
                   f"The scene file grows by about {size:.1f} GB (compressed); the cache file stays on disk")
        return context.window_manager.invoke_confirm(self, event, title="Cache file", message=msg)

    def execute(self, context):
        s = context.scene.mecsub
        self.phase = 0
        s.running, s.progress, s.progress_text = True, 0.0, ("writing the cache file" if self.target
                                                             else "taking the copies into the scene")
        context.workspace.status_text_set(f"Renderbricker: {s.progress_text} ...")
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if self.phase == 0:                    # the text is on screen now
            self.phase = 1
            return {'RUNNING_MODAL'}
        s = context.scene.mecsub
        if self.phase == 1:                    # stepped, with a progress bar (run 69)
            if not hasattr(self, "gen"):
                self.t0 = time.time()
                try:
                    if self.target:
                        _SWITCHING[0] = True
                        try:
                            s.use_cache = True          # write_cache follows the setting
                        finally:
                            _SWITCHING[0] = False
                        self.path = core.cache_path_for(bpy.data.filepath)
                        self.gen = core.write_cache_steps(self.path)
                    else:
                        self.gen = core.embed_cache_steps()
                except Exception as e:
                    self.gen, self.fail = None, e
            if getattr(self, "gen", None) is not None:
                try:
                    done, st = step_gen(self.gen, work_budget(self, 0.1))
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    done, st, self.fail = True, None, e
                if not done:
                    show_step(context, "cache", st)
                    tick_done(self)
                    return {'RUNNING_MODAL'}
                self.result = st
            self.phase = 2
        t0 = self.t0
        err = None
        def setting(value):
            _SWITCHING[0] = True
            try:
                s.use_cache = value
            finally:
                _SWITCHING[0] = False
        import os
        if getattr(self, "fail", None) is not None:
            err = f"{type(self.fail).__name__}: {self.fail}"
            text = f"Cache switch failed: {err}"
        elif self.target:
            text = f"Cache on, {self.result} copies in {os.path.basename(self.path)} ({time.time() - t0:.0f} s)"
        else:
            text = f"Cache off: {self.result} copies taken into the scene - save the scene to keep them"
        phase("cache on" if self.target else "cache off", t0)
        context.window_manager.event_timer_remove(self._timer)
        setting(self.target if err is None else not self.target)
        s.running = False
        s.summary = text if self.target else text + f" ({time.time() - t0:.0f} s)"
        context.workspace.status_text_set(None)
        self.report({'ERROR'} if err else {'INFO'}, "Renderbricker: " + s.summary)
        redraw(context)
        return {'FINISHED'}


class MECSUB_OT_copy_cache(bpy.types.Operator):
    bl_idname = "mecsub.copy_cache"
    bl_label = "Copy cache to this scene"
    bl_description = ("Copy the cache file next to this scene as <scene>_rbcache.blend, link the copy and save "
                      "the scene - both scene files keep a cache of their own (needs the disk space of a "
                      "second cache). Esc cancels")
    _timer = None

    @classmethod
    def poll(cls, context):
        st = core.cache_state()
        return bool(bpy.data.filepath) and st is not None and st[1] != st[2] and st[3]

    def invoke(self, context, event):
        import os
        st = core.cache_state()
        size = os.path.getsize(st[1]) / 1e9
        extra = (f" {os.path.basename(st[2])} exists already and will be replaced." if os.path.exists(st[2]) else "")
        return context.window_manager.invoke_confirm(
            self, event, title="Copy cache",
            message=f"Copy {os.path.basename(st[1])} ({size:.1f} GB) next to this scene?{extra}")

    def execute(self, context):
        import threading
        st = core.cache_state()
        self.lib, self.src, self.dst = st[0], st[1], st[2]
        self.tmp = self.dst + ".copying"
        self.total = max(1, __import__("os").path.getsize(self.src))
        self.done_bytes, self.failed, self.stop = 0, None, False

        def copy():                              # plain file copy in a thread, no Blender data
            try:
                with open(self.src, "rb") as fi, open(self.tmp, "wb") as fo:
                    while not self.stop:
                        b = fi.read(16 << 20)
                        if not b:
                            break
                        fo.write(b)
                        self.done_bytes += len(b)
            except Exception as e:
                self.failed = e

        self.thread = threading.Thread(target=copy, daemon=True)
        self.thread.start()
        s = context.scene.mecsub
        s.running, s.progress, s.progress_text = True, 0.0, "copying the cache file"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        import os
        s = context.scene.mecsub
        if event.type == 'ESC':
            self.stop = True
            self.thread.join()
            if os.path.exists(self.tmp):
                os.remove(self.tmp)
            return self._end(context, "Copy of the cache cancelled")
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if not getattr(self, "linking", False):      # the link text stays for its tick
            s.progress = self.done_bytes / self.total
            s.progress_text = f"copying the cache file {self.done_bytes / 1e9:.1f} / {self.total / 1e9:.1f} GB"
            context.workspace.status_text_set(f"Renderbricker: {s.progress_text}   (Esc: cancel)")
            redraw(context)
        if self.thread.is_alive():
            return {'RUNNING_MODAL'}
        if self.failed is not None:
            if os.path.exists(self.tmp):
                os.remove(self.tmp)
            return self._end(context, f"Copy of the cache failed: {self.failed}", error=True)
        if not getattr(self, "linking", False):      # one tick with the text on screen first
            self.linking = True
            s.progress = 0.99
            s.progress_text = link_text(self.tmp) + " ..."
            context.workspace.status_text_set(f"Renderbricker: {s.progress_text}")
            redraw(context)
            return {'RUNNING_MODAL'}
        os.replace(self.tmp, self.dst)
        core.relink_cache(self.lib, self.dst)
        bpy.ops.wm.save_mainfile()
        return self._end(context, f"Cache copied: {os.path.basename(self.src)} -> {os.path.basename(self.dst)}, "
                                  f"scene saved (the other scene keeps {os.path.basename(self.src)})")

    def _end(self, context, text, error=False):
        s = context.scene.mecsub
        context.window_manager.event_timer_remove(self._timer)
        s.running = False
        context.workspace.status_text_set(None)
        s.summary = text
        self.report({'ERROR'} if error else {'INFO'}, "Renderbricker: " + text)
        redraw(context)
        return {'CANCELLED'} if error else {'FINISHED'}


class MECSUB_OT_select(bpy.types.Operator):
    bl_idname = "mecsub.select"
    bl_label = "Select"
    bl_description = "Select and frame this object"
    obj: StringProperty()

    def execute(self, context):
        ob = context.scene.objects.get(self.obj)
        if not ob:
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True); context.view_layer.objects.active = ob
        try:
            bpy.ops.view3d.view_selected()
        except RuntimeError:
            pass
        return {'FINISHED'}


class MECSUB_OT_headless(bpy.types.Operator):
    bl_idname = "mecsub.headless"
    bl_label = "Convert headless"
    bl_description = ("Save the scene, write a start script next to it (.bat on Windows, .command on macOS, .sh on "
                      "Linux) and run it in a terminal: Blender converts the whole scene in the background on several "
                      "cores and saves the result as <scene>_subdiv_<add-on version>.blend. The open scene is not changed")

    def invoke(self, context, event):
        if not bpy.data.filepath:
            self.report({'WARNING'}, "Save the scene first, then press Convert headless again")
            return bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
        return context.window_manager.invoke_confirm(
            self, event, title="Convert headless",
            message="The scene is saved now and converted in a console window. Continue?")

    def execute(self, context):
        import os
        object_mode(context)
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        s = context.scene.mecsub
        blend = bpy.data.filepath
        folder, stem = os.path.dirname(blend), os.path.splitext(os.path.basename(blend))[0]
        tag = VERSION.replace(".", "-")
        name, k = f"{stem}_subdiv_{tag}", 1
        while os.path.exists(os.path.join(folder, name + ".blend")):   # never overwrite an earlier result
            k += 1
            name = f"{stem}_subdiv_{tag}_{k}"
        out = os.path.join(folder, name + ".blend")
        args = ["-b", "--factory-startup", blend, "--python", os.path.join(os.path.dirname(__file__), "core.py"),
                "--", out, "--view-level", str(s.view_level), "--render-level", str(s.render_level),
                "--shading", "mecabricks" if s.variant == 'A' else "geometric", "--jobs", "auto"]
        if s.use_cache:
            args += ["--cache", core.cache_path_for(out)]
        if s.use_log:
            args += ["--log", log_path()]
        if s.use_setup and bpy.data.objects.get(core.CAMERA_NAME) is None:
            args += ["--setup", setup_blend()]
        script = write_headless_script(os.path.join(folder, name), stem, blend, out, args)
        how = start_script(script)
        s.summary = (f"Headless conversion started in a terminal: {os.path.basename(script)}, result: {os.path.basename(out)}"
                     if how else f"Start script written, run it in a terminal: {script}")
        self.report({'INFO'}, "Renderbricker: " + s.summary)
        return {'FINISHED'}


# lines of the conversion worth showing in the terminal (the rest is Blender's own output)
HEADLESS_SHOW = ("PROGRESS", "SKIP", "SAVED", "Error", "Traceback", "MESHES", "JOBS", "MERGE", "CACHE", "CAMERA",
                 "RETIRE", "CLEAN")


def write_headless_script(base, stem, blend, out, args):
    """Start script for the headless conversion: <base>.bat (Windows), .command (macOS), .sh (Linux)."""
    import os, sys, shlex
    blender = bpy.app.binary_path
    head = f"Renderbricker {VERSION}: converting"
    if sys.platform.startswith("win"):
        q = lambda x: '"' + x.replace("%", "%%") + '"'
        lines = ["@echo off", "chcp 65001 >nul", f"title Renderbricker {VERSION} headless: {stem}",
                 f"echo {head} {q(blend)}", f"echo Result: {q(out)}", "echo.",
                 " ".join([q(blender)] + [q(a) if (" " in a or os.sep in a) else a for a in args])
                 + " 2>&1 | findstr /B " + " ".join(f'/C:"{w}"' for w in HEADLESS_SHOW),
                 "echo.", f"if exist {q(out)} (echo Done: {q(out)}) else (echo FAILED - no result written)", "pause"]
        path = base + ".bat"
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")
        return path
    path = base + (".command" if sys.platform == "darwin" else ".sh")
    lines = ["#!/bin/sh", f"# Renderbricker {VERSION} headless conversion of {stem}",
             f"echo {shlex.quote(head + ' ' + blend)}", f"echo {shlex.quote('Result: ' + out)}", "echo",
             " ".join(shlex.quote(a) for a in [blender] + args)
             + " 2>&1 | grep -E " + shlex.quote("^(" + "|".join(HEADLESS_SHOW) + ")"),
             "echo", f"if [ -f {shlex.quote(out)} ]; then echo {shlex.quote('Done: ' + out)}; "
             "else echo 'FAILED - no result written'; fi",
             "printf 'Press Enter to close. '", "read _"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)
    return path


def start_script(path):
    """Run a start script in a terminal window. Windows: its own console; macOS: Terminal; Linux: the
    first terminal found. Returns how it was started, or None when no terminal was found (the user
    runs it by hand)."""
    import os, sys, shutil, subprocess
    if sys.platform.startswith("win"):
        os.startfile(path)
        return "console"
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Terminal", path])
        return "Terminal"
    for term, pre in (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
                      ("xfce4-terminal", ["-x"]), ("kitty", []), ("alacritty", ["-e"]), ("xterm", ["-e"])):
        exe = shutil.which(term)
        if exe:
            subprocess.Popen([exe] + pre + [path], start_new_session=True)
            return term
    return None


# ---------------------------------------------------------------- panel
VERSION = ".".join(str(x) for x in bl_info["version"])


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
    if s.scope == 'COLLECTION':
        if s.collection is None:
            return False, "Choose a collection"
        ok = any(o.type == 'MESH' for o in s.collection.all_objects)
        return ok, f"Parts in {s.collection.name}" if ok else "The collection has no parts"
    ok = any(o.type == 'MESH' for o in context.scene.objects)
    return ok, "All parts of the scene" if ok else "The scene has no parts"


def _g_save(L, context, s):
    import os
    if bpy.data.filepath:
        L.operator("wm.save_mainfile", text="Save", icon='FILE_TICK')
    else:
        L.operator("wm.save_as_mainfile", text="Save As...", icon='FILE_TICK', depress=True)
    ok = bool(bpy.data.filepath)
    status(L, ok, f"Saved: {os.path.basename(bpy.data.filepath)}" if ok else "Not saved yet")
    return ok


def _g_parts(L, context, s):
    col = L.column(align=True)
    col.prop(s, "scope", expand=True)
    if s.scope == 'COLLECTION':
        col.prop(s, "collection", text="", icon='OUTLINER_COLLECTION')
    ok, text = scope_state(context)
    status(L, ok, text)
    return ok


def _g_settings(L, context, s):
    L.prop(s, "variant", text="")
    draw_levels(L, s, context)
    L.prop(s, "use_cores")
    L.prop(s, "use_cache")
    L.prop(s, "use_log")
    row = L.row(align=True)
    row.prop(s, "use_setup")
    row.operator("mecsub.frame_camera", text="", icon='VIEW_CAMERA')
    return True


def _g_apply(L, context, s):
    ok = s.subdiv_state in ("ON", "MIXED")
    row = L.row()
    row.scale_y = 1.3
    row.operator("mecsub.apply", icon='MOD_SUBSURF', depress=not ok)
    status(L, ok, "Parts converted" if ok else "Press Apply")
    draw_summary(L, s)
    return ok


def _g_check(L, context, s):
    ok = s.wt_checked
    row = L.row()
    row.scale_y = 1.3
    row.operator("mecsub.check", icon='VIEWZOOM', depress=not ok)
    if ok:
        status(L, s.wt_bad == 0, "No problems found" if s.wt_bad == 0
               else f"{s.wt_bad} parts with problems - see the list")
    else:
        status(L, False, "Press Check")
    draw_summary(L, s)
    return ok


def _g_compare(L, context, s):
    state = s.subdiv_state
    label, icon = {"ON": ("Subdivision: ON", 'CHECKBOX_HLT'), "OFF": ("Subdivision: OFF", 'CHECKBOX_DEHLT'),
                   "MIXED": ("Subdivision: partly on", 'CHECKBOX_HLT')}.get(state, ("Subdivision: -", 'CHECKBOX_DEHLT'))
    ok = s.wt_compared and state == "ON"
    row = L.row()
    row.scale_y = 1.3
    row.operator("mecsub.toggle", icon=icon, text=label, depress=(state == "ON"))
    status(L, ok, "Compared - subdivision is on" if ok else
           ("Switch it back ON" if state == "OFF" else "Switch OFF, look, switch back ON"))
    return ok


def _g_render(L, context, s):
    ok = s.wt_rendered
    row = L.row()
    row.scale_y = 1.3
    op = row.operator("mecsub.render", text="Render Image (F12)", icon='RENDER_STILL', depress=not ok)
    op.use_viewport = True
    status(L, ok, "Rendered with the render level" if ok else "Press F12 or the button")
    return ok


def _g_next(L, context, s):
    L.operator("mecsub.headless", icon='CONSOLE')
    L.operator("wm.url_open", text="Documentation", icon='HELP').url = \
        "https://github.com/Renderbricks/Renderbricker#documentation"
    return True


GUIDE = (
    ("Save the scene", _g_save, (
        "Renderbricker writes the subdivided parts into a cache file next to the scene - so the scene "
        "needs a file first.",
        "Save it under the name you want to keep.")),
    ("Choose the parts", _g_parts, (
        "All: every part of the scene.",
        "Selected: only the objects selected in the viewport or the Outliner.",
        "Collection: the parts in one collection and its child collections - handy for converting a "
        "large scene piece by piece.",
        "Parts outside the choice stay as imported.")),
    ("Settings", _g_settings, (
        "Variant A keeps the shading of the Mecabricks import (soft logos on the studs); B computes it "
        "from the smoothed surface (crisper logos).",
        "Viewport level: how smooth the parts look while you work. 1 keeps the viewport fast.",
        "Render level: how smooth they are in the render. 2 is enough even for close-ups.",
        "Use several cores: larger scenes are converted in parallel background Blenders.",
        "Cache file: the smoothed parts are stored in <scene>_rbcache.blend next to the scene, so the "
        "scene file stays small.",
        "Log file: the results of Apply, Check and Convert headless are also written into "
        "<scene>_renderbricker.log, with the full list of problems.",
        "Renderbricks camera: the first Apply creates the camera \"Renderbricks\" that frames the whole "
        "model and takes over the Renderbricks render settings and sky. The camera icon frames it again.",
        "The defaults suit most scenes.")),
    ("Apply", _g_apply, (
        "Apply decides for every edge of every part whether the real brick is sharp or round there, "
        "and sets a crease on the sharp ones.",
        "It then bakes the smoothed result into a copy of each part mesh; all bricks of the same kind "
        "share that copy.",
        "The imported mesh stays unchanged in the file - you can always go back.",
        "Esc cancels. With the cache file on, the scene is saved at the end.")),
    ("Check", _g_check, (
        "Check looks for folded faces and gaps along seams in the smoothed parts.",
        "The arrow next to a listed part selects it and frames it in the viewport.",
        "Folds can come from faces that are already broken in the import - render a close-up before "
        "you worry.")),
    ("Compare with the import", _g_compare, (
        "The button switches every brick between the smoothed copy (ON) and the imported mesh (OFF).",
        "Switch OFF and back ON: sharp edges of the real part stay sharp, round shapes like studs and "
        "tires turn round.")),
    ("Render", _g_render, (
        "F12 (image) and Ctrl+F12 (animation) switch the bricks to the render level while rendering "
        "and back to the viewport level afterwards.",
        "The Render menu has the same: Render Image / Animation (Renderbricker levels).",
        "With the option Renderbricks camera, the render uses the camera \"Renderbricks\" that frames "
        "the whole model.")),
    ("Done - what next", _g_next, (
        "Save As under another name or folder: the panel then offers Move cache here or Copy cache "
        "here, so the new file gets its cache.",
        "Large scenes: Convert headless converts in a terminal window and writes a new file; the open "
        "scene stays unchanged.",
        "Remove takes the scene back to the plain import.",
        "Start the guide again any time from the top of the panel.")),
)


def draw_guide(L, context):
    s = context.scene.mecsub
    i = min(s.wt_step, len(GUIDE) - 1)
    title, draw, text = GUIDE[i]
    head = L.row()
    head.label(text=f"Step {i + 1} of {len(GUIDE)}: {title}")
    head.operator("mecsub.guide_exit", text="", icon='X')
    bullets(L.box(), text, context)
    body = L.column()
    body.enabled = not s.running
    ready = draw(body, context, s)
    nav = L.row(align=True)
    nav.enabled = not s.running
    if i > 0:
        nav.operator("mecsub.guide_nav", text="Back", icon='TRIA_LEFT').delta = -1
    if i < len(GUIDE) - 1:
        nav.operator("mecsub.guide_nav", text="Next", icon='TRIA_RIGHT', depress=bool(ready)).delta = 1
    else:
        nav.operator("mecsub.guide_exit", text="Finish", icon='CHECKMARK', depress=True)


class MECSUB_OT_guide_start(bpy.types.Operator):
    bl_idname = "mecsub.guide_start"
    bl_label = "Start Guide"
    bl_description = "Step-by-step guide through the workflow, with an explanation for every step"

    def execute(self, context):
        s = context.scene.mecsub
        s.wt_active, s.wt_step = True, 0
        s.wt_compared = s.wt_rendered = False
        return {'FINISHED'}


class MECSUB_OT_guide_nav(bpy.types.Operator):
    bl_idname = "mecsub.guide_nav"
    bl_label = "Guide step"
    bl_description = "Go to the previous or next step of the guide"
    delta: IntProperty(default=1)

    def execute(self, context):
        s = context.scene.mecsub
        s.wt_step = max(0, min(s.wt_step + self.delta, len(GUIDE) - 1))
        return {'FINISHED'}


class MECSUB_OT_guide_exit(bpy.types.Operator):
    bl_idname = "mecsub.guide_exit"
    bl_label = "Exit guide"
    bl_description = "Close the guide and show the full panel"

    def execute(self, context):
        context.scene.mecsub.wt_active = False
        return {'FINISHED'}


class MECSUB_PT_panel(bpy.types.Panel):
    bl_label = f"Renderbricker {VERSION}"   # version in the header (runs 41/42); the rules version stays internal (user, 2026-09-28)
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Renderbricker"

    def draw(self, context):
        s = context.scene.mecsub
        L = self.layout
        if s.running:
            box = L.box()
            if hasattr(box, "progress"):
                box.progress(factor=s.progress, type='BAR', text=s.progress_text)
            else:
                box.label(text=f"{s.progress * 100:.0f} %  {s.progress_text}")
            box.label(text="Esc: cancel", icon='CANCEL')
        if s.wt_active:
            draw_guide(L, context)
            return
        row = L.row()
        row.scale_y = 1.3
        row.operator("mecsub.guide_start", icon='HELP')
        body = L.column()
        body.enabled = not s.running
        col = body.column(align=True)
        col.prop(s, "scope", expand=True)
        if s.scope == 'COLLECTION':
            col.prop(s, "collection", text="", icon='OUTLINER_COLLECTION')
        body.prop(s, "variant", text="")
        draw_levels(body, s, context)
        body.operator("mecsub.apply", icon='MOD_SUBSURF')
        body.prop(s, "use_cores")
        body.prop(s, "use_cache")
        body.prop(s, "use_log")
        row = body.row(align=True)
        row.prop(s, "use_setup")
        row.operator("mecsub.frame_camera", text="", icon='VIEW_CAMERA')
        st = core.cache_state()
        if st is not None:
            import os
            box = body.box()
            if not st[3]:
                box.label(text=f"Cache missing: {os.path.basename(st[1])}", icon='ERROR')
            elif st[1] != st[2]:
                box.label(text=f"Cache of another scene: {os.path.basename(st[1])}", icon='ERROR')
                row = box.row(align=True)
                row.operator("mecsub.move_cache", icon='FILE_FOLDER', text="Move cache here")
                row.operator("mecsub.copy_cache", icon='DUPLICATE', text="Copy cache here")
            else:
                box.label(text=f"Cache: {os.path.basename(st[1])}", icon='FILE_BLEND')
        row = body.row(align=True)
        row.operator("mecsub.check", icon='VIEWZOOM')
        state = s.subdiv_state
        label, icon = {"ON": ("Subdivision: ON", 'CHECKBOX_HLT'), "OFF": ("Subdivision: OFF", 'CHECKBOX_DEHLT'),
                       "MIXED": ("Subdivision: partly on", 'CHECKBOX_HLT')}.get(state, ("Subdivision: -", 'CHECKBOX_DEHLT'))
        row.operator("mecsub.toggle", icon=icon, text=label, depress=(state == "ON"))
        body.operator("mecsub.remove", icon='X')
        body.separator()
        body.operator("mecsub.headless", icon='CONSOLE')
        draw_summary(L, s)
        col = L.column(align=True)
        col.scale_y = 0.8
        for line in COPYRIGHT.split(" – "):         # holder on its own line, the name is never split
            col.label(text=line)


COPYRIGHT = "© 2026 Renderbricks® – Prof. Michael Klein"
TRADEMARK = "Renderbricks® is a registered trademark in Germany."
DISCLAIMER = ("Renderbricks is about rendering digital LEGO®. LEGO is a trademark of the LEGO Group of companies "
              "which does not sponsor, authorize or endorse this add-on.")
LINKS = (("www.renderbricks.com", "https://www.renderbricks.com", 'URL'),
         ("Facebook", "https://www.facebook.com/renderbricks", 'COMMUNITY'),
         ("YouTube", "https://www.youtube.com/@renderbricks", 'PLAY'),
         ("Renderbricker on GitHub", "https://github.com/Renderbricks/Renderbricker", 'HELP'))


def wrapped(layout, text, context):
    """Label lines that fit the sidebar width (a label does not wrap by itself)."""
    import textwrap
    width = context.region.width if context.region else 300
    chars = max(20, int(width / (7.5 * context.preferences.system.ui_scale)))
    col = layout.column(align=True)
    col.scale_y = 0.8
    for line in textwrap.wrap(text, chars):
        col.label(text=line)


class MECSUB_PT_about(bpy.types.Panel):
    bl_label = "About"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Renderbricker"
    bl_parent_id = "MECSUB_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        L = self.layout
        wrapped(L, TRADEMARK, context)
        col = L.column(align=True)
        for text, url, icon in LINKS:
            col.operator("wm.url_open", text=text, icon=icon).url = url
        wrapped(L, DISCLAIMER, context)


classes = (MECSUB_Problem, MECSUB_Settings, MECSUB_OT_apply, MECSUB_OT_check, MECSUB_OT_levels, MECSUB_OT_toggle,
           MECSUB_OT_remove, MECSUB_OT_select, MECSUB_OT_headless, MECSUB_PT_panel, MECSUB_OT_move_cache, MECSUB_OT_copy_cache,
           MECSUB_OT_cache_switch, MECSUB_OT_render, MECSUB_PT_about,
           MECSUB_OT_guide_start, MECSUB_OT_guide_nav, MECSUB_OT_guide_exit, MECSUB_OT_level_confirm,
           MECSUB_OT_frame_camera)


@persistent
def _unlock(*args):
    """A progress state saved or left behind by a crashed or stuck run must not lock the
    panel: nothing can be running when a file is loaded or the add-on is (re)registered.
    A missing cache file (moved or deleted): the objects show their originals (run 62)."""
    for sc in bpy.data.scenes:
        if getattr(sc, "mecsub", None) and sc.mecsub.running:
            sc.mecsub.running = False
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
        refresh_state()
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


HANDLERS = ((bpy.app.handlers.render_pre, _render_pre), (bpy.app.handlers.render_post, _render_post),
            (bpy.app.handlers.render_cancel, _render_post), (bpy.app.handlers.load_post, _unlock))

def register():
    # always load the rule module fresh: re-enabling or Reload Scripts kept the old one
    # in memory (header 1.5.4, rules of 1.5.3 - run 42)
    global core
    import importlib
    core = importlib.reload(core)
    MECSUB_PT_panel.bl_label = f"Renderbricker {VERSION}"
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.mecsub = PointerProperty(type=MECSUB_Settings)
    for lst, fn in HANDLERS:
        if fn not in lst:
            lst.append(fn)
    bpy.app.timers.register(_unlock, first_interval=0.1)     # after (re)installing in a stuck session
    bpy.types.TOPBAR_MT_render.prepend(_render_menu)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:                                   # F12 / Ctrl+F12 switch the level in the main thread (run 72)
        km = kc.keymaps.new(name="Screen", space_type='EMPTY')
        kmi = km.keymap_items.new(MECSUB_OT_render.bl_idname, 'F12', 'PRESS')
        kmi.properties.use_viewport = True
        _keymaps.append((km, kmi))
        kmi = km.keymap_items.new(MECSUB_OT_render.bl_idname, 'F12', 'PRESS', ctrl=True)
        kmi.properties.animation = True
        kmi.properties.use_viewport = True
        _keymaps.append((km, kmi))

def unregister():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()
    bpy.types.TOPBAR_MT_render.remove(_render_menu)
    for lst, fn in HANDLERS:
        if fn in lst:
            lst.remove(fn)
    del bpy.types.Scene.mecsub
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
