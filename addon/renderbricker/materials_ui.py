"""Materials: Mecabricks or Physicalbricks for every Mecabricks material of the file (UPDATES #59).

The row below Import from Mecabricks, its options in mode Physicalbricks and the sub-panels Print and Parts Jitter.
The work is the vendored Physicalbricks library's (renderbricker.physicalbricks): this module calls only its
registry (acting, switch, settings_of), switch.has_import() and reads AVAILABLE and EFFECTS of its own copy. Nothing
switches by itself: only the button does. A panel's draw() reads only the settings object of the scene, AVAILABLE and
scene['rb_phys_skipped']."""
import sys

import bpy

NO_MODEL = "No Mecabricks model in the file"
NEEDS_5 = "Physicalbricks needs Blender 5.0+"
MODES = (("MECABRICKS", "Mecabricks", "The original Mecabricks materials"),
         ("PHYSICAL", "Physicalbricks", "Physically based LEGO materials: ABS with subsurface scattering, glass with "
                                        "absorption in the volume, rubber, pearl, metal, glitter, speckle, opal "
                                        "(Blender 5.0+)"))


def lib():
    """The vendored library, looked up at call time: enabling the add-on again imports it anew."""
    return sys.modules[__package__ + ".physicalbricks"]


def settings(scene):
    """The scene's settings object as the acting copy's host gives it (Dev's when Dev is enabled), or None."""
    try:
        return lib().registry.settings_of(scene)
    except (KeyError, AttributeError):
        return None


class MECSUB_OT_material_system(bpy.types.Operator):
    bl_idname = "mecsub.material_system"
    bl_label = "Materials"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(name="Materials", items=MODES)

    @classmethod
    def poll(cls, context):
        L = lib()
        return bool(L.AVAILABLE) and L.registry.acting() is not None and settings(context.scene) is not None

    @classmethod
    def description(cls, context, properties):
        return dict((m[0], m[2]) for m in MODES).get(properties.mode, "")

    def execute(self, context):
        L = lib()
        if not L.switch.has_import():
            self.report({'WARNING'}, NO_MODEL)
            return {'CANCELLED'}
        networks, skipped = L.registry.switch(self.mode)
        if self.mode == 'PHYSICAL':
            text = f"Physicalbricks: {networks} materials"
            if skipped:
                text += f", {skipped} edited materials left as they are"
        else:
            text = "Mecabricks materials"
        self.report({'INFO'}, text)
        return {'FINISHED'}


def draw_materials(L, context):
    """The row Materials with Mecabricks | Physicalbricks, and the options of mode Physicalbricks below it."""
    s = settings(context.scene)
    if s is None:
        return
    available = lib().AVAILABLE
    col = L.column()
    row = col.row(align=True)
    row.label(text="Materials")
    buttons = row.row(align=True)
    for mode, text, _tip in MODES:
        buttons.operator(MECSUB_OT_material_system.bl_idname, text=text,
                         depress=s.material_system == mode).mode = mode
    row.enabled = bool(available)
    if not available:
        col.label(text=NEEDS_5, icon='INFO')
        return
    if s.material_system != 'PHYSICAL':
        return
    col.row().prop(s, "physical_subsurface", expand=True)
    glow = col.row(align=True)
    glow.prop(s, "glow_in_dark")
    strength = glow.row(align=True)
    strength.prop(s, "glow_strength", text="Strength")
    strength.enabled = s.glow_in_dark
    col.row().prop(s, "yellowing")
    skipped = context.scene.get("rb_phys_skipped", 0)
    if skipped:
        col.label(text=f"{skipped} edited materials left as they are", icon='ERROR')


class _Sub:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Renderbricker"
    bl_parent_id = "MECSUB_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}


class MECSUB_PT_print(_Sub, bpy.types.Panel):
    """The print's ink in mode Physicalbricks (Ink Wear and Ink Rim Wear only with the library's EFFECTS)."""
    bl_label = "Print"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        s = settings(context.scene)
        return bool(lib().AVAILABLE) and s is not None and s.material_system == 'PHYSICAL'

    def draw(self, context):
        s = settings(context.scene)
        col = self.layout.column()
        names = ["surface_ink_relief", "surface_ink_grain", "surface_ink_contour"]
        if lib().EFFECTS:
            names += ["surface_ink_wear", "surface_ink_wear_rims"]
        for name in names + ["surface_ink_seed"]:
            col.prop(s, name)


class MECSUB_PT_parts_jitter(_Sub, bpy.types.Panel):
    """Every part a little moved and turned - in both modes and below Blender 5.0 too (it moves objects)."""
    bl_label = "Parts Jitter"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return settings(context.scene) is not None

    def draw(self, context):
        s = settings(context.scene)
        L = self.layout
        note = L.row()
        note.scale_y = 0.7
        note.label(text="Moves and turns every part a little")
        for value, seed in (("parts_translate", "parts_translate_seed"), ("parts_rotate", "parts_rotate_seed")):
            split = L.row().split(factor=0.72, align=True)
            split.row(align=True).prop(s, value)
            split.row(align=True).prop(s, seed, text="")
        L.row().prop(s, "parts_mute")
