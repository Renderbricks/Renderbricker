"""The Start Guide: its steps, their controls and the navigation."""
import bpy
from bpy.props import IntProperty
from . import camera_ui, logfile, panels, props, widgets


def _g_save(L, context, s):
    import os
    if bpy.data.filepath:
        L.operator("wm.save_mainfile", text="Save", icon='FILE_TICK')
    else:
        L.operator("wm.save_as_mainfile", text="Save As...", icon='FILE_TICK', depress=True).filepath =             widgets.save_as_name(context)
    ok = bool(bpy.data.filepath)
    widgets.status(L, ok, f"Saved: {os.path.basename(bpy.data.filepath)}" if ok else "Not saved yet")
    return ok


def _g_parts(L, context, s):
    props.draw_scope(L, s)
    ok, text = widgets.scope_state(context)
    widgets.status(L, ok, text)
    return ok


def _g_settings(L, context, s):
    L.prop(s, "variant", text="")
    widgets.draw_levels(L, s, context)
    L.prop(s, "use_cores")
    widgets.draw_low_memory(L, s)
    L.prop(s, "use_cache")
    logfile.draw_log(L, s)
    return True


def _g_apply(L, context, s):
    ok = s.subdiv_state in ("ON", "MIXED")
    row = L.row()
    row.scale_y = 1.3
    widgets.apply_button(row, context, depress=not ok)
    widgets.status(L, ok, "Parts converted" if ok else "Press Apply")
    widgets.draw_summary(L, s)
    return ok


def _g_check(L, context, s):
    ok = s.wt_checked
    row = L.row()
    row.scale_y = 1.3
    row.operator("mecsub.check", icon='VIEWZOOM', depress=not ok)
    if ok:
        widgets.status(L, s.wt_bad == 0, "No problems found" if s.wt_bad == 0
               else f"{s.wt_bad} parts with problems - see the list")
    else:
        widgets.status(L, False, "Press Check")
    widgets.draw_summary(L, s)
    return ok


def _g_compare(L, context, s):
    state = s.subdiv_state
    label, icon = {"ON": ("Subdivision: ON", 'CHECKBOX_HLT'), "OFF": ("Subdivision: OFF", 'CHECKBOX_DEHLT'),
                   "MIXED": ("Subdivision: partly on", 'CHECKBOX_HLT')}.get(state, ("Subdivision: -", 'CHECKBOX_DEHLT'))
    ok = s.wt_compared and state == "ON"
    row = L.row()
    row.scale_y = 1.3
    row.operator("mecsub.toggle", icon=icon, text=label, depress=(state == "ON"))
    widgets.status(L, ok, "Compared - subdivision is on" if ok else
           ("Switch it back ON" if state == "OFF" else "Switch OFF, look, switch back ON"))
    return ok


def _g_render(L, context, s):
    ok = s.wt_rendered
    camera_ui.draw_render_camera(L, context, render_button=False)     # the step has its own render button
    row = L.row()
    row.scale_y = 1.3
    op = row.operator("mecsub.render", text="Render Image (F12)", icon='RENDER_STILL', depress=not ok)
    op.use_viewport = True
    widgets.status(L, ok, "Rendered with the render level" if ok else "Press F12 or the button")
    return ok


def _g_next(L, context, s):
    L.operator("mecsub.headless", icon='CONSOLE')
    L.operator("wm.url_open", text="Documentation", icon='HELP').url = panels.DOCUMENTATION_URL
    return True


GUIDE = (
    ("Import and save", _g_save, (
        "Import the model from Mecabricks: File > Import > Mecabricks (.zmbx) - the Mecabricks Lite or "
        "Advanced add-on by Nicolas 'Scrubs' Jarraud.",
        "Renderbricker writes the smoothed parts into a cache file next to the scene - so the scene "
        "needs a file first.",
        "Save it under the name you want to keep - Save As offers the name of the imported model.")),
    ("Choose the parts", _g_parts, (
        "All: every part of the scene.",
        "Selected: only the objects selected in the viewport or the Outliner.",
        "Collection: the parts in the collections of the list and their child collections - the list "
        "starts empty, + adds the collection active in the Outliner. Handy for converting a large scene piece by piece.",
        "The camera icon of a collection marks it for the render camera: with the camera on, only the "
        "marked collections are shown and rendered.",
        "Parts outside the choice stay as imported.")),
    ("Settings", _g_settings, (
        "The defaults suit most scenes.",
        "Variant A keeps the shading of the Mecabricks import (soft logos on the studs); B computes it "
        "from the smoothed surface (crisper logos).",
        "Viewport level: how smooth the parts look while you work. 1 keeps the viewport fast.",
        "Render level: how smooth they are in the render. 2 is enough even for close-ups.",
        "Use several Blender processes: larger scenes are converted by several Blenders in the background "
        "at the same time - how many depends on the processor and the free memory.",
        "Low Memory: only for very large parts or little memory (16 or 32 GB) - Auto decides.",
        "Cache file: the copies are stored in <scene>_rbcache.blend next to the scene, so the scene file "
        "stays small.",
        "Log file: the results of Apply, Check and Convert headless are also written into "
        "<scene>_Renderbricker.log, with the full list of problems; the icon next to it opens it.")),
    ("Apply", _g_apply, (
        "Apply decides for every edge of every part whether the real part is sharp or round there, "
        "and sets a crease on the sharp ones.",
        "It then bakes the smoothed result into a copy of each part; all links of the part share that copy.",
        "The imported mesh stays unchanged in the file - you can always go back.",
        "Esc cancels. With the cache file on, the scene is saved at the end.",
        "Afterwards the button reads Apply: up to date; Shift+click converts all parts again.")),
    ("Compare with the import", _g_compare, (
        "The button switches every link between the smoothed copy (ON) and the imported mesh (OFF).",
        "Switch OFF and back ON: edges that are sharp on the real part stay sharp, round shapes like studs "
        "and tires turn round.")),
    ("Check", _g_check, (
        "Check looks for folded faces and gaps along seams in the smoothed parts.",
        "The arrow next to a listed part selects it and frames it in the viewport.",
        "Folds can come from faces that are already broken in the import - render a close-up before "
        "you worry.")),
    ("Render", _g_render, (
        "F12 (image) and Ctrl+F12 (animation) switch the parts to the render level while rendering "
        "and back to the viewport level afterwards.",
        "The Render menu has the same: Render Image / Animation (Renderbricker levels).",
        "Render camera ON: the camera \"Renderbricks\" frames the whole model, a world \"Renderbricks Sky\" "
        "(Physical Sky) and the Renderbricks render settings are used. OFF brings your own camera, world and "
        "render settings back - nothing is overwritten.",
        "The camera icon frames the model again, e.g. after adding parts.",
        "Front, Right, Back, Left, Top, Bottom turn the camera around the model: Front is the view of the "
        "render setup, the others go round in 90° steps or look from above and below.",
        "Below: the sun fixed or turning with the camera, Transparent, Resolution Scale, the samples, "
        "Render (F12) and All views (each view into its own slot).")),
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
    widgets.bullets(L.box(), text, context)
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
