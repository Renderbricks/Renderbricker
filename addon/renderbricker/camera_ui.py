"""The render camera in the panel: ON/OFF, views, sun, transparency, samples."""
import bpy
from bpy.props import EnumProperty, IntProperty
from . import rbcore as core
from . import common, convert, props


_VIEW_BEFORE = {}           # 3D viewport -> (view, relationship lines, statistics) before Render camera ON


_PROPS_BEFORE = {}      # Properties editor: its tab before the render camera was switched on


def properties_output(context, on):
    """Render camera ON: the Properties editors show the Output tab (resolution, scale, file); OFF: the
    tab they had before (user, 2026-09-28)."""
    screen = context.screen
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'PROPERTIES':
            continue
        space = area.spaces.active
        key = area.as_pointer()
        try:
            if on:
                _PROPS_BEFORE.setdefault(key, space.context)
                space.context = 'OUTPUT'
            elif key in _PROPS_BEFORE:
                space.context = _PROPS_BEFORE.pop(key)
        except (TypeError, AttributeError):
            pass
        area.tag_redraw()


def viewport_camera(context, on):
    """Render camera ON (and the view buttons): the 3D viewport of the button looks through the camera,
    relationship lines off, statistics on; OFF: back to how it was before (user, 2026-09-28). Without a
    3D viewport (scripts) nothing."""
    properties_output(context, on)
    area = context.area if context.area and context.area.type == 'VIEW_3D' else None
    if area is None and context.screen:
        area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        return
    space = area.spaces.active
    r3d, ov = space.region_3d, space.overlay
    key = area.as_pointer()
    if on:
        if key not in _VIEW_BEFORE:
            _VIEW_BEFORE[key] = (r3d.view_perspective, ov.show_relationship_lines, ov.show_stats)
        r3d.view_perspective = 'CAMERA'
        ov.show_relationship_lines = False
        ov.show_stats = True
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is not None:                  # the camera frame fills the viewport (Frame Camera Bounds)
            try:
                with context.temp_override(area=area, region=region):
                    bpy.ops.view3d.view_center_camera()
            except RuntimeError:
                pass
    else:
        before = _VIEW_BEFORE.pop(key, None)
        if before is None:
            before = ('PERSP', ov.show_relationship_lines, ov.show_stats)
        r3d.view_perspective = before[0]        # a camera view before: now through the scene's own camera
        ov.show_relationship_lines, ov.show_stats = before[1], before[2]
    area.tag_redraw()


class MECSUB_OT_render_camera(bpy.types.Operator):
    bl_idname = "mecsub.render_camera"
    bl_label = "Render camera"
    bl_description = ("ON: the camera \"Renderbricks\" (framing the whole model) and the world \"Renderbricks Sky\" "
                      "(Physical Sky) become active and the Renderbricks render settings are taken over. OFF: the "
                      "scene's camera, world and render settings from before come back - nothing of your own setup "
                      "is overwritten. ON again brings back the settings you had at the last OFF (samples, "
                      "Transparent, Resolution Scale ...); Shift+click starts fresh from the setup scene")
    bl_options = {'REGISTER', 'UNDO'}
    fresh: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.fresh = event.shift
        return self.execute(context)

    def execute(self, context):
        common.object_mode(context)
        sc = context.scene
        if core.render_camera_is_on(sc):
            text = core.render_camera_off(sc)
            viewport_camera(context, False)
        else:
            text = core.render_camera_on(sc, props.setup_blend(), context.evaluated_depsgraph_get(),
                                         props.camera_collections(sc.mecsub), fresh=self.fresh)
            viewport_camera(context, True)
        context.scene.mecsub.summary = text
        self.report({'INFO'}, "Renderbricker: " + text)
        convert.redraw(context)
        return {'FINISHED'}


class MECSUB_OT_frame_camera(bpy.types.Operator):
    bl_idname = "mecsub.frame_camera"
    bl_label = "Frame camera"
    bl_description = ("Move the camera \"Renderbricks\" so that all visible parts fill the picture again (its "
                      "direction stays), e.g. after adding parts")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return core.render_camera_is_on(context.scene)

    def execute(self, context):
        common.object_mode(context)
        cam, _made = core.render_camera(context.scene)
        core.picture_orientation(context.scene, context.scene.get("rb_camera_view", "FRONT"))
        ok = core.frame_camera(context.scene, cam, context.evaluated_depsgraph_get())
        self.report({'INFO'}, "Renderbricker: " + ("camera Renderbricks framed" if ok else "no visible parts to frame"))
        return {'FINISHED'}


class MECSUB_OT_camera_view(bpy.types.Operator):
    bl_idname = "mecsub.camera_view"
    bl_label = "Camera view"
    bl_description = ("Turn the camera \"Renderbricks\" around the model and frame it: Front is the view of the "
                      "setup scene, Right / Back / Left go round in 90° steps, Top and Bottom look straight down "
                      "and up. For Bottom the sky is mirrored vertically, so the sun lights the underside (the "
                      "first time the sky is rendered as a panorama, a few seconds)")
    bl_options = {'REGISTER', 'UNDO'}
    view: EnumProperty(items=[(k, label, "") for k, label, _d in core.CAMERA_VIEWS], default="FRONT")

    @classmethod
    def poll(cls, context):
        return core.render_camera_is_on(context.scene)

    def execute(self, context):
        common.object_mode(context)
        ok = core.camera_view(context.scene, self.view, context.evaluated_depsgraph_get())
        viewport_camera(context, True)
        if not ok:
            self.report({'WARNING'}, "Renderbricker: no camera or no visible parts to frame")
        if self.view == "BOTTOM" and context.scene.world and not context.scene.world.get(core.BELOW_TAG)                 and context.scene.world.get(core.SKY_TAG):
            self.report({'WARNING'}, "Renderbricker: mirrored sky not made (see the console)")
        convert.redraw(context)
        return {'FINISHED'}


class MECSUB_OT_sun_follow(bpy.types.Operator):
    bl_idname = "mecsub.sun_follow"
    bl_label = "Sun turns with the camera"
    bl_description = ("Off (default): the sun stays where it is and the views show the model from all sides in the "
                      "same light. On: the sun turns with the camera, so every view is lit as the Front view")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return core.render_camera_is_on(context.scene)

    def execute(self, context):
        sc = context.scene
        sc[core.SUN_FOLLOW] = not bool(sc.get(core.SUN_FOLLOW))
        note = core.apply_sky(sc, sc.get("rb_camera_view", "FRONT"))
        if note:
            self.report({'WARNING'}, "Renderbricker: " + note)
        convert.redraw(context)
        return {'FINISHED'}


def is_transparent(scene):
    cyc = getattr(scene, "cycles", None)
    return scene.render.film_transparent and (cyc is None or getattr(cyc, "film_transparent_glass", True))


class MECSUB_OT_transparent(bpy.types.Operator):
    bl_idname = "mecsub.transparent"
    bl_label = "Transparent"
    bl_description = ("Film Transparent together with Transparent Glass: the sky is left out of the picture "
                      "(alpha), and glass shows what lies behind it in the final image. The sky still lights "
                      "the model. Render camera OFF brings back your own setting")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return core.render_camera_is_on(context.scene)

    def execute(self, context):
        sc = context.scene
        on = not is_transparent(sc)
        sc.render.film_transparent = on
        cyc = getattr(sc, "cycles", None)
        if cyc is not None and hasattr(cyc, "film_transparent_glass"):
            cyc.film_transparent_glass = on
        convert.redraw(context)
        return {'FINISHED'}


SAMPLE_LEVELS = (("Low", 128), ("Medium", 256), ("Good", 512), ("High", 1024))   # user, 2026-09-28


def render_samples(sc):
    return sc.eevee.taa_render_samples if sc.render.engine.startswith("BLENDER_EEVEE") else sc.cycles.samples


class MECSUB_OT_samples(bpy.types.Operator):
    bl_idname = "mecsub.samples"
    bl_label = "Render samples"
    bl_options = {'REGISTER', 'UNDO'}
    samples: IntProperty(default=1024, min=1)

    @classmethod
    def description(cls, context, properties):
        name = next((n for n, v in SAMPLE_LEVELS if v == properties.samples), "")
        return (f"{name}: {properties.samples} render samples (Cycles and EEVEE). Render camera OFF brings "
                f"your own samples back")

    def execute(self, context):
        sc = context.scene
        sc.cycles.samples = self.samples
        sc.eevee.taa_render_samples = self.samples
        return {'FINISHED'}


def draw_render_camera(L, context, render_button=True):
    sc = context.scene
    on = core.render_camera_is_on(sc)
    col = L.column(align=True)
    row = col.row(align=True)
    row.operator("mecsub.render_camera", text=f"Render camera: {'ON' if on else 'OFF'}",
                 icon='OUTLINER_OB_CAMERA' if on else 'CAMERA_DATA', depress=on)
    row.operator("mecsub.frame_camera", text="", icon='VIEW_CAMERA')
    if on:
        only = props.camera_collections(sc.mecsub)
        if only:
            col.label(text="Only: " + ", ".join(c.name for c in only), icon='HIDE_OFF')
        current = sc.get("rb_camera_view", "")
        for keys in (core.CAMERA_VIEWS[0:2], core.CAMERA_VIEWS[2:4], core.CAMERA_VIEWS[4:6]):   # in pairs
            row = col.row(align=True)
            for k, label, _d in keys:
                row.operator("mecsub.camera_view", text=label, depress=(k == current)).view = k
        follow = bool(sc.get(core.SUN_FOLLOW))  # sun fixed or turning with the camera (user, 2026-09-28)
        col.operator("mecsub.sun_follow", text="Sun: turns with the camera" if follow else "Sun: fixed",
                     icon='LIGHT_SUN', depress=follow)
        clear = is_transparent(sc)            # background and glass transparent (user, 2026-09-28)
        col.operator("mecsub.transparent", text="Transparent: on" if clear else "Transparent: off",
                     icon='TEXTURE' if clear else 'WORLD', depress=clear)
        col.prop(sc.render, "resolution_percentage", text="Resolution Scale")
        n = render_samples(sc)
        col.label(text=f"Samples: {n}", icon='RENDER_STILL')
        row = col.row(align=True)
        for name, value in SAMPLE_LEVELS:
            row.operator("mecsub.samples", text=name, depress=(n == value)).samples = value
    if on and render_button:
        row = col.row(align=True)             # render through the camera (user, 2026-09-28)
        row.scale_y = 1.3
        op = row.operator("mecsub.render", text="Render (F12)", icon='RENDER_STILL')
        op.use_viewport = True
        row.operator("mecsub.render_views", text="All views", icon='RENDERLAYERS')
