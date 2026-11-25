# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of its own: scene.rb_phys, the settings object of a host without a panel of its own for the library's values
(Renderbricker beside Nicolas' Lite or Advanced). The library reads it through host.settings_of, whose default is
getattr(scene, 'rb_phys', None) - a host that has its own settings object supplies settings_of instead.

    RbPhysSettings      the 17 values the library reads: material system, subsurface, SSS factor, Yellowing, glow,
                        the print's ink, Parts Jitter - names, types, limits, defaults, labels and tooltips as
                        Renderbricks Dev's panel has them (except a sentence on an import option only Dev has);
                        each update calls the library and does nothing below Blender 5.0 (constants.AVAILABLE) -
                        except Parts Jitter's, which acts there too
    register_pointer()  the class and bpy.types.Scene.rb_phys - only the acting copy (registry.elect) holds them
    unregister_pointer()  both again; either may run when there is nothing to do
    from_file(scene, mode)  scene.rb_phys in line with the file each time a file opens (registry._load_work)

Values stored in a file stay when the class changes: a PropertyGroup's values are ID properties of the scene, read by
name (rna_ID.cc: for property groups user and system properties are the same group), so the next copy's class reads
them where the last one left them. Part of the frozen cross-copy contract (registry.py): register_pointer and
unregister_pointer.

Part of Physicalbricks (see __init__.py)."""
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
)

from . import host, jitter, surface, switch
from . import scene as scenes
from .constants import AVAILABLE
from .scene import AFTERGLOW

POINTER = 'rb_phys'


def update_material_system(self, context):
    """Switch every Mecabricks material of the file."""
    if AVAILABLE:
        switch.set_material_system(self.material_system)


def update_physical_subsurface(self, context):
    if AVAILABLE:
        scenes.set_subsurface_method(self.physical_subsurface)


def update_glow(self, context):
    if AVAILABLE:
        scenes.apply_afterglow()


def update_yellowing(self, context):
    """A slider move is the user's choice: the scene's Yellowing holds a value of its own from now on, no record default
    goes over it (surface.YELLOWING_SET; self.id_data is the scene that owns rb_phys)."""
    if AVAILABLE:
        self.id_data[surface.YELLOWING_SET] = True
        surface.apply_surface(self)
        surface.yellowing_viewport()


def update_surface(self, context):
    if AVAILABLE:
        surface.apply_surface(self)


def update_parts(self, context):
    """Parts Jitter acts in every Blender, below 5.0 too: it only writes delta transforms of the parts host.parts_of
    finds (spec section 7: Lite and Advanced users get it through the carrying add-on, whatever the switch)."""
    jitter.apply(getattr(context, 'scene', None) or bpy.context.scene, self)


class RbPhysSettings(bpy.types.PropertyGroup):
    """The settings group scene.rb_phys: material system, physical options, the print's ink and Parts Jitter."""
    material_system: EnumProperty(
        name="Materials",
        description="The shader concept of every Mecabricks material: Mecabricks or Physicalbricks",
        items=(("MECABRICKS", "Mecabricks", "The original Mecabricks materials"),
               ("PHYSICAL", "Physicalbricks", ("Physically based LEGO materials: ABS with subsurface scattering, "
                                               "glass with absorption in the volume, rubber, pearl, metal, glitter, "
                                               "speckle, opal (Blender 5.0+)"))),
        default="MECABRICKS",
        update=update_material_system,
    )
    physical_subsurface: EnumProperty(
        name="Subsurface",
        description="Subsurface scattering of the physical solid plastic",
        items=(("BURLEY", "Burley", "Diffusion: clean on Mecabricks parts (open, intersecting shells)"),
               ("RANDOM_WALK", "Random Walk", "Volume paths (Cycles' Random Walk Skin): sharper detail than Burley")),
        default="BURLEY",
        update=update_physical_subsurface,
    )
    glow_in_dark: BoolProperty(
        name="Glow in the dark",
        description="Phosphorescent colours (Phosphorescent White, Phosphorescent Green, White Glow) shine with their "
                    "afterglow: visible in dark scenes, a faint tint in daylight. Off: their plain daylight look",
        default=True,
        update=update_glow,
    )
    glow_strength: FloatProperty(
        name="Glow strength",
        description="Brightness of the afterglow: 1 = the strength of the material record",
        min=0.0,
        soft_max=10.0,
        default=0.1,
        update=update_glow,
    )
    sss_factor: FloatProperty(
        name="SSS Factor",
        description="How far light travels inside the plastic, for every colour at once: 1 as the colour has it, "
                    "2 twice as far - thin parts glow more in back light and the shading gets softer",
        min=0.0, soft_min=surface.SSS_FACTOR_RANGE[0], soft_max=surface.SSS_FACTOR_RANGE[1], default=1.0,
        update=update_surface,
    )
    yellowing: FloatProperty(
        name="Yellowing",
        description="How yellow uncoloured plastic has turned with age and light (20 Nature): 0 the cast of a fresh "
                    "part, 1 an old one",
        min=0.0, max=1.0, default=0.0, subtype='FACTOR',
        update=update_yellowing,
    )
    surface_ink_grain: FloatProperty(
        name="Ink Grain",
        description="A fine grain in the surface of a print's ink, as a pad print has it (0: smooth)",
        min=0.0, max=1.0, default=0.0, subtype='FACTOR',
        update=update_surface)
    surface_ink_relief: FloatProperty(
        name="Ink Relief",
        description="How far a print stands out of the surface, as applied ink does: a factor on the ink film's "
                    "height (1: 0.01 mm). The film rises from the outline of the print inwards",
        min=0.0, max=20.0, soft_max=10.0, default=1.0,
        update=update_surface)
    surface_ink_contour: FloatProperty(
        name="Ink Contour",
        description="A bead of ink along the outline of a print, as a stamp leaves it (1: 0.01 mm high)",
        min=0.0, max=10.0, soft_max=3.0, default=0.0,
        update=update_surface)
    surface_ink_wear: FloatProperty(
        name="Ink Wear",
        description="Ink rubbed off a print, in patches and specks, the rims first",
        min=0.0, max=1.0, default=0.0, subtype='FACTOR',
        update=update_surface)
    surface_ink_wear_rims: FloatProperty(
        name="Ink Rim Wear",
        description="How much earlier the rims of a print wear than its faces - thin lines are all rim: 0 they wear "
                    "as the faces do, 1 they go first by far",
        min=0.0, max=1.0, default=0.5, subtype='FACTOR',
        update=update_surface)
    surface_ink_seed: IntProperty(
        name="Ink Seed",
        description="Another pattern of this layer alone (the Seed below moves all layers at once)",
        min=0, max=9999, default=0,
        update=update_surface)
    parts_translate: IntProperty(
        name='Translate',
        description='Move every part a little off its place (100 % = up to 0.4 mm along each axis)',
        min=0, max=100, default=0, subtype='PERCENTAGE',
        update=update_parts)
    parts_rotate: IntProperty(
        name='Rotate',
        description='Turn every part a little (100 % = up to 2 degrees about each axis)',
        min=0, max=100, default=0, subtype='PERCENTAGE',
        update=update_parts)
    parts_mute: BoolProperty(
        name='Mute',
        description='Every part back on its imported place (the settings stay)',
        default=False,
        update=update_parts)
    parts_translate_seed: IntProperty(
        name='Seed',
        description='Another draw of the offsets (0 = the first one)',
        min=0, max=999999, default=0,
        update=update_parts)
    parts_rotate_seed: IntProperty(
        name='Seed',
        description='Another draw of the turns (0 = the first one)',
        min=0, max=999999, default=0,
        update=update_parts)


def _registered():
    """The class is registered: bpy keeps bl_rna in a registered class's own dictionary (bpy_rna.cc
    pyrna_register_class refuses a class that has it: 'already registered as a subclass')."""
    return 'bl_rna' in RbPhysSettings.__dict__


def _pointer():
    return bpy.types.Scene.bl_rna.properties.get(POINTER)


def _ours(prop):
    return prop is not None and _registered() and prop.fixed_type == RbPhysSettings.bl_rna


def register_pointer():
    """The class and bpy.types.Scene.rb_phys of this copy. Nothing to do when both are this copy's; a Scene.rb_phys of
    another class (a copy gone without unregister()) is replaced - assigning a property frees one of the same name
    first (bpy_props.cc, RNA_def_property_free_identifier_deferred_prepare / _finish). Reads no file data."""
    if not _registered():
        bpy.utils.register_class(RbPhysSettings)
    if not _ours(_pointer()):
        bpy.types.Scene.rb_phys = PointerProperty(type=RbPhysSettings, name="Physicalbricks",
                                                  description="The settings of the Physicalbricks library")


def unregister_pointer():
    """Scene.rb_phys when it is this copy's, then the class when it is registered; a pointer of another class stays."""
    if _ours(_pointer()):
        del bpy.types.Scene.rb_phys
    if _registered():
        bpy.utils.unregister_class(RbPhysSettings)


def _cast(prop, value):
    """A value as the property stores it: an ID property of another type is freed on its first read (rna_access.cc
    rna_idproperty_verify_valid, rna_property_rna_or_id_get) - an enum as its item's number. None for a value the
    property cannot hold: an identifier its enum lacks, an array, a type other than enum, int, boolean and float (a
    host's pointer, collection or string under one of the names), a value that is no number, an infinite or NaN one
    for an int (round() raises OverflowError or ValueError) - from_file skips it."""
    if prop.type == 'ENUM':
        item = prop.enum_items.get(value) if isinstance(value, str) else None
        return None if item is None else item.value
    if prop.type not in ('INT', 'BOOLEAN', 'FLOAT') or getattr(prop, 'array_length', 0):
        return None
    try:
        if prop.type == 'INT':
            return round(value)                        # round() of a float is an int
        if prop.type == 'BOOLEAN':
            return bool(value)
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _node_values():
    """What the file's node data holds of the settings, in mode Physical: the eight values of surface.VALUES from the
    Value nodes of rb_phys_surface_settings, the subsurface method of rb_phys_solid, and from the first afterglow
    emission Glow in the dark (its Strength above 0) - and Glow strength only then (with glow off the emission is 0,
    scene.afterglow_strength). Parts Jitter is not in the node data."""
    values = {}
    group = bpy.data.node_groups.get(surface.SETTINGS_GROUP)
    for prop, name in surface.VALUES.items():
        node = group.nodes.get(name) if group is not None else None
        if node is not None:
            values[prop] = node.outputs[0].default_value
    solid = bpy.data.node_groups.get('rb_phys_solid')
    principled = next((n for n in solid.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'), None) if solid else None
    if principled is not None:
        values['physical_subsurface'] = 'BURLEY' if principled.subsurface_method == 'BURLEY' else 'RANDOM_WALK'
    glow = next((n for m in bpy.data.materials if m.node_tree is not None for n in m.node_tree.nodes
                 if n.bl_idname == 'ShaderNodeEmission' and AFTERGLOW in n), None)
    if glow is not None:
        strength = glow.inputs['Strength'].default_value
        values['glow_in_dark'] = strength > 0
        if strength > 0 and float(glow[AFTERGLOW]) > 0:
            values['glow_strength'] = strength / float(glow[AFTERGLOW])
    return values


def from_file(scene, mode):
    """The scene's settings object in line with the file (registry._load_work, before the upgrade): the mode always,
    written only when the object's material_system reads otherwise (an unrelated file in Mecabricks, whose object
    reads the default Mecabricks, gets no data of the library on its scenes); the node-held values only in mode
    'PHYSICAL' - in mode Mecabricks the groups carry no fake user (groups.load_groups) and Blender drops a group
    without users when it saves, so there they are no source and the stored values stay. No guard on values already
    stored: every write through the properties goes through the groups (apply_surface), so the node data is current,
    also after another host changed the file. Written raw (no update runs), each value cast to its property's type;
    one the property cannot hold (_cast) is skipped, the others still written. What still raises (a host object
    without keys() or bl_rna, an afterglow strength that is no number) registry._load_work catches for this scene
    alone. The object: scene.rb_phys while no host supplies settings_of; a host's own object only when it holds no
    stored value at all and the file is in Physical (maintainer 10.11.2026, question 9) - one with a stored value is
    that host's own state. When Yellowing is read from a file in Physical into scene.rb_phys, the scene gets
    surface.YELLOWING_SET: the file's value is its state, and the button's switch gives no record default over it.
    Into a host's object only when the value is not 0: a host's own import hook gives the record default to a scene
    without the flag (Renderbricks Dev: surface.yellowing_default from hooks.AFTER_IMPORT), and a 0 read from the file
    is no choice of the user's - with the flag, a later import into that scene would start at 0 where the host gave
    the default before (run 158, task 5, ruling R5). Returns whether anything was written (nothing when the object
    already reads the file's mode and the file is in Mecabricks); nothing below Blender 5.0."""
    if not AVAILABLE:
        return False
    target = host.settings_of(scene)
    if target is None:
        return False
    own = isinstance(target, RbPhysSettings)
    if not own and (mode != 'PHYSICAL' or target.keys()):
        return False
    values = {} if getattr(target, 'material_system', None) == mode else {'material_system': mode}
    if mode == 'PHYSICAL':
        values.update(_node_values())
    props = target.bl_rna.properties
    written = False
    for name, value in values.items():
        cast = _cast(props[name], value) if name in props else None
        if cast is not None:
            target[name] = cast
            written = True
            if name == 'yellowing' and (own or target[name] != 0):
                scene[surface.YELLOWING_SET] = True
    return written
