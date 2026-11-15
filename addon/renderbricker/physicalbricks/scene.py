# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene settings that follow the material system: subsurface method, Cycles bounces.

Part of Physicalbricks (see __init__.py)."""

import bpy

from . import host
from .constants import (
    BOUNCES,
    BOUNCES_BEFORE,
    CLAMP_BEFORE,
    MIN_BOUNCES,
    MIN_CLAMP_INDIRECT,
    RT_BEFORE,
    SOLID_RW,
    SUBSURFACE_METHODS,
)

AFTERGLOW = 'mb_afterglow_strength'   # on an afterglow emission node: its record's strength
# in the scene's settings until 2.1.17.64: the panel switch (forget_eevee_raytracing)
OLD_SWITCH = 'physical_eevee_raytracing'


def afterglow_strength(base):
    """The emission strength of an afterglow: the record's strength x Glow strength while Glow in the dark is on,
    else 0 (the daylight look). The Maya variant uses the same values."""
    settings = host.settings_of(bpy.context.scene)
    if settings is None or not getattr(settings, 'glow_in_dark', False):
        return 0.0
    return float(base) * float(getattr(settings, 'glow_strength', 1.0))

def apply_afterglow():
    """Every afterglow emission of the file follows the scene's Glow in the dark and Glow strength."""
    count = 0
    for material in bpy.data.materials:
        if material.node_tree is None:
            continue
        for node in material.node_tree.nodes:
            if node.bl_idname == 'ShaderNodeEmission' and AFTERGLOW in node:
                value = afterglow_strength(node[AFTERGLOW])
                if abs(node.inputs['Strength'].default_value - value) > 1e-9:
                    node.inputs['Strength'].default_value = value
                count += 1
    return count


def set_subsurface_method(method):
    """'BURLEY' or 'RANDOM_WALK' for the solid plastic of the whole file (one shared group, so one choice). Random
    Walk renders as Cycles' Random Walk (Skin), see SUBSURFACE_METHODS. The copy for the records that ask for Random
    Walk (50, 329 - solid_random_walk_group) follows: Burley with Burley, Cycles' plain Random Walk with Random Walk
    (user 27.10.2026: „Ohne bleiben wir bei Burley.“)."""
    group = bpy.data.node_groups.get('rb_phys_solid')
    if group is None:
        return False
    for name, chosen in (('rb_phys_solid', SUBSURFACE_METHODS.get(method, method)),
                         (SOLID_RW, solid_rw_method(method))):
        for node in (bpy.data.node_groups[name].nodes if name in bpy.data.node_groups else ()):
            if node.bl_idname == 'ShaderNodeBsdfPrincipled' and node.subsurface_method != chosen:
                node.subsurface_method = chosen
    return True


def solid_rw_method(method):
    """The subsurface method of the ghost copy for the panel's choice: plain Random Walk, the method its colours were
    matched with (run 83) - Skin made the shroud opaque and kept the knob-foot rings (runs 108, 115)."""
    return 'BURLEY' if method == 'BURLEY' else 'RANDOM_WALK'

def forget_eevee_raytracing():
    """The material system leaves the scene's Eevee raytracing alone (UPDATES #82, user 10.10.2026): an import
    switches it on with the other EEVEE settings, as Renderbricker's EEVEE button does (stage.eevee_best), and the
    panel switch "Eevee Raytracing" of 2.1.17.46-.64 had no effect beside that. What a file of those versions still
    carries of the switch - its value, and the scene's raytracing from before Physical - is dropped when the file
    opens; the scene's raytracing stays as the file has it."""
    for scene in bpy.data.scenes:
        if RT_BEFORE in scene:
            del scene[RT_BEFORE]
        settings = host.settings_of(scene)
        if settings is not None and OLD_SWITCH in settings.keys():
            del settings[OLD_SWITCH]

def apply_cycles_bounces(physical):
    """Cycles ray depth and indirect clamp of the scene: in Physical every bounce limit at least MIN_BOUNCES (glass:
    internal reflections and the haze of the volume need them - Blender's glossy 4 / volume 0 give dark edges and dark
    studs) and Clamp Indirect at least MIN_CLAMP_INDIRECT unless it is off (dispersion, see constants); back to
    Mecabricks: the scene's own values from before."""
    scene = bpy.context.scene
    cycles = getattr(scene, 'cycles', None)
    if cycles is None:
        return
    if physical:
        if BOUNCES_BEFORE not in scene:
            scene[BOUNCES_BEFORE] = [getattr(cycles, name) for name in BOUNCES]
        for name in BOUNCES:
            if getattr(cycles, name) < MIN_BOUNCES:
                setattr(cycles, name, MIN_BOUNCES)
        if CLAMP_BEFORE not in scene:
            scene[CLAMP_BEFORE] = cycles.sample_clamp_indirect
        if 0.0 < cycles.sample_clamp_indirect < MIN_CLAMP_INDIRECT:
            cycles.sample_clamp_indirect = MIN_CLAMP_INDIRECT
        return
    if BOUNCES_BEFORE in scene:
        for name, value in zip(BOUNCES, scene[BOUNCES_BEFORE], strict=False):
            setattr(cycles, name, int(value))
        del scene[BOUNCES_BEFORE]
    if CLAMP_BEFORE in scene:
        cycles.sample_clamp_indirect = float(scene[CLAMP_BEFORE])
        del scene[CLAMP_BEFORE]
