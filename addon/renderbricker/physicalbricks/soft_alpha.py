# SPDX-License-Identifier: GPL-3.0-or-later
"""A print's mask, softened: a copy of a material's Mecabricks decoration tree with one more output, Soft Alpha - the
mean of the print's alpha at the point and at twelve points around it. The image's own alpha only says „ink or no
ink“; the softened one rises over about RADIUS_PX pixels of the image across the outline, which is what the physical
decoration needs to give the ink film a visible, bevelled relief, a bead along the outline and wear that starts at
the rims (user, 13.10.2026: „Beim Stempeldruck sehe ich nichts. Ich möchte eine Art Relief haben, weil die Farbe
aufgetragen ist.“ - the relief of the sharp mask was a line one pixel wide).

The Mecabricks tree itself is not touched; the copy is used by the physical network only (as network.part_bump_tree).

Part of Physicalbricks (see __init__.py)."""
import math

import bpy

MARK = 'rb_phys_soft_alpha'        # on the copy: the version of this construction
VERSION = 1
OUTPUT = 'Soft Alpha'
RADIUS_PX = 5.0                    # pixels of the print's image; a 512 px print on a 20 mm part: about 0.2 mm
# eight points on the circle of that radius and four on half of it, turned against the first
TAPS = ([(math.cos(k * math.pi / 4), math.sin(k * math.pi / 4)) for k in range(8)]
        + [(0.5 * math.cos(k * math.pi / 2 + 0.4), 0.5 * math.sin(k * math.pi / 2 + 0.4)) for k in range(4)])


def _alpha_source(tree):
    """(image node, node between image and alpha or None, the socket that carries the alpha) of a decoration tree,
    or None when the tree has no alpha from an image."""
    out = next((n for n in tree.nodes if n.bl_idname == 'NodeGroupOutput'), None)
    alpha = out.inputs.get('Alpha') if out is not None else None
    if alpha is None or not alpha.is_linked:
        return None
    source = alpha.links[0].from_socket
    node = source.node
    if node.bl_idname == 'ShaderNodeTexImage':
        return node, None, source
    if node.bl_idname == 'ShaderNodeGroup':                # legacy prints: a mask group reads the image's colour
        for socket in node.inputs:
            if socket.is_linked and socket.links[0].from_node.bl_idname == 'ShaderNodeTexImage':
                return socket.links[0].from_node, node, source
    return None


def soft_alpha_tree(tree):
    """The copy of a decoration tree with the output Soft Alpha (made once per tree and file). The tree itself when it
    has no alpha from an image - the caller then takes its Alpha."""
    name = tree.name + '.phys_soft'
    copy = bpy.data.node_groups.get(name)
    if copy is not None and copy.get(MARK) == VERSION:
        return copy
    if _alpha_source(tree) is None:
        return tree
    if copy is not None:
        copy.name = name + '_old'
    copy = tree.copy()
    copy.name = name
    copy[MARK] = VERSION
    image_node, between, source = _alpha_source(copy)
    nodes, links = copy.nodes, copy.links
    copy.interface.new_socket(OUTPUT, in_out='OUTPUT', socket_type='NodeSocketFloat')
    out = next(n for n in nodes if n.bl_idname == 'NodeGroupOutput')
    if image_node.image is None or not image_node.inputs['Vector'].is_linked:
        links.new(source, out.inputs[OUTPUT])
        return copy
    place = image_node.inputs['Vector'].links[0].from_socket
    radius = RADIUS_PX / max(image_node.image.size[0], 1)
    total = source
    x, y = image_node.location.x, image_node.location.y - 700
    for index, (dx, dy) in enumerate(TAPS, 1):
        shift = nodes.new('ShaderNodeVectorMath')
        shift.operation, shift.label = 'ADD', f'point {index} beside (image space)'
        shift.inputs[1].default_value = (dx * radius, dy * radius, 0.0)
        links.new(place, shift.inputs[0])
        tap = nodes.new('ShaderNodeTexImage')
        tap.image, tap.label = image_node.image, f'the print at point {index}'
        tap.interpolation, tap.extension = image_node.interpolation, image_node.extension
        tap.projection = image_node.projection
        links.new(shift.outputs[0], tap.inputs['Vector'])
        value = tap.outputs['Alpha']
        column = [shift, tap]
        if between is not None:
            mask = nodes.new('ShaderNodeGroup')
            mask.node_tree, mask.label = between.node_tree, f'its mask at point {index}'
            for socket, twin in zip(between.inputs, mask.inputs, strict=True):
                if not socket.is_linked:
                    if hasattr(socket, 'default_value'):
                        twin.default_value = socket.default_value
                elif socket.links[0].from_node == image_node:
                    links.new(tap.outputs[socket.links[0].from_socket.name], twin)
                else:
                    links.new(socket.links[0].from_socket, twin)
            value = mask.outputs[source.name]
            column.append(mask)
        add = nodes.new('ShaderNodeMath')
        add.operation, add.label = 'ADD', f'+ point {index}'
        links.new(total, add.inputs[0])
        links.new(value, add.inputs[1])
        total = add.outputs[0]
        column.append(add)
        for row, node in enumerate(column):
            node.location = (x + (index - 1) * 300, y - row * 320)
    mean = nodes.new('ShaderNodeMath')
    mean.operation, mean.label = 'MULTIPLY', f'the mean of the {len(TAPS) + 1} points: the softened mask'
    mean.inputs[1].default_value = 1.0 / (len(TAPS) + 1)
    mean.location = (x + len(TAPS) * 300, y)
    links.new(total, mean.inputs[0])
    links.new(mean.outputs[0], out.inputs[OUTPUT])
    return copy
