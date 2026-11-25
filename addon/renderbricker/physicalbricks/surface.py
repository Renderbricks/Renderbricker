# SPDX-License-Identifier: GPL-3.0-or-later
"""The panel's surface values in the physical groups: one group, rb_phys_surface_settings, holds them as Value nodes,
and every material's surface group reads it - a slider is one write for the whole file.

Part of Physicalbricks (see __init__.py)."""
import bpy

from . import host

SETTINGS_GROUP = 'rb_phys_surface_settings'

# property of the scene's settings (host.settings_of) -> Value node of the group: the print's ink (rb_phys_decoration
# reads them), Yellowing and the SSS Factor (group version 45: rb_phys_solid and rb_phys_pearl multiply their subsurface
# depth by it). The carrying add-on adds its own values (host.SETTINGS_VALUES: Dev's surface layers).
VALUES = {'surface_ink_relief': 'Ink Relief', 'surface_ink_grain': 'Ink Grain', 'surface_ink_contour': 'Ink Contour',
          'surface_ink_wear': 'Ink Wear', 'surface_ink_wear_rims': 'Ink Rim Wear', 'surface_ink_seed': 'Ink Seed',
          'yellowing': 'Yellowing', 'sss_factor': 'SSS Factor'}

# a value a host's settings object does not have: its rest value instead of 0 (a host without the SSS factor -
# Renderbricks Dev until it gets the slider - keeps the records' depths, never 0)
MISSING = {'sss_factor': 1.0}

# the SSS factor's range (maintainer 16.11.2026: „Der SSS Faktor darf nicht übertrieben werden. Vermutlich ist eine
# Verdoppelung ausreichend.“): RbPhysSettings.sss_factor's soft limits, which a host's slider takes over
SSS_FACTOR_RANGE = (1.0, 2.0)

# The networks belong to the file, not to a scene: whether they were built with the surface node is kept on the
# library's own settings group (SETTINGS_GROUP), which every file with a physical network has. Until library 1.3.1
# (Dev 2.1.17.88) it sat on the importer's node-library material: taken over once when read or written.
ACTIVE = 'rb_phys_surface_active'
OLD_HOLDER = 'mb:nodes'
OLD_ACTIVE = 'mb_surface_active'


def surface_active(settings=None):
    """The networks carry a surface branch (the carrying add-on decides: host.surface_active; Dev: a layer slider is
    above 0)."""
    if settings is None:
        settings = host.settings_of(bpy.context.scene)
    return bool(host.surface_active(settings))


def _take_over_old_flag(group):
    """A file of Dev 2.1.17.88 or older: its flag moves from the node-library material onto the settings group."""
    holder = bpy.data.materials.get(OLD_HOLDER)
    if holder is None or OLD_ACTIVE not in holder or group is None or group.library is not None:
        return
    group[ACTIVE] = bool(holder[OLD_ACTIVE])
    if holder.library is None:
        del holder[OLD_ACTIVE]


def built_with_surface():
    """The file's networks carry the surface node."""
    group = bpy.data.node_groups.get(SETTINGS_GROUP)
    if group is None:
        holder = bpy.data.materials.get(OLD_HOLDER)        # an old file whose groups are not loaded yet
        return bool(holder.get(OLD_ACTIVE, False)) if holder is not None else False
    _take_over_old_flag(group)
    return bool(group.get(ACTIVE, False))


def set_built_with_surface(value):
    group = bpy.data.node_groups.get(SETTINGS_GROUP)
    if group is not None and group.library is None:
        _take_over_old_flag(group)
        group[ACTIVE] = bool(value)


def apply_surface(settings=None):
    """Write the scene's surface values into the group; returns how many values were written (0: all were there, or
    the file has no such group). A value at rest is not written again: every write makes Blender scan all node trees
    of the file. Compared as the socket stores it (float32)."""
    group = bpy.data.node_groups.get(SETTINGS_GROUP)
    if group is None:
        return 0
    if settings is None:
        settings = host.settings_of(bpy.context.scene)
    if settings is None:
        return 0
    written = apply_eevee_glass()
    for prop, name in {**VALUES, **host.SETTINGS_VALUES}.items():
        node = group.nodes.get(name)
        if node is None:
            continue
        value = float(getattr(settings, prop, MISSING.get(prop, 0.0)))
        if abs(node.outputs[0].default_value - value) >= 1e-7:
            node.outputs[0].default_value = value
            written += 1
    return written


EEVEE_GLASS_VALUES = ('Eevee Thin', 'Eevee Caustics', 'Eevee Caustics Strength')


def apply_eevee_glass():
    """The carrying add-on's Eevee glass settings (host.eevee_glass) into the settings group's Eevee values (group
    version 40, rb_phys_eevee reads them); returns how many values were written. Called when the networks are
    built and when the panel changes them."""
    group = bpy.data.node_groups.get(SETTINGS_GROUP)
    wanted = host.eevee_glass()
    if group is None or wanted is None:
        return 0
    thin, caustics, strength = wanted
    written = 0
    for name, value in zip(EEVEE_GLASS_VALUES, (1.0 if thin else 0.0, 1.0 if caustics else 0.0, float(strength)),
                           strict=True):
        node = group.nodes.get(name)
        if node is not None and abs(node.outputs[0].default_value - value) >= 1e-7:
            node.outputs[0].default_value = value
            written += 1
    return written


# on the scene: Yellowing holds a value of its own - set to a record's default once, moved by the user on the library's
# slider (settings.update_yellowing), or read from a file in Physical (settings.from_file; into a host's own settings
# object only a value other than 0); no default goes over it
YELLOWING_SET = 'rb_phys_yellowing_set'


def _colour_ids(name, nicolas):
    """The colour ids yellowing_default looks at in a material name: Renderbricks Dev's mb:<id>:... as before (the
    first id of a name with one); with nicolas also Nicolas' mb:<scope>:<part>:<id,id...> (readers.NICOLAS_NAME, a
    Blender suffix .NNN dropped), every id in base order as the readers take them. A Dev name never matches Nicolas'
    pattern: its scope does not start with a digit."""
    import re

    from .readers import NICOLAS_NAME, SUFFIX
    match = re.match(r'^mb:(\d+):', name)
    if match:
        return [int(match.group(1))]
    match = NICOLAS_NAME.match(SUFFIX.sub('', name)) if nicolas else None
    return [int(x) for x in match.group(3).split(',')] if match else []


def yellowing_default(scene, state=None, *, nicolas=False):
    """Hook (hooks.AFTER_IMPORT), on load (switch.upgrade_on_load) and after the button's switch to Physical
    (switch.switch_to): the slider Yellowing (group version 38) at the default of the first record in the file that
    can yellow (20 Nature, materials version 16: 0.38, b* +4 in ACES 2.0), once per scene - a value the scene holds
    of its own (YELLOWING_SET) stays. Dev's names; Nicolas' (Lite, Advanced) only with nicolas - the button's call
    (maintainer 10.11.2026, question 8), so Dev's import hook and the upgrade read as before. Returns nothing: the
    importer counts what its hooks return as seconds (importer.py: mb_convert_seconds)."""
    from . import records
    settings = host.settings_of(scene)
    if settings is None or scene.get(YELLOWING_SET):
        return
    for material in bpy.data.materials:
        for colour_id in _colour_ids(material.name, nicolas):
            record = records.of(material, colour_id)
            if record and 'yellowing' in record:
                scene[YELLOWING_SET] = True
                settings.yellowing = float(record['yellowing']['default'])
                apply_surface(settings)
                yellowing_viewport()
                return


def yellowing_viewport():
    """The Solid view colour of every network with the blend Yellowing follows the slider: the transmittance (A) blended
    with the yellowing end (B) at the settings group's value - as the network does (network.build_network)."""
    group = bpy.data.node_groups.get(SETTINGS_GROUP)
    node = group.nodes.get('Yellowing') if group else None
    if node is None:
        return
    t = node.outputs[0].default_value

    def numbers(combine):
        return [s.links[0].from_node.outputs[0].default_value if s.is_linked else s.default_value
                for s in combine.inputs[:3]]

    for material in bpy.data.materials:
        tree = material.node_tree
        blend = next((n for n in tree.nodes if n.label == 'Yellowing #1'), None) if tree else None
        if blend is None or not (blend.inputs[6].is_linked and blend.inputs[7].is_linked):
            continue
        a, b = numbers(blend.inputs[6].links[0].from_node), numbers(blend.inputs[7].links[0].from_node)
        seen = [min(x + (y - x) * t, 1.0) for x, y in zip(a, b, strict=True)]
        material.diffuse_color = [*seen, material.diffuse_color[3]]
