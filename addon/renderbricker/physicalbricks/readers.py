# SPDX-License-Identifier: GPL-3.0-or-later
"""Readers: what the physical network reads from a Mecabricks material's tree, one reader per importer that built it
(spec 2026-11-08 §2, plan part 3).

    Dev        Renderbricks Dev (two outputs, the Eevee Shader, mb_colour_id on the base nodes or Dev's material names
               mb:<id,id...>:...)
    Advanced   Nicolas' Mecabricks Advanced as he ships it (two outputs, his Eevee Shader, Customize, his names
               mb:<scope>:<part>:<id,id...>)
    Lite       Nicolas' Mecabricks Lite as he ships it (one output for both engines, no Eevee Shader, no Customize, his
               names); the network adds its own outputs and mixes Lite's trees as copies (lite_trees.py)

A reader looks at the tree as the importer left it in the user's file and returns a Reading, or None when the tree is
not one it knows. The network then reads only the Reading. Nicolas' trees are read, never edited.

Part of Physicalbricks (see __init__.py)."""
import re
from dataclasses import dataclass, field

from .constants import NET

DEV_NAME = re.compile(r'^mb:(\d+(?:,\d+)*)(?::|$)')       # Renderbricks Dev: mb:<id,id...>:<names>...
# Nicolas' Lite and Advanced: mb:<scope>:<part>:<id,id...> (PartLoader.get_material_name; scope 'o', 'c' ...)
NICOLAS_NAME = re.compile(r'^mb:([^:\d][^:]*):([^:]+):(\d+(?:,\d+)*)$')
SUFFIX = re.compile(r'\.\d{3,}$')                           # Blender's .001 for a second material of that name


@dataclass
class Reading:
    """What the network reads from one material's tree.

    case            'dev' (later 'advanced', 'lite')
    bases           the Base Material nodes #1, #2 ...
    colour_ids      the colour id of each base (None: not known)
    scale, normal   the Scale value node and the Normal group (its Normal output; Height where the tree has one)
    height          the Normal group's Height output, or None
    mix             the Mix Shader group node
    base_inputs     identifier of the mix input each base's Shader feeds, in base order
    decoration      the Decoration group node, or None
    customize       the Customize group node the network builds on, or None (Dev reads past its Customize)
    eevee           the material's Eevee Shader group node, or None
    eevee_sources   input name of the Eevee shader -> the socket that feeds it in the material's tree
    normal_map      a socket giving the part's Eevee normal map beside eevee_sources, or None
    normal_map_tree a node tree giving it (output 0) when it lives inside the material's Eevee group: the network
                    instances it (Advanced: his part normal maps and Mecabricks' bevel maps), or None
    out_cycles, out_eevee, out_all   the material outputs (targets CYCLES, EEVEE, ALL), or None"""
    case: str
    bases: list
    colour_ids: list
    scale: object
    normal: object
    height: object = None
    mix: object = None
    base_inputs: list = field(default_factory=list)
    decoration: object = None
    customize: object = None
    eevee: object = None
    eevee_sources: dict = field(default_factory=dict)
    normal_map: object = None
    normal_map_tree: object = None
    out_cycles: object = None
    out_eevee: object = None
    out_all: object = None


def find(tree, label):
    """The Mecabricks node of a tree with this label (not one of the network's)."""
    return next((n for n in tree.nodes if n.label == label and not n.get(NET)), None)


def output(tree, target):
    """The material output of a tree for a render target (CYCLES, EEVEE or ALL), not one of the network's."""
    return next((n for n in tree.nodes if n.bl_idname == 'ShaderNodeOutputMaterial' and n.target == target
                 and not n.get(NET)), None)


def base_material_nodes(tree):
    """The Base Material nodes of a tree in their order #1, #2 ..."""
    nodes = [n for n in tree.nodes if n.label.startswith('Base Material #') and not n.get(NET)]
    return sorted(nodes, key=lambda n: int(n.label.split('#')[1]))


def colour_ids_from_name(name):
    """The colour ids in a material name, in base order: Renderbricks Dev's mb:<id,id...>:... or Nicolas'
    mb:<scope>:<part>:<id,id...> (Lite and Advanced), a Blender suffix .NNN dropped; None for any other name - a
    renamed material is skipped and counted, never coloured by a guess (spec §2, plan part 3 task 2)."""
    name = SUFFIX.sub('', name)
    match = DEV_NAME.match(name)
    if match:
        return [int(x) for x in match.group(1).split(',')]
    match = NICOLAS_NAME.match(name)
    if match:
        return [int(x) for x in match.group(3).split(',')]
    return None


def colour_id_of(node, material):
    """The node's colour id (set by Renderbricks Dev's builder from 2.1.17.42 on), else its id in the material name
    (colour_ids_from_name), the n-th id for Base Material #n - else None. The colour is never guessed from a value
    (the library holds no Mecabricks colour table; plan 2026-11-08, part 1, task 2)."""
    if 'mb_colour_id' in node:
        return int(node['mb_colour_id'])
    ids = colour_ids_from_name(material.name)
    if not ids:
        return None
    number = re.search(r'#(\d+)$', node.label)
    index = int(number.group(1)) - 1 if number else 0
    return ids[index] if 0 <= index < len(ids) else None


def _base_inputs(tree, bases, mix):
    """The identifier of the mix input each base's Shader output feeds (None where it feeds none)."""
    out = []
    for base in bases:
        link = next((l for l in tree.links if l.from_node == base and l.to_node == mix
                     and l.from_socket.name == 'Shader'), None)
        out.append(link.to_socket.identifier if link else None)
    return out


def read_dev(material):
    """Renderbricks Dev: both outputs, the Eevee Shader, and mb_colour_id on a base node or Dev's name mb:<ids>:..."""
    tree = material.node_tree
    if tree is None:
        return None
    mix, eevee = find(tree, 'Mix Shader'), find(tree, 'Eevee Shader')
    scale, normal = find(tree, 'Scale'), find(tree, 'Normal')
    out_c, out_e = output(tree, 'CYCLES'), output(tree, 'EEVEE')
    bases = base_material_nodes(tree)
    if None in (mix, eevee, scale, normal, out_c, out_e) or not bases:
        return None
    if not (any('mb_colour_id' in b for b in bases) or DEV_NAME.match(material.name)):
        return None
    return Reading(case='dev', bases=bases, colour_ids=[colour_id_of(b, material) for b in bases],
                   scale=scale, normal=normal, height=normal.outputs.get('Height'), mix=mix,
                   base_inputs=_base_inputs(tree, bases, mix), decoration=find(tree, 'Decoration'),
                   eevee=eevee,
                   eevee_sources={l.to_socket.name: l.from_socket for l in tree.links if l.to_node == eevee},
                   out_cycles=out_c, out_eevee=out_e)


def _eevee_normal_tree(eevee):
    """Advanced: the group inside the material's own Eevee Shader copy that feeds 'Mix Normals' its second input - the
    part's normal maps (seams, moulding) and Mecabricks' bevel maps (MaterialBuilder.build: make_normal(eevee, ...))."""
    tree = eevee.node_tree if eevee is not None else None
    mixer = tree.nodes.get('Mix Normals') if tree is not None else None
    if mixer is None or len(mixer.inputs) < 2 or not mixer.inputs[1].is_linked:
        return None
    source = mixer.inputs[1].links[0].from_node
    if source.bl_idname != 'ShaderNodeGroup' or source.node_tree is None or source.inputs:
        return None                                   # only an input-free group can be instanced as it is
    return source.node_tree


def read_advanced(material):
    """Nicolas' Mecabricks Advanced as shipped: both outputs, his Eevee Shader and Customize, no mb_colour_id, and his
    name mb:<scope>:<part>:<ids> (a Dev file is read by read_dev first)."""
    tree = material.node_tree
    if tree is None or not NICOLAS_NAME.match(SUFFIX.sub('', material.name)):
        return None
    mix, eevee, customize = find(tree, 'Mix Shader'), find(tree, 'Eevee Shader'), find(tree, 'Customize')
    scale, normal = find(tree, 'Scale'), find(tree, 'Normal')
    out_c, out_e = output(tree, 'CYCLES'), output(tree, 'EEVEE')
    bases = base_material_nodes(tree)
    if None in (mix, eevee, customize, scale, normal, out_c, out_e) or not bases:
        return None
    if any('mb_colour_id' in b for b in bases):
        return None
    return Reading(case='advanced', bases=bases, colour_ids=[colour_id_of(b, material) for b in bases],
                   scale=scale, normal=normal, height=normal.outputs.get('Height'), mix=mix,
                   base_inputs=_base_inputs(tree, bases, mix), decoration=find(tree, 'Decoration'),
                   customize=customize, eevee=eevee,
                   eevee_sources={l.to_socket.name: l.from_socket for l in tree.links if l.to_node == eevee},
                   normal_map_tree=_eevee_normal_tree(eevee), out_cycles=out_c, out_eevee=out_e)


def read_lite(material):
    """Nicolas' Mecabricks Lite as shipped: one output (target ALL), no Eevee Shader, no Customize, his name. Lite's
    Normal group has no Height; its seams and moulding marks are roughness layers inside it (MaterialBuilder.
    assemble_normals), read with the normal - Lite has no normal-map textures."""
    tree = material.node_tree
    if tree is None or not NICOLAS_NAME.match(SUFFIX.sub('', material.name)):
        return None
    if find(tree, 'Eevee Shader') is not None or find(tree, 'Customize') is not None:
        return None
    mix, scale, normal = find(tree, 'Mix Shader'), find(tree, 'Scale'), find(tree, 'Normal')
    out_all = output(tree, 'ALL')
    bases = base_material_nodes(tree)
    if None in (mix, scale, normal, out_all) or not bases or any('mb_colour_id' in b for b in bases):
        return None
    return Reading(case='lite', bases=bases, colour_ids=[colour_id_of(b, material) for b in bases],
                   scale=scale, normal=normal, height=normal.outputs.get('Height'), mix=mix,
                   base_inputs=_base_inputs(tree, bases, mix), decoration=find(tree, 'Decoration'), out_all=out_all)


READERS = (read_dev, read_advanced, read_lite)


def read(material):
    """The Reading of the first reader that knows the material's tree, or None."""
    if material is None or material.node_tree is None:
        return None
    for reader in READERS:
        reading = reader(material)
        if reading is not None:
            return reading
    return None
