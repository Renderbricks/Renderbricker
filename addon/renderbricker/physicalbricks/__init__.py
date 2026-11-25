# SPDX-License-Identifier: GPL-3.0-or-later
"""Physicalbricks: physically based LEGO® materials for Mecabricks models in Blender - a library, not an add-on.

An add-on carries its own copy of this package as a sub-package (Renderbricks Dev: `mecabricks advanced/physicalbricks`)
and fills the hooks of host.py in its register(). Every import inside stays relative, so several copies of different
versions can be loaded at once.

The physical network of a material: physically based base materials beside the Mecabricks shader tree. The Mecabricks
tree of a material stays as it is and only supplies data: scale, the bevel normal, colour masks and decoration (through
its Mix Shader group) and the colour id of each Base Material node. Beside it, in one frame, the network is built: per
colour the record's colour (data/materials.json, converted into the working space) and the class group of
data/physical.blend (CLASS_GROUPS), a second instance of the material's Mix Shader group (same masks and decoration
slot) and of its Eevee Shader group. Switching relinks the material outputs; back to Mecabricks the network is deleted
and the two output links restored, so the Mecabricks tree is bit-identical. Blender 5.0+.

    host.py       what the carrying add-on tells the library (settings, parts, extra branches)
    jitter.py     Parts Jitter: every part a little moved and turned
    colour.py     colours into the file's working colour space
    node_size.py  where a node and its sockets are drawn (height, socket points, box)
    constants.py  names, tables and markers shared by the modules
    groups.py     the class groups of physical.blend, the in-place swap of the first version
    network.py    building and removing the network of one material
    order.py      the order of a tree: a node's column and its row (pure, no bpy; the network and the groups)
    layout.py     placing the network's nodes by the order: one outer frame, inside it a numbered frame per step (its
                  title in capitals, then its note), on Blender's grid of 20
    scene.py      scene settings that follow the material system (subsurface, Cycles bounces)
    switch.py     switching every material of the file; the import and file-open hooks
    records.py    the colour records (data/materials.json)
    readers.py    what the network reads from a Mecabricks material's tree, one reader per importer (Dev, Lite,
                  Advanced)
    lite_trees.py what Nicolas' Lite lacks for the network, made at run time from Lite's own trees in the file
    soft_alpha.py a print's mask softened: a copy of the decoration tree with the output Soft Alpha
    surface.py    the panel's surface values in the group rb_phys_surface_settings
    registry.py   several loaded copies: exactly one acts (the highest VERSION, REVISION) - an add-on's register() ends
                  with registry.register(name), its unregister() calls registry.unregister()
    settings.py   scene.rb_phys, the settings of a host without a panel of its own; the acting copy registers it and
                  brings it in line with the file when a file opens

VERSION is the material set's number, the one users see; REVISION (a file beside it, one integer) is the library's
internal revision, raised with every hand-out of library code, also when VERSION stays (maintainer 10.11.2026) -
counted by the build since 15.11.2026 (REVISIONS.tsv beside the package); VERSION equals the website's number.

Physical materials, their records and measuring method: Prof. Michael Klein, Renderbricks®, developed with Claude Code.
Spec: Renderbricks R&D, docs/specs/2026-11-08-physicalbricks-library-design.md."""
import os

from . import host, jitter, records, registry, settings
from .constants import (
    AVAILABLE,
    BOUNCES,
    BOUNCES_BEFORE,
    CLAMP_BEFORE,
    CLASS_GROUPS,
    DISPERSION_MARK,
    EEVEE_PARAMS,
    EFFECT_INPUTS,
    EFFECTS,
    FLAKE_DEFAULTS,
    FLAKE_INPUTS,
    FRAME_LABEL,
    GLASS,
    IRIDESCENCE_INPUTS,
    SURFACE_FILM_INPUTS,
    LIBRARY,
    MARK,
    MIN_BOUNCES,
    MIN_CLAMP_INDIRECT,
    NET,
    OWN_RECORD,
    PART_BUMP,
    PARTICLE_DEFAULTS,
    PARTICLE_INPUTS,
    PHYS_VERSION,
    REFRACTION,
    RT_BEFORE,
    SAVED,
    SOLID_RW,
    TYPES,
    VIEWPORT,
)
from .groups import (
    base_nodes,
    cycles_output,
    groups_current,
    kind_of,
    load_groups,
    plain,
    solid_random_walk_group,
    swap_tree,
    wire_dispersion,
)
from .host import AFTER_NETWORK
from .layout import layout, network_columns, place
from .network import (
    build_network,
    part_bump_tree,
    remove_network,
    revert_v1,
)
from .readers import base_material_nodes, colour_id_of, find, output
from .scene import (
    AFTERGLOW,
    afterglow_strength,
    apply_afterglow,
    apply_cycles_bounces,
    forget_eevee_raytracing,
    set_subsurface_method,
)
from .surface import (
    apply_eevee_glass,
    apply_surface,
    built_with_surface,
    surface_active,
    yellowing_default,
    yellowing_viewport,
)
from .switch import after_import, set_material_system, upgrade_on_load

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), encoding="utf-8") as _handle:
    VERSION = _handle.read().strip()
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "REVISION"), encoding="utf-8") as _handle:
    REVISION = int(_handle.read().strip())

__all__ = [
    "AFTERGLOW",
    "AFTER_NETWORK",
    "AVAILABLE",
    "BOUNCES",
    "BOUNCES_BEFORE",
    "CLAMP_BEFORE",
    "CLASS_GROUPS",
    "DISPERSION_MARK",
    "EEVEE_PARAMS",
    "EFFECTS",
    "EFFECT_INPUTS",
    "FLAKE_DEFAULTS",
    "FLAKE_INPUTS",
    "FRAME_LABEL",
    "GLASS",
    "IRIDESCENCE_INPUTS",
    "SURFACE_FILM_INPUTS",
    "LIBRARY",
    "MARK",
    "MIN_BOUNCES",
    "MIN_CLAMP_INDIRECT",
    "NET",
    "OWN_RECORD",
    "PARTICLE_DEFAULTS",
    "PARTICLE_INPUTS",
    "PART_BUMP",
    "PHYS_VERSION",
    "REFRACTION",
    "REVISION",
    "RT_BEFORE",
    "SAVED",
    "SOLID_RW",
    "TYPES",
    "VERSION",
    "VIEWPORT",
    "after_import",
    "afterglow_strength",
    "apply_afterglow",
    "apply_cycles_bounces",
    "apply_eevee_glass",
    "apply_surface",
    "base_material_nodes",
    "base_nodes",
    "build_network",
    "built_with_surface",
    "colour_id_of",
    "cycles_output",
    "find",
    "forget_eevee_raytracing",
    "groups_current",
    "host",
    "jitter",
    "kind_of",
    "layout",
    "load_groups",
    "network_columns",
    "output",
    "part_bump_tree",
    "place",
    "plain",
    "records",
    "registry",
    "remove_network",
    "revert_v1",
    "set_material_system",
    "set_subsurface_method",
    "settings",
    "solid_random_walk_group",
    "surface_active",
    "swap_tree",
    "upgrade_on_load",
    "wire_dispersion",
    "yellowing_default",
    "yellowing_viewport",
]
