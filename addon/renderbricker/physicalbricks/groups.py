# SPDX-License-Identifier: GPL-3.0-or-later
"""The class groups of physical.blend: loading them into the file, and the in-place swap
of files of the first physical version.

Part of Physicalbricks (see __init__.py)."""
import os
import re

import bpy

from . import host
from .constants import (
    AVAILABLE,
    CLASS_GROUPS,
    DISPERSION_MARK,
    EEVEE_GROUPS,
    GLITTER_OPAQUE,
    LIBRARY,
    MARK,
    OLD_PREFIX,
    PHYS_VERSION,
    PREFIX,
    SAVED,
    SOLID_RW,
)
from .scene import solid_rw_method

DISPERSION_ABBE = 'Transmission Dispersion Abbe Number'    # Principled BSDF, Blender 5.3+
DISPERSION_SCALE = 'Transmission Dispersion Scale'
NO_DISPERSION = 'RB_PHYS_NO_DISPERSION'   # environment, run 144's refactor gate only: wire, but Dispersion Scale 0


def wire_dispersion(tree=None):
    """Dispersion of the glass (group version 37): built with 5.3 the link is there already; Blender 5.0-5.2
    (physical.blend opens there too) have no dispersion sockets. Where this Blender has them, the glass marked
    DISPERSION_MARK gets the group input 'Abbe Number' on 'Transmission Dispersion Abbe Number' (unless linked)
    and 'Transmission Dispersion Scale' 1 (Cauchy IOR per wavelength from the Abbe number, bsdf_microfacet.h
    bsdf_glass_ior; 0 = none). True when wired, False where there is nothing to wire (older Blender, no marked
    glass). tree: rb_phys_transparent of the file by default."""
    tree =tree or bpy.data.node_groups.get(CLASS_GROUPS['transparent'])
    glass = [n for n in tree.nodes if n.get(DISPERSION_MARK)] if tree is not None else []
    if not glass or DISPERSION_ABBE not in glass[0].inputs:
        return False
    feeds = [n for n in tree.nodes if n.bl_idname == 'NodeGroupInput' and 'Abbe Number' in n.outputs]
    if not feeds:
        return False
    feed = next((n for n in feeds if not n.outputs['Abbe Number'].hide), feeds[0])
    feed.outputs['Abbe Number'].hide = False
    scale = 0.0 if os.environ.get(NO_DISPERSION) else 1.0
    for node in glass:
        if not node.inputs[DISPERSION_ABBE].is_linked:
            tree.links.new(feed.outputs['Abbe Number'], node.inputs[DISPERSION_ABBE])
        node.inputs[DISPERSION_SCALE].default_value = scale
    return True


def rename_old_prefix():
    """A file of group version 37 or older: its physical groups and the ID properties the add-on puts on scenes,
    objects, materials, groups and nodes carry mb_phys_* (constants.OLD_PREFIX) - renamed to rb_phys_*. Where the
    file already has the new group too, the old one's users move to it by socket name (remap_by_name). Returns how
    many names and keys were renamed. Linked data (from another file) cannot be edited here and is left as it is."""
    renamed = 0
    for old in [g for g in bpy.data.node_groups if g.name.startswith(OLD_PREFIX) and g.library is None]:
        name = PREFIX + old.name[len(OLD_PREFIX):]
        new = bpy.data.node_groups.get(name)
        if new is None:
            old.name = name
        else:
            remap_by_name(old, new)
            bpy.data.node_groups.remove(old)
        renamed += 1
    holders = list(bpy.data.scenes) + list(bpy.data.objects) + list(bpy.data.materials) + list(bpy.data.node_groups)
    for idb in [x for x in holders if x.library is None]:
        tree = idb if isinstance(idb, bpy.types.NodeTree) else getattr(idb, 'node_tree', None)
        for item in [idb] + list(tree.nodes if tree is not None else ()):
            for key in [k for k in item.keys() if k.startswith(OLD_PREFIX)]:
                item[PREFIX + key[len(OLD_PREFIX):]] = item[key]
                del item[key]
                renamed += 1
    return renamed


def load_groups():
    """rb_phys_* in this file at the add-on's version; appended copies of groups the file already has
    (mb_base_solid.001 ...) are mapped onto the file's own and removed. The glass gets its dispersion where this
    Blender has it (wire_dispersion) - also in a file whose groups are current but were saved by an older Blender."""
    rename_old_prefix()
    names = library_groups()
    if groups_current():
        wire_dispersion()
        return True
    if not AVAILABLE or not os.path.isfile(LIBRARY):
        return False
    # older versions make way – the class groups and every shared rb_phys_* sub-group the library brings (glitter
    # layer, flake normal, particle cells, object space): left in place, the appended class groups would be remapped
    # onto the file's stale sub-groups
    with bpy.data.libraries.load(LIBRARY, link=False) as (data_from, data_to):
        shipped = [n for n in data_from.node_groups if n.startswith('rb_phys_')]
    replaced = sorted(set(names) | set(shipped))
    for n in replaced:
        old = bpy.data.node_groups.get(n)
        if old is not None:
            old.name = n + ' (old)'
    before = set(bpy.data.node_groups)
    with bpy.data.libraries.load(LIBRARY, link=False) as (data_from, data_to):
        data_to.node_groups = [n for n in names if n in data_from.node_groups]
    for group in [g for g in bpy.data.node_groups if g not in before]:
        match = re.match(r'^(.*)\.\d{3}$', group.name)
        own = bpy.data.node_groups.get(match.group(1)) if match else None
        if own is not None and own not in [g for g in bpy.data.node_groups if g not in before]:
            group.user_remap(own)
            bpy.data.node_groups.remove(group)
    for n in replaced:
        old = bpy.data.node_groups.get(n + ' (old)')
        if old is not None and bpy.data.node_groups.get(n) is not None:
            remap_by_name(old, bpy.data.node_groups[n])
            bpy.data.node_groups.remove(old)
        elif old is not None:                          # not brought along this time: keep the file's own
            old.name = n
    for n in names:
        g = bpy.data.node_groups.get(n)
        if g is not None:
            g.use_fake_user = False
    wire_dispersion()
    return all(bpy.data.node_groups.get(n) is not None for n in names)

def remap_by_name(old, new):
    """Every group node of the file that uses old gets new, its links and values carried by socket name.
    ID.user_remap alone keeps a node's values by socket identifier, and identifiers are numbered in the order the
    inputs were made: when a group's inputs change (speckle, version 17), the values of a node the network builder does
    not rebuild - a material that is no mb: material any more - landed on other inputs."""
    trees = [m.node_tree for m in bpy.data.materials if m.node_tree is not None]
    trees += [g for g in bpy.data.node_groups if g != old and g != new]
    for tree in trees:
        for node in [x for x in tree.nodes if x.type == 'GROUP' and x.node_tree == old]:
            swap_tree(tree, node, new)
    old.user_remap(new)                                # whatever else points at it

def plain(value):
    """A socket default as something an ID property can hold."""
    return tuple(value) if hasattr(value, '__len__') else float(value)

def swap_tree(tree, node, group):
    """Point node at group. Changing a group node's tree rebuilds its sockets by identifier, which differ between
    the base and the phys groups, so links and typed values (e.g. a neon colour's Diffuse Fac) are carried over
    by socket name; what the new tree has no socket for (an older library's input) is kept on the node and put
    back when a tree with that socket returns."""
    incoming = [(l.from_node.name, l.from_socket.identifier, l.to_socket.name) for l in tree.links if l.to_node == node]
    outgoing = [(l.from_socket.name, l.to_socket) for l in tree.links if l.from_node == node]
    values = {s.name: plain(s.default_value) for s in node.inputs
              if not s.is_linked and hasattr(s, 'default_value') and s.type != 'SHADER'}
    saved = node.get(SAVED, {})
    kept_links = [list(x) for x in saved.get('links', [])] + [list(x) for x in incoming]
    kept_values = dict(saved.get('values', {}))
    kept_values.update(values)
    for link in [l for l in tree.links if l.to_node == node or l.from_node == node]:
        tree.links.remove(link)
    node.node_tree = group
    left_links, left_values = [], {}
    for from_name, from_id, to_name in kept_links:
        source = tree.nodes.get(from_name)
        socket = next((x for x in source.outputs if x.identifier == from_id), None) if source else None
        if socket is not None and to_name in node.inputs and not node.inputs[to_name].is_linked:
            tree.links.new(socket, node.inputs[to_name])
        elif socket is not None and to_name not in node.inputs:
            left_links.append([from_name, from_id, to_name])
    # an input the old tree did not have holds the value of the old socket with the same identifier (identifiers are
    # numbered in the order the inputs were made): it gets the new group's own default instead
    interface = getattr(group, 'interface', None)
    for item in (interface.items_tree if interface else ()):
        if item.item_type != 'SOCKET' or item.in_out != 'INPUT' or item.name in kept_values:
            continue
        target = node.inputs.get(item.name)
        if (target is not None and not target.is_linked and hasattr(target, 'default_value')
                and hasattr(item, 'default_value') and target.type != 'SHADER'):
            target.default_value = item.default_value
    for name, value in kept_values.items():
        target = node.inputs.get(name)
        if target is None:
            left_values[name] = value
        elif not target.is_linked and hasattr(target, 'default_value'):
            target.default_value = value
    for name, to_socket in outgoing:
        if name in node.outputs:
            tree.links.new(node.outputs[name], to_socket)
    if left_links or left_values:
        node[SAVED] = {'links': left_links, 'values': left_values}
    elif SAVED in node:
        del node[SAVED]

def base_nodes(tree):
    """The base-material group nodes of a tree (mb_base_*, or rb_phys_* of a swapped file)."""
    return [n for n in tree.nodes if n.type == 'GROUP' and n.node_tree is not None
            and n.node_tree.name.startswith(('mb_base_', 'rb_phys_'))]

def kind_of(node):
    """The material type of a base node (solid, transparent ...)."""
    return node.get(MARK) or node.node_tree.name.split('_', 2)[2]

def cycles_output(tree):
    """The material output of a tree that targets Cycles."""
    return next((n for n in tree.nodes if n.bl_idname == 'ShaderNodeOutputMaterial' and n.target == 'CYCLES'), None)

def solid_random_walk_group():
    """The solid group with Random Walk subsurface, for records that need light carried through the material
    (50 Phosphorescent White - the hollow ghost shroud is lit from inside only with Random Walk). A copy of
    rb_phys_solid, made once per file. It follows the panel's subsurface switch (scene.set_subsurface_method): Burley
    with Burley (user 27.10.2026: Random Walk only with the import option Studs for Random Walk), else Cycles' plain
    Random Walk, the method its colours were matched with (run 83, dE 0): Skin, which the panel's Random Walk uses
    for the other solids (SUBSURFACE_METHODS), made the shroud darker and opaque - dE 5.3, black eyes (run 108) - and
    kept the knob-foot rings as plain Random Walk does (run 115: only the import's stud cut removes them)."""
    group = bpy.data.node_groups.get(SOLID_RW)
    base = bpy.data.node_groups.get(CLASS_GROUPS['solid'])
    if group is None or group.get('rb_phys_version', 0) < (base.get('rb_phys_version', 0) if base else 0):
        if base is None:
            return None
        if group is not None:
            group.name = SOLID_RW + '_old'
        group = base.copy()
        group.name = SOLID_RW
    settings = host.settings_of(bpy.context.scene)
    method = solid_rw_method(getattr(settings, 'physical_subsurface', 'BURLEY'))
    for node in group.nodes:
        if node.bl_idname == 'ShaderNodeBsdfPrincipled':
            node.subsurface_method = method
    return group

def groups_current():
    """Every physical group of this file is at the add-on's version."""
    return all((g := bpy.data.node_groups.get(n)) is not None and g.get('rb_phys_version', 0) >= PHYS_VERSION
               for n in library_groups())


def library_groups():
    """The top groups physical.blend ships: the class groups, the opaque glitter, the decoration, the Eevee shader.
    The surface layers (rb_phys_surface and its children) are no longer among them since library part 2 - they are
    the host's (Renderbricks Dev: fx/surface_layers), loaded by it."""
    return sorted(set(CLASS_GROUPS.values())) + [GLITTER_OPAQUE, 'rb_phys_decoration', *EEVEE_GROUPS]
