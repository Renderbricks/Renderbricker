"""F12 and Ctrl+F12 with the render level, and All views (render slots, timers)."""
import bpy
from bpy.app.handlers import persistent
from . import rbcore as core


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
        if core.render_camera_is_on(context.scene) and not self.animation:    # the view's own slot
            set_render_slot(context.scene.get("rb_camera_view", "FRONT"))
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


def _view3d_override():
    """Window and 3D view for starting a render outside an operator (the timer of the view chain)."""
    wm = bpy.context.window_manager
    want = _VIEWS.get("window")
    wins = sorted(wm.windows, key=lambda w: w.as_pointer() != want)
    for w in wins:
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                return {"window": w, "area": a}
    return {"window": wins[0]} if wins else {}


def ensure_render_result(override=None):
    """The image "Render Result" only exists after the first render; without it no slot can be chosen
    and the first render would always land in slot 1. Showing the render view creates it."""
    img = bpy.data.images.get("Render Result")
    if img is None:
        try:
            with bpy.context.temp_override(**(override or {})):
                bpy.ops.render.view_show('INVOKE_DEFAULT')
        except (RuntimeError, TypeError):
            pass
        img = bpy.data.images.get("Render Result")
    return img if img is not None and img.type == 'RENDER_RESULT' else None


def set_render_slot(view, override=None):
    """The render camera's views each render into a slot of their own (user, 2026-09-28): Slot 1 Front,
    2 Right, 3 Back, 4 Left, 5 Top, 6 Bottom; the slots are named after the views."""
    img = ensure_render_result(override)
    if img is None:
        return None
    keys = [k for k, _label, _d in core.CAMERA_VIEWS]
    for i, (_k, label, _d) in enumerate(core.CAMERA_VIEWS):
        if i < len(img.render_slots):
            img.render_slots[i].name = label
    i = keys.index(view) if view in keys else 0
    if i < len(img.render_slots):
        img.render_slots.active_index = i
    return i


# The chain of the six views runs on a timer, not in a modal operator: a render started while the
# event system hands a timer event through the panels crashed Blender 5.2.2 in ui::handler_panel
# (the render window changes the screen under the running handler loop). Esc in the render window
# cancels the running render; the render_cancel handler then stops the chain.
_VIEWS = {}


@persistent
def _views_cancelled(scene, *args):
    if _VIEWS.get("running"):
        _VIEWS["cancelled"] = True


def _views_tick():
    if not _VIEWS.get("running"):
        return None
    if bpy.app.is_job_running('RENDER'):
        return 0.25
    try:
        sc = bpy.data.scenes[_VIEWS["scene"]]
    except KeyError:
        _VIEWS.clear()
        return None
    if _VIEWS["rendering"]:
        _VIEWS["rendering"] = False
        if not _VIEWS["cancelled"]:
            _VIEWS["done"] += 1
    if _VIEWS["cancelled"] or not _VIEWS["queue"]:
        _views_finish(sc)
        return None
    view = _VIEWS["queue"].pop(0)
    ov = _view3d_override()
    core.camera_view(sc, view, bpy.context.evaluated_depsgraph_get())
    set_render_slot(view, ov)
    sc.mecsub.progress_text = f"Rendering view {6 - len(_VIEWS['queue'])} / 6: {view.title()}"
    try:
        with bpy.context.temp_override(**ov):
            r = bpy.ops.render.render('INVOKE_DEFAULT', use_viewport=True)
    except RuntimeError as e:
        print("Renderbricker: render of view", view, "not started:", e)
        r = {'CANCELLED'}
    if 'RUNNING_MODAL' in r or bpy.app.is_job_running('RENDER'):
        _VIEWS["rendering"] = True
    elif 'FINISHED' in r:
        _VIEWS["done"] += 1
    else:
        _VIEWS["cancelled"] = True
    return 0.25


def _views_finish(sc):
    _swap_back()
    _RENDER_OP[0] = False
    done, cancelled = _VIEWS["done"], _VIEWS["cancelled"]
    core.camera_view(sc, _VIEWS["start_view"], bpy.context.evaluated_depsgraph_get())
    _VIEWS.clear()
    sc["rb_views_rendered"] = done
    sc.mecsub.summary = f"{done} of 6 views rendered into the slots of the Render window" + (
        " (stopped)" if cancelled else "")
    sc.mecsub.progress_text = ""
    try:
        sc.mecsub.wt_rendered = True
    except (AttributeError, ReferenceError):
        pass
    print("Renderbricker:", sc.mecsub.summary)
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()


class MECSUB_OT_render_views(bpy.types.Operator):
    bl_idname = "mecsub.render_views"
    bl_label = "Render all views"
    bl_description = ("Render the six views of the render camera one after the other with the render level, each "
                      "into its own slot of the Render window (Slot 1 Front ... Slot 6 Bottom). Esc in the Render "
                      "window stops the chain; the camera returns to the view it had")

    @classmethod
    def poll(cls, context):
        return (core.render_camera_is_on(context.scene) and not bpy.app.is_job_running('RENDER')
                and not _VIEWS.get("running"))

    def execute(self, context):
        sc = context.scene
        sc.pop("rb_views_rendered", None)
        _VIEWS.clear()
        _VIEWS.update(running=True, scene=sc.name, start_view=sc.get("rb_camera_view", "FRONT"),
                      queue=[k for k, _label, _d in core.CAMERA_VIEWS], rendering=False, cancelled=False,
                      done=0, window=context.window.as_pointer() if context.window else 0)
        _swap_to_render(sc)
        _RENDER_OP[0] = True
        bpy.app.timers.register(_views_tick, first_interval=0.05)
        return {'FINISHED'}


def _render_menu(self, context):
    layout = self.layout
    layout.operator(MECSUB_OT_render.bl_idname, text="Render Image (Renderbricker levels)", icon='RENDER_STILL')
    op = layout.operator(MECSUB_OT_render.bl_idname, text="Render Animation (Renderbricker levels)", icon='RENDER_ANIMATION')
    op.animation = True
    layout.separator()


_keymaps = []
