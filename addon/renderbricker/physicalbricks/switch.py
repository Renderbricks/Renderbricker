# SPDX-License-Identifier: GPL-3.0-or-later
"""Switching every Mecabricks material of the file between Mecabricks and Physical,
after imports and when a file is opened.

Part of Physicalbricks (see __init__.py)."""

import bpy

from . import host
from .constants import AVAILABLE, BOUNCES, BOUNCES_BEFORE, CLAMP_BEFORE, NET
from .groups import groups_current, load_groups, rename_old_prefix
from .layout import NOTE, current
from .network import build_network, remove_network, revert_v1
from .readers import read
from .scene import apply_cycles_bounces, forget_eevee_raytracing, set_subsurface_method
from .surface import (
    apply_surface,
    set_built_with_surface,
    surface_active,
    yellowing_default,
    yellowing_viewport,
)


def understood(material):
    """A Mecabricks material one of the readers knows (readers.read; the trees of Renderbricks Dev, and with plan
    part 3 those of Nicolas' Advanced and Lite)."""
    if material.node_tree is None or not material.name.startswith('mb:'):
        return False
    return read(material) is not None


def has_import():
    """The file holds a Mecabricks import the library understands (any understood material)."""
    return any(understood(m) for m in bpy.data.materials)


def _holds_network(material):
    return (material.name.startswith('mb:') and material.node_tree is not None
            and any(n.get(NET) for n in material.node_tree.nodes))


def current_mode():
    """'PHYSICAL' when a material named mb:... holds a node marked NET, else 'MECABRICKS': the file decides, not a
    setting. Stops at the first hit and calls no reader; in mode Mecabricks it looks at every node of every such
    material - for the work on load and for tests, not for a panel's draw()."""
    return 'PHYSICAL' if any(_holds_network(m) for m in bpy.data.materials) else 'MECABRICKS'


def layouts_current():
    """Every material that holds a network carries the current layout (layout.current: layout 3, the order of part
    4c - texts, widths, hidden inputs and the step frames, written only when a network is built)."""
    return all(current(m.node_tree) for m in bpy.data.materials if _holds_network(m))


def switch_to(mode):
    """The call a button makes (through registry.switch): mode 'PHYSICAL' or 'MECABRICKS' for the file. Sets
    material_system of the context scene's settings object when it has one - its update switches, and Blender runs
    the update also when the value stays the same (bpy_rna.cc pyrna_py_to_prop: RNA_property_update after every set)
    - else set_material_system(mode). After a switch to Physical the slider Yellowing goes to the record default
    once per scene, Nicolas' names read too (surface.yellowing_default nicolas=True: a model switched through this
    button looks as after Dev's import; maintainer 10.11.2026, question 8) - here, not in set_material_system, so
    Dev's own path stays as it is. A scene whose Yellowing holds a value of its own keeps it (YELLOWING_SET).
    Returns (materials that hold a network afterwards, scene['rb_phys_skipped']).
    Part of the frozen cross-copy contract (registry.py): another copy may call it."""
    if not AVAILABLE:
        return 0, 0
    scene = bpy.context.scene
    settings = host.settings_of(scene)
    if settings is not None and hasattr(settings, 'material_system'):
        settings.material_system = mode
    else:
        set_material_system(mode)
    if mode == 'PHYSICAL':
        yellowing_default(scene, nicolas=True)
    return sum(1 for m in bpy.data.materials if _holds_network(m)), scene.get('rb_phys_skipped', 0)


@bpy.app.handlers.persistent
def upgrade_on_load(_dummy=None):
    """A file saved in mode Physical with older physical groups (e.g. 2.1.17.44, v8) gets the current network when it
    opens: otherwise classes added since kept the Mecabricks base output, with its wear,
    until the user switched modes by hand. And the leftovers of the Eevee raytracing switch go (2.1.17.46-.64).
    A network of an older layout (part 4: no LAYOUT on its outer frame; part 4b: layout 2, with its taps and trace
    reroutes) is rebuilt the same way, once: layout 3, the order of part 4c, with its labels, widths and hidden
    inputs, is written only when a network is built.
    First the old prefix mb_phys_* of groups and keys becomes rb_phys_* - in every mode: a file in mode Mecabricks
    keeps on its nodes what the way back to Physical needs (SAVED). Below Blender 5.0 nothing switches: the 5.x
    groups of physical.blend do not load there (constants.AVAILABLE)."""
    rename_old_prefix()
    forget_eevee_raytracing()
    if not AVAILABLE:
        return
    if not any(getattr(host.settings_of(s), 'material_system', '') == 'PHYSICAL' for s in bpy.data.scenes):
        return
    if not has_import() or (groups_current() and layouts_current()):
        return
    set_material_system('PHYSICAL')
    move_fixed_glow()
    for scene in bpy.data.scenes:                  # a file from before the slider Yellowing (group version 38)
        yellowing_default(scene)

def move_fixed_glow():
    """Files until 2.1.17.67: a fluorescent colour carried an Emission of fixed strength in its volume
    ('Physical Glow'), which shone without light. The networks of mb: materials are rebuilt when such a file opens;
    in any other material that still holds one (a copy under another name), its colour and strength move into the
    class group's glow inputs and the emission goes - the fluorescence follows the light there too. A material
    whose volume comes from a group without those inputs (an own copy of an old class group) is left as it is."""
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None:
            continue
        adds = [n for n in tree.nodes if n.bl_idname == 'ShaderNodeAddShader' and n.label == 'Physical Volume + Glow']
        for add in adds:
            sources = [link.from_socket for socket in add.inputs for link in socket.links]
            emit = next((s.node for s in sources if s.node.bl_idname == 'ShaderNodeEmission'), None)
            volume = next((s for s in sources if s.node.type == 'GROUP' and 'Glow Strength' in s.node.inputs), None)
            if emit is None or volume is None:
                continue
            volume.node.inputs['Glow Color'].default_value = emit.inputs['Color'].default_value
            volume.node.inputs['Glow Strength'].default_value = emit.inputs['Strength'].default_value
            for target in [link.to_socket for link in add.outputs[0].links]:
                tree.links.new(volume, target)
            tree.nodes.remove(add)
            tree.nodes.remove(emit)

def set_material_system(mode, surface=None, settings=None):
    """mode 'PHYSICAL' or 'MECABRICKS' for every Mecabricks material of the file; returns (built, skipped).
    Physical always rebuilds the networks: recoloured copies and second imports get fresh values.
    surface: build the networks with the surface node (None: as the settings say); settings: the scene's settings
    (host.settings_of) whose surface values go into the groups (None: the context scene's)."""
    physical = mode == 'PHYSICAL'
    if not has_import():
        # no import yet: nothing to switch. Loading physical.blend now would bring its own mb_base_* first and the
        # import's node library would arrive as .001 copies; finish_import applies the mode after the import
        return 0, 0
    if physical and not load_groups():
        return 0, 0
    if physical:                                       # the panel's subsurface choice (freshly appended groups: Burley)
        settings = host.settings_of(bpy.context.scene)
        set_subsurface_method(getattr(settings, 'physical_subsurface', 'BURLEY'))
    # the networks carry the surface node while a layer slider is above 0; the file remembers how they were built
    with_surface = physical and (surface_active(settings) if surface is None else bool(surface))
    set_built_with_surface(with_surface)
    built = skipped = 0
    surfaced = False
    for material in bpy.data.materials:
        if (not material.name.startswith('mb:') or material.name == 'mb:nodes' or material.node_tree is None
                or material.name.startswith('mb:dust')):
            continue
        revert_v1(material.node_tree)
        remove_network(material)
        if not physical:
            continue
        # the hosts' own nodes go in before the layout, which places them in their steps too (layout.py)
        if build_network(material, with_surface=with_surface, after=host.AFTER_NETWORK):
            built += 1
            surfaced = surfaced or (with_surface and any(n.label == 'Physical Surface'
                                                         for n in material.node_tree.nodes))
        else:
            skipped += 1
    # the step frames' notes are texts with a fake user (text.cc:289-292): those no frame uses any more go
    for text in [t for t in bpy.data.texts if t.name.startswith(NOTE) and t.users == int(t.use_fake_user)]:
        bpy.data.texts.remove(text)
    if with_surface and built and not surfaced:
        # the host built no surface (Dev's layer file missing - a packaging error, final review of plan 2): the file
        # must not remember the networks as built with it, or the next slider move would not rebuild them
        set_built_with_surface(False)
        print("Physicalbricks: the surface layers could not be loaded - the networks are built without them")
    if physical:                                       # freshly loaded groups stand at 0: the panel's values go in
        apply_surface(settings)
        yellowing_viewport()                           # the Solid view colour at the slider's value (group v38)
    bpy.context.scene['rb_phys_skipped'] = skipped
    apply_cycles_bounces(physical)
    return built, skipped

def _older_models(scene, state):
    """Whether the scene already holds a model of an earlier import (a mesh outside this import's collection with an
    mb: material) - an older file, in Mecabricks mode unless someone switched it. The import's objects are taken
    once from its collection: Object.users_collection tests every collection of the file per object
    (_bpy_types.py:279-295), quadratic in the parts (speed profile run 261115: 0.21 s on 2710 parts)."""
    new = state.get('collection')
    ours = set(new.objects) if new is not None else set()
    for obj in scene.objects:
        if obj.type != 'MESH' or obj in ours:
            continue
        if any(s.material and s.material.name.startswith('mb:') for s in obj.material_slots):
            return True
    return False


def after_import(scene, state):
    """Hook (hooks.AFTER_IMPORT): the new materials physical when the file is in that mode; returns the seconds.

    Physicalbricks is the default of an import (user 31.10.2026: „Physicalbricks muss absofort Standard für den Import
    sein.“): a scene where no material system was ever chosen (no mb_switch_to) and without an older model switches
    to Physical here, through the panel's switch (it converts the file and remembers the choice). A chosen Mecabricks
    stays, and so does an older file that holds Mecabricks models. The subsurface stays Burley unless the import's
    Studs for Random Walk asks for it (knob_cut.choose_subsurface).

    An import leaves the scene's Cycles bounces as they are: the importer's render settings step comes after this hook
    and sets them for a scene it sets up (camera and sky); a scene of the user's own (own camera or world, Camera and
    Sky off) keeps its settings untouched (run52 render settings). Switching in the panel raises them as before."""
    import time
    if not AVAILABLE:
        return None
    start = time.perf_counter()
    cycles = getattr(scene, 'cycles', None)
    bounces = [getattr(cycles, name) for name in BOUNCES] if cycles is not None else None
    clamp = cycles.sample_clamp_indirect if cycles is not None else None
    had_before = BOUNCES_BEFORE in scene
    had_clamp = CLAMP_BEFORE in scene
    settings = host.settings_of(scene)
    if settings.material_system != 'PHYSICAL':
        if 'mb_switch_to' in scene or _older_models(scene, state):
            return None
        settings.material_system = 'PHYSICAL'                   # the update switches every mb: material of the file
    else:
        set_material_system('PHYSICAL')
    if bounces is not None:                                    # the import changes no render setting of its own
        for name, value in zip(BOUNCES, bounces, strict=True):
            setattr(cycles, name, value)
        if not had_before:
            scene.pop(BOUNCES_BEFORE, None)
    if clamp is not None:                                      # Clamp Indirect alike (the render settings set 50)
        cycles.sample_clamp_indirect = clamp
        if not had_clamp:
            scene.pop(CLAMP_BEFORE, None)
    return time.perf_counter() - start
