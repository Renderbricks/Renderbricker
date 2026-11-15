# SPDX-License-Identifier: GPL-3.0-or-later
"""What Nicolas' Lite lacks for the physical network, made at run time from Lite's own trees in the user's file
(plan part 3, task 4). The copies carry our nodes; Lite's trees are not touched and nothing of his is shipped.

    mix_tree(lite_mix)          Lite's mb_mix_shader mixes shaders only (Shader, ..., Dec Shader, Dec Mask). The
                                copy gets Advanced's interface - Shader<n>, Shader Dec., Shader Dec. Mask - and beside
                                every Mix Shader one Mix node per Eevee parameter (EEVEE_PARAMS) driven by the same
                                factor (his colour masks, his print mask): inputs <param><n>, <param> Dec., outputs per
                                parameter. So the network mixes the Eevee values of a multi-colour Lite part as
                                Advanced's tree does
    print_tree(lite_decoration) Lite's Decoration gives Shader, Normal, Alpha, Sticker; the copy adds Color (the print's
                                colour texture), Metallic (decoded from the data texture: red = metallic print, blue =
                                sticker, red or green = metal foil on a sticker) and Height (flat) - the channels the
                                network reads from Advanced's Decoration

Part of Physicalbricks (see __init__.py)."""
import bpy

from .constants import EEVEE_PARAMS

VERSION = 1
MARK = 'rb_phys_lite_tree'
KINDS = {'Color': ('NodeSocketColor', 'RGBA'), 'Height': ('NodeSocketColor', 'RGBA')}     # else Float


def _kind(param):
    return KINDS.get(param, ('NodeSocketFloat', 'FLOAT'))


def _cached(name):
    tree = bpy.data.node_groups.get(name)
    return tree if tree is not None and tree.get(MARK) == VERSION else None


def _fresh(source, name):
    old = bpy.data.node_groups.get(name)
    if old is not None:
        old.name = name + '_old'
    copy = source.copy()
    copy.name = name
    copy[MARK] = VERSION
    return copy


def _inputs(tree):
    return [i for i in tree.interface.items_tree if getattr(i, 'in_out', None) == 'INPUT']


def mix_tree(lite_mix):
    """Lite's mix with Advanced's interface and the Eevee values mixed beside the shaders (see the module)."""
    name = 'rb_phys_mix_' + lite_mix.name
    cached = _cached(name)
    if cached is not None:
        return cached
    tree = _fresh(lite_mix, name)
    nodes, links = tree.nodes, tree.links
    gin = next(n for n in nodes if n.bl_idname == 'NodeGroupInput')
    gout = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
    shaders = [i for i in _inputs(tree) if i.socket_type == 'NodeSocketShader']
    masks = [i for i in _inputs(tree) if i.name == 'Dec Mask']
    # the shader inputs: base #n's and the print's, named as in Advanced's mix (Shader<n>, Shader Dec.)
    slot = {}                                             # shader input identifier -> its suffix (1, 2 ... or ' Dec.')
    for index, item in enumerate(shaders, 1):
        suffix = ' Dec.' if item.name == 'Dec Shader' else str(index)
        slot[item.identifier] = suffix
        item.name = 'Shader' + suffix
    for item in masks:
        item.name = 'Shader Dec. Mask'
    # one input per Eevee parameter and slot, one output per parameter
    param_in = {}
    for param in EEVEE_PARAMS:
        kind = _kind(param)[0]
        for identifier, suffix in slot.items():
            param_in[(param, identifier)] = tree.interface.new_socket(param + suffix, in_out='INPUT',
                                                                      socket_type=kind).identifier
        tree.interface.new_socket(param, in_out='OUTPUT', socket_type=kind)
    socket = {s.identifier: s for s in gin.outputs}

    def source_of(mixer, index, param, made):
        """What feeds the parameter where a Mix Shader input is fed: another Mix Shader's parameter mix, or the
        parameter input of the group input's shader slot."""
        if not mixer.inputs[index].is_linked:
            return None
        src = mixer.inputs[index].links[0].from_socket
        if src.node.bl_idname == 'ShaderNodeMixShader':
            return made[(src.node.name, param)].outputs[2 if _kind(param)[1] == 'RGBA' else 0]
        if src.node == gin and src.identifier in slot:
            return socket[param_in[(param, src.identifier)]]
        return None

    mixers = [n for n in nodes if n.bl_idname == 'ShaderNodeMixShader']
    made = {}
    pending = list(mixers)
    while pending:                                         # upstream mixers first
        for mixer in list(pending):
            ups = [mixer.inputs[i].links[0].from_node for i in (1, 2) if mixer.inputs[i].is_linked]
            if any(u.bl_idname == 'ShaderNodeMixShader' and u in pending for u in ups):
                continue
            for row, param in enumerate(EEVEE_PARAMS):
                mix = nodes.new('ShaderNodeMix')
                mix.data_type = _kind(param)[1]
                mix.label = f'{param}: as {mixer.name}'
                mix.location = (mixer.location.x, mixer.location.y - 220 * (row + 1))
                factor = mixer.inputs[0]
                if factor.is_linked:
                    links.new(factor.links[0].from_socket, mix.inputs[0])
                else:
                    mix.inputs[0].default_value = factor.default_value
                ab = (6, 7) if mix.data_type == 'RGBA' else (2, 3)
                for side, index in zip(ab, (1, 2), strict=True):
                    src = source_of(mixer, index, param, made)
                    if src is not None:
                        links.new(src, mix.inputs[side])
                made[(mixer.name, param)] = mix
            pending.remove(mixer)
    last = gout.inputs['Shader'].links[0].from_node if gout.inputs['Shader'].is_linked else None
    if last is not None and last.bl_idname == 'ShaderNodeMixShader':
        for param in EEVEE_PARAMS:
            mix = made[(last.name, param)]
            links.new(mix.outputs[2 if mix.data_type == 'RGBA' else 0], gout.inputs[param])
    return tree


def print_tree(lite_decoration):
    """Lite's Decoration with the outputs Color, Metallic and Height Advanced's gives (see the module)."""
    name = 'rb_phys_print_' + lite_decoration.name
    cached = _cached(name)
    if cached is not None:
        return cached
    tree = _fresh(lite_decoration, name)
    nodes, links = tree.nodes, tree.links
    gout = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
    inner = next((n for n in nodes if n.bl_idname == 'ShaderNodeGroup' and n.node_tree is not None
                  and 'Data' in n.inputs and 'Color' in n.inputs), None)
    for out_name in ('Color', 'Metallic', 'Height'):
        if out_name not in gout.inputs:
            tree.interface.new_socket(out_name, in_out='OUTPUT', socket_type='NodeSocketColor')
    if inner is None:
        return tree
    # Color: the print's colour as it reaches his decoration (the colour texture, or a legacy part's decoration texture)
    if inner.inputs['Color'].is_linked:
        links.new(inner.inputs['Color'].links[0].from_socket, gout.inputs['Color'])
    else:
        gout.inputs['Color'].default_value = inner.inputs['Color'].default_value
    # Metallic from the data texture: red = metallic print, blue = sticker, on a sticker red or green = metal foil
    if inner.inputs['Data'].is_linked:
        split = nodes.new('ShaderNodeSeparateColor')
        split.label = 'Data: red print metal, green foil, blue sticker'
        split.location = (inner.location.x, inner.location.y - 400)
        links.new(inner.inputs['Data'].links[0].from_socket, split.inputs[0])
        foil = nodes.new('ShaderNodeMath')
        foil.operation, foil.label = 'MAXIMUM', 'sticker metal: red or green'
        foil.location = (split.location.x + 200, split.location.y)
        links.new(split.outputs['Red'], foil.inputs[0])
        links.new(split.outputs['Green'], foil.inputs[1])
        metal = nodes.new('ShaderNodeMix')
        metal.data_type, metal.label = 'FLOAT', 'Metallic: print, or the sticker where blue'
        metal.location = (foil.location.x + 200, foil.location.y)
        links.new(split.outputs['Blue'], metal.inputs[0])
        links.new(split.outputs['Red'], metal.inputs[2])
        links.new(foil.outputs[0], metal.inputs[3])
        links.new(metal.outputs[0], gout.inputs['Metallic'])
    return tree
