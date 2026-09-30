"""Scene settings of the panel (mecsub), the levels with their question above 2, the collection list."""
import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty, CollectionProperty, PointerProperty
from . import rbcore as core
from . import common


# ---------------------------------------------------------------- properties
class MECSUB_Problem(bpy.types.PropertyGroup):
    obj: StringProperty()
    info: StringProperty()


def _processed_groups(context):
    idx = core.copy_index_begin() if core._COPY_INDEX[0] is None else core._COPY_INDEX[0]
    return [(me, obs) for me, obs in common.by_mesh(common.targets(context)).items() if idx.get(me.name)]


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


def scope_collections(s):
    """The collections of the list (scenes from before: the single collection)."""
    cols = [it.collection for it in s.collections if it.collection is not None]
    if not cols and s.collection is not None:
        cols = [s.collection]
    return cols


def camera_collections(s):
    """The collections marked for the render camera (only these shown and rendered)."""
    return [it.collection for it in s.collections if it.render and it.collection is not None]


def _collection_render_update(self, context):
    """A collection marked or unmarked for the camera while it is on: show and frame the new choice."""
    sc = context.scene
    if not core.render_camera_is_on(sc):
        return
    core.isolate(sc, camera_collections(sc.mecsub))
    cam, _made = core.render_camera(sc)
    core.picture_orientation(sc, sc.get("rb_camera_view", "FRONT"))
    core.frame_camera(sc, cam, context.evaluated_depsgraph_get())


class MECSUB_CollectionItem(bpy.types.PropertyGroup):
    collection: PointerProperty(type=bpy.types.Collection, name="Collection",
                                description="Apply, Check, On/Off, Levels and Remove work on the parts in this "
                                            "collection and its child collections")
    render: bpy.props.BoolProperty(name="Render camera", default=False, update=_collection_render_update,
                                   description="With the render camera on, only the collections marked here are "
                                               "shown and rendered (none marked: everything)")


class MECSUB_UL_collections(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        if item.collection is not None:     # a name, no field: its x only cleared the entry (user, 2026-09-28)
            row.label(text=item.collection.name, icon='OUTLINER_COLLECTION')
        else:                               # an empty entry: choose a collection
            row.prop(item, "collection", text="", icon='OUTLINER_COLLECTION')
        row.prop(item, "render", text="", emboss=False,
                 icon='OUTLINER_OB_CAMERA' if item.render else 'CAMERA_DATA')


class MECSUB_OT_collection_add(bpy.types.Operator):
    bl_idname = "mecsub.collection_add"
    bl_label = "Add collection"
    bl_description = "Add the collection active in the Outliner to the list (or an empty entry to choose one)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.mecsub
        c = context.collection
        listed = {it.collection for it in s.collections}
        it = s.collections.add()
        if c is not None and c != context.scene.collection and c not in listed:
            it.collection = c
        s.collections_index = len(s.collections) - 1
        return {'FINISHED'}


class MECSUB_OT_collection_remove(bpy.types.Operator):
    bl_idname = "mecsub.collection_remove"
    bl_label = "Remove collection"
    bl_description = "Remove the selected collection from the list (the collection itself stays)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.mecsub.collections) > 0

    def execute(self, context):
        s = context.scene.mecsub
        i = min(s.collections_index, len(s.collections) - 1)
        s.collections.remove(i)
        s.collections_index = max(0, i - 1)
        _collection_render_update(None, context)
        return {'FINISHED'}


def draw_scope(L, s):
    col = L.column(align=True)
    col.prop(s, "scope", expand=True)
    if s.scope == 'COLLECTION':
        row = L.row()
        row.template_list("MECSUB_UL_collections", "", s, "collections", s, "collections_index", rows=2)
        sub = row.column(align=True)
        sub.operator("mecsub.collection_add", text="", icon='ADD')
        sub.operator("mecsub.collection_remove", text="", icon='REMOVE')


def scope_empty_text(context):
    s = context.scene.mecsub
    if s.scope == 'COLLECTION' and not scope_collections(s):
        return "Add a collection first"
    return "No mesh objects in scope"


# ---------------------------------------------------------------- sun sliders (user, 2026-09-30)
_BELOW_DUE = [0.0, None]        # when the mirrored sky of Bottom is made again, for which scene


def _below_tick():
    """Make the mirrored sky of Bottom again once the sliders have rested for a moment (every slider
    change would otherwise start a panorama render)."""
    import time
    if time.monotonic() < _BELOW_DUE[0]:
        return 0.25
    sc = bpy.data.scenes.get(_BELOW_DUE[1] or "")
    _BELOW_DUE[1] = None
    if sc is not None and sc.world is not None and sc.world.get(core.BELOW_TAG):
        core.apply_sky(sc, "BOTTOM")
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
    return None


def sun_changed(scene, below):
    """After a slider change: the mirrored sky of Bottom is made again a little later."""
    if not below:
        return
    import time
    _BELOW_DUE[0], _BELOW_DUE[1] = time.monotonic() + 0.8, scene.name
    if bpy.app.background:
        _BELOW_DUE[0] = 0.0
        _below_tick()
    elif not bpy.app.timers.is_registered(_below_tick):
        bpy.app.timers.register(_below_tick, first_interval=0.3)


def _altitude_get(self):
    return 100.0 * core.altitude_position(core.sun_values(core.sky_world())["altitude"])


def _altitude_set(self, value):
    """Dragged or typed up to 100: a position on the slider (%); typed above 100: metres, as they are."""
    m = value if value > 100.0 else core.altitude_from_position(value / 100.0)
    sc = self.id_data
    sun_changed(sc, core.set_sun(sc, "altitude", m))


def _sun_prop(key, angle=False):
    import math

    def get(self):
        v = core.sun_values(core.sky_world())[key]
        return math.radians(v) if angle else v

    def set(self, value):
        sc = self.id_data
        sun_changed(sc, core.set_sun(sc, key, math.degrees(value) if angle else value))
    return get, set


class MECSUB_Settings(bpy.types.PropertyGroup):
    scope: EnumProperty(name="Scope", items=[
        ('ALL', "All", "Every mesh object in the scene"),
        ('SELECTED', "Selected", "Selected mesh objects only"),
        ('COLLECTION', "Collection", "Mesh objects in the chosen collection and its child collections")],
        default='ALL')        # Collection starts with an empty list (user, 2026-09-28)
    collections: CollectionProperty(type=MECSUB_CollectionItem)
    collections_index: IntProperty(default=0)
    collection: PointerProperty(type=bpy.types.Collection, name="Collection",       # scenes from before: taken over
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
        name="Use several Blender processes", default=True,
        description="Apply on larger scenes (about 40 meshes and more) starts several Blenders in the "
                    "background that share the parts, and loads the result into this scene - the scene is saved "
                    "first. How many depends on the processor and the free memory; every one of them uses "
                    "several processor cores itself")
    low_memory: bpy.props.EnumProperty(
        name="Low Memory", default='AUTO',
        items=[('AUTO', "Auto", "On only when a single part needs so much memory that otherwise less than half "
                                "the Blender processes could run (a part of many GB, like NINJAGO City's)"),
               ('OFF', "Off", "Every Blender process gets its share of the parts at once and books large parts "
                              "in a shared memory ledger - the fastest way when there is memory enough"),
               ('ON', "On", "The parts are cut into small segments, each baked by a fresh Blender that ends "
                            "afterwards and gives its memory back; a segment starts only when there is room - "
                            "slower, for computers with little memory (16 or 32 GB) or very large parts")],
        description="How the Blender processes share the parts: all at once (fastest) or in small segments "
                    "that need less memory")
    use_cache: bpy.props.BoolProperty(
        name="Cache file next to the scene", default=True, update=_cache_update,
        description="The subdivided copies are kept in <scene>_rbcache.blend next to the scene and "
                    "linked into it (as library overrides that carry the scene's materials): the scene file "
                    "stays about as large as the import. Needs a saved scene")
    use_log: bpy.props.BoolProperty(
        name="Log file", default=False,
        description="Write the results of Apply, Check and Convert headless into <scene>_Renderbricker.log "
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
    # the sun of the add-on's sky, while the render camera is on (user, 2026-09-30): the values live on the
    # sky world, these only show them; the arrows beside them step in 10 deg / 1,000 m / 0.01
    sun_elevation: bpy.props.FloatProperty(
        name="Elevation", subtype='ANGLE', min=-0.2618, max=3.4034, precision=0,
        get=_sun_prop("elevation", True)[0], set=_sun_prop("elevation", True)[1],
        description="Height of the sun above the horizon: from 15° below it over the top (90°) to the other "
                    "side (195°). The arrows go in 10° steps, a typed value stays as it is")
    sun_rotation: bpy.props.FloatProperty(
        name="Rotation", subtype='ANGLE', min=0.0, max=6.2832, precision=0,
        get=_sun_prop("rotation", True)[0], set=_sun_prop("rotation", True)[1],
        description="Direction of the sun around the model. The arrows go in 10° steps, a typed value "
                    "stays as it is. With \"Sun turns with the camera\" this is the direction for the Front view")
    sun_altitude: bpy.props.FloatProperty(       # the slider's position; 0 ... 10,000 m on its first half
        name="Altitude", subtype='PERCENTAGE', min=0.0, max=100000.0, soft_min=0.0, soft_max=100.0, precision=0,
        get=_altitude_get, set=_altitude_set,
        description="Height of the viewer above the ground - the higher, the clearer and darker the sky. The "
                    "first half of the slider covers 0 to 10,000 m, the second 10,000 to 100,000 m. A typed "
                    "number above 100 is taken as metres. The arrows go in steps of 1,000 m up to 10,000 m and "
                    "of 10,000 m above")
    sky_strength: bpy.props.FloatProperty(
        name="Strength", min=0.0, max=10.0, soft_min=0.01, soft_max=0.1, precision=3,
        get=_sun_prop("strength")[0], set=_sun_prop("strength")[1],
        description="Brightness of the sky (Strength of the Background node): the slider goes from 0.01 to "
                    "0.1, a typed value can lie outside. The arrows go in steps of 0.01")
