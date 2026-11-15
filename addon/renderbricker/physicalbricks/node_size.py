# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Blender draws a node and its sockets, for stacking the network's nodes without overlap.

The model follows Blender's node_draw.cc (node_update_basis, node_update_basis_from_socket_lists,
node_update_basis_from_declaration, node_update_collapsed, the margins table) with the button heights measured in
Blender 5.3; it is the socket model of the Renderbricks R&D tool node_routing.py (exact for 886 of 886 nodes of the
physical groups in 5.3). A reroute's socket is its location (node_draw.cc reroute_node_prepare_for_draw).

    socket_offsets(node) -> ({output identifier: dy}, {input identifier: dy}, height)   dy below the location
    node_height(node)     the drawn height (a reroute: 0)
    node_top(node)        how far the drawn top lies above the location (a collapsed node; else 0)
    socket_point(node, socket) -> (x, y)   in the tree, through location_absolute
    node_rect(node)       (x0, y_bottom, x1, y_top) as drawn
    modelled(node)        False for a conventional node whose buttons were not measured: it counts BUTTONS_UNKNOWN

Before Blender 5.3 a conventional node is laid out by another rule (SOCKET_LISTS); nodes drawn from a declaration
(groups, the Principled BSDF, the Gamma with its output in its input's row - ALIGNED) and collapsed nodes are drawn
alike in 5.0 to 5.3."""
import bpy

HEADER, TOP, ROW, GAP = 20, 4, 20, 2      # NODE_DY; 2 x NODE_ITEM_SPACING_Y; a socket row; NODE_ITEM_SPACING_Y
VECTOR_FIELDS = 62                          # an unlinked vector input shows its label and x, y, z (measured)
PANEL_HEADER = 10                           # NODE_DYS
BASIS_RAD = 4                               # 0.2 widget units
BUTTONS_UNKNOWN = 24

# the buttons of a conventional node with their margins, measured in Blender 5.3: node height minus its socket rows.
# None = a node without buttons.
BUTTONS = {
    'ShaderNodeMath': 49, 'ShaderNodeVectorMath': 24, 'ShaderNodeTexNoise': 74, 'ShaderNodeTexCoord': 49,
    'ShaderNodeBump': 24, 'ShaderNodeSeparateColor': 24, 'ShaderNodeTexWhiteNoise': 24, 'ShaderNodeBevel': 24,
    'ShaderNodeVectorTransform': 74, 'ShaderNodeAttribute': 49, 'ShaderNodeAmbientOcclusion': 74,
    'ShaderNodeTexWave': 74,
    ('ShaderNodeMix', 'FLOAT'): 49, ('ShaderNodeMix', 'VECTOR'): 74, ('ShaderNodeMix', 'RGBA'): 99,
    ('ShaderNodeMapRange', 'SMOOTHSTEP'): 49, ('ShaderNodeMapRange', 'LINEAR'): 74,
    ('ShaderNodeTexVoronoi', 'F1'): 99, ('ShaderNodeTexVoronoi', 'DISTANCE_TO_EDGE'): 74,
    'ShaderNodeAddShader': None, 'ShaderNodeMixShader': None, 'ShaderNodeCombineXYZ': None,
    'ShaderNodeSeparateXYZ': None, 'ShaderNodeHueSaturation': None,
    'ShaderNodeBsdfTranslucent': None, 'ShaderNodeFresnel': None, 'ShaderNodeBsdfAnisotropic': 24,
    'ShaderNodeBsdfDiffuse': None,
    'ShaderNodeBsdfTransparent': None, 'ShaderNodeLightPath': None, 'ShaderNodeNewGeometry': None,
    'ShaderNodeObjectInfo': None, 'ShaderNodeValue': None, 'NodeGroupInput': None, 'NodeGroupOutput': None,
    'NodeCombineBundle': None, 'NodeSeparateBundle': None,
    # measured 10.11.2026 in a Blender 5.3.0 window (Renderbricks R&D run 158, measure_nodes.py; drawn height at UI
    # scale 1 minus the socket rows): the colour picker 102 (drawn 150), the colour mode menu 24 (136), the target menu
    # 24 (138); the Emission none (drawn 92, as the Add Shader). With them every node of the hat's network of Red
    # Beard in Lite, Advanced and Dev and of an LDraw polygon-print material in Dev is drawn as modelled (0 off)
    'ShaderNodeRGB': 102, 'ShaderNodeCombineColor': 24, 'ShaderNodeOutputMaterial': 24, 'ShaderNodeEmission': None,
}
# Blender 5.0 to 5.2 lay out a conventional node by the rule of node_update_basis_from_socket_lists before 5.3
# (node_draw.cc of v5.0.1, v5.1.2, v5.2.4; socket rows, buttons, declared and collapsed nodes are drawn as in 5.3):
# 5 at the top (NODE_DYS / 2); after a shown output 2 when another output follows - in 5.0 any, from 5.1 an available
# one; 5 after the outputs (NODE_DY / 4); after a shown input 2 when any input follows; 5 at the bottom after inputs or
# buttons; and the colour picker's buttons are 97. Measured 11.11.2026 in Blender 5.2.4 and 5.0.1 windows (Renderbricks
# R&D run 159, task 6): by the 5.3 rule 33 and 25 of their conventional nodes were 2 to 9 px off, by this one none.
# version -> (which next output earns the gap: 'any' / 'available', the buttons that differ)
SOCKET_LISTS = {(5, 0): ('any', {'ShaderNodeRGB': 97}), (5, 1): ('available', {'ShaderNodeRGB': 97}),
                (5, 2): ('available', {'ShaderNodeRGB': 97})}
_LISTS = SOCKET_LISTS.get(tuple(bpy.app.version[:2]))
if _LISTS is not None:
    BUTTONS.update(_LISTS[1])
# panels in declaration order; a socket in a closed panel is drawn at the panel's header
PRINCIPLED_PANELS = (
    ("Diffuse", ("Diffuse Roughness",)),
    ("Subsurface", ("Subsurface Weight", "Subsurface Radius", "Subsurface Scale", "Subsurface IOR",
                    "Subsurface Anisotropy")),
    ("Specular", ("Specular IOR Level", "Specular Tint", "Anisotropic", "Anisotropic Rotation", "Tangent")),
    ("Transmission", ("Transmission Weight", "Transmission Dispersion Scale", "Transmission Dispersion Abbe Number")),
    ("Coat", ("Coat Weight", "Coat Roughness", "Coat IOR", "Coat Tint", "Coat Normal")),
    ("Sheen", ("Sheen Weight", "Sheen Roughness", "Sheen Tint")),
    ("Emission", ("Emission Color", "Emission Strength")),
    ("Thin Film", ("Thin Film Thickness", "Thin Film IOR")),
)
VOLUME_PANELS = (
    ("Absorption", ("Absorption Coefficients",)),
    ("Scatter", ("Scatter Coefficients", "Anisotropy", "IOR", "Backscatter", "Alpha", "Diameter")),
    ("Emission", ("Emission Coefficients",)),
)
# nodes drawn from a declaration with panels: (panels, closed by default, panels whose content starts with a layout)
PANELLED = {
    'ShaderNodeBsdfPrincipled': (PRINCIPLED_PANELS, True, ("Subsurface", "Specular")),
    'ShaderNodeVolumeCoefficients': (VOLUME_PANELS, False, ("Scatter",)),
}
# nodes drawn from a declaration whose output shares the row of the input before it (part 4c, ruling C8; measured in
# the Blender 5.3 window, Renderbricks R&D run 160 task 7: the Gamma 70 high, modelled conventionally 92). A node whose
# declaration calls use_custom_socket_order() is drawn from its declaration (node_draw.cc:344-347
# is_node_panels_supported, 1300-1305 node_update_basis); an output declared align_with_previous() goes into the row of
# the socket before it when that one is visible, else into a row of its own (node_draw.cc:706-734
# add_flat_items_for_socket). Gamma: input Color, output Color aligned, input Gamma (nodes/shader/nodes/
# node_shader_gamma.cc:22-42) - 20 + 4 + 20 + 2 + 20 + 4 = 70. The same declaration and the same drawing path in
# v5.0.1 and v5.2.4 (their node_shader_gamma.cc and node_draw.cc read 12.11.2026), so no SOCKET_LISTS entry: 70 in
# 5.0 to 5.3. Per type: the rows in declaration order, each (input name, the name of the output aligned with it or
# None). Not modelled, used by none of our groups nor the network: ShaderNodeVectorRotate (node_shader_vector_rotate.cc
# :27-50, its output Vector aligned, with a default layout whose buttons were not measured; only in Dev's surface layer
# groups, which keep their own layout), ShaderNodeRaycast (node_shader_raycast.cc:32-83, aligned attribute outputs in a
# panel); the other custom-order shader nodes without an aligned output - Glass, Metallic BSDF, Light Info - are not
# used either
ALIGNED = {
    'ShaderNodeGamma': (("Color", "Color"), ("Gamma", None)),
}
# item kinds: S socket, L layout, P panel header, B / E the begin / end of an open panel's content
MARGIN = {('S', 'S'): 2, ('S', 'L'): 4, ('S', 'P'): 6, ('S', 'E'): 4,
          ('L', 'S'): 4, ('L', 'L'): 2, ('L', 'P'): 6, ('L', 'E'): 4,
          ('P', 'S'): 8, ('P', 'L'): 6, ('P', 'P'): 10, ('P', 'B'): 6, ('P', 'E'): 6,
          ('B', 'S'): 4, ('B', 'L'): 4, ('B', 'P'): 6, ('B', 'E'): 2,
          ('E', 'S'): 2, ('E', 'L'): 2, ('E', 'P'): 6, ('E', 'E'): 0}
MARGIN_TOP = {'S': 4, 'L': 6, 'P': 8}
MARGIN_BOTTOM = {'S': 4, 'L': 10, 'P': 8, 'E': 2}


class _ThinWallRow:
    """The row Thin Wall a Principled BSDF of a 5.0 file gets when it opens in 5.1+."""
    is_output, is_linked, type, identifier, hide_value = False, True, 'BOOLEAN', '', False


def _visible(s):
    return s.enabled and not s.hide


def _row(s):
    if s.is_output or s.is_linked or getattr(s, 'hide_value', False) or s.type != 'VECTOR':
        return ROW
    return ROW + VECTOR_FIELDS


def _button_key(node):
    """The key of the node's measured buttons in BUTTONS, or None when they were not measured."""
    for prop in ('data_type', 'interpolation_type', 'feature'):
        key = (node.bl_idname, getattr(node, prop, None))
        if key in BUTTONS:
            return key
    return node.bl_idname if node.bl_idname in BUTTONS else None


def _buttons(node):
    key = _button_key(node)
    return BUTTONS_UNKNOWN if key is None else BUTTONS[key]


def _conventional(node):
    """Outputs, buttons, inputs (node_update_basis_from_socket_lists)."""
    outs, ins = {}, {}
    d = HEADER + TOP
    shown_out = [s for s in node.outputs if _visible(s)]
    shown_in = [s for s in node.inputs if _visible(s)]
    for i, s in enumerate(shown_out):
        d += GAP if i else 0
        outs[s.identifier] = d + ROW // 2
        d += ROW
    b = _buttons(node)
    if b is not None:
        d += b
    for i, s in enumerate(shown_in):
        if i or (b is None and shown_out):
            d += GAP
        ins[s.identifier] = d + ROW // 2
        d += _row(s)
    if shown_out or shown_in or b is not None:
        d += 2 * GAP
    return outs, ins, max(d, 2 * HEADER)


def _conventional_before_5_3(node, next_output):
    """Outputs, buttons, inputs by the rule of Blender 5.0 to 5.2 (SOCKET_LISTS); next_output 'any' / 'available'."""
    outs, ins = {}, {}
    d = HEADER + HEADER // 4
    outputs, inputs = list(node.outputs), list(node.inputs)
    shown_out = shown_in = False
    for i, s in enumerate(outputs):
        if not _visible(s):
            continue
        outs[s.identifier] = d + ROW // 2
        d += ROW
        following = outputs[i + 1] if i + 1 < len(outputs) else None
        if following is not None and (next_output == 'any' or following.enabled):
            d += GAP
        shown_out = True
    if shown_out:
        d += HEADER // 4
    b = _buttons(node)
    if b is not None:
        d += b
    for i, s in enumerate(inputs):
        if not _visible(s):
            continue
        ins[s.identifier] = d + ROW // 2
        d += _row(s)
        if i + 1 < len(inputs):
            d += GAP
        shown_in = True
    if shown_in or b is not None:
        d += HEADER // 4
    return outs, ins, max(d, 2 * HEADER)


def _declared(items):
    """Items in order: ('S', socket or a tuple of the sockets sharing one row) | ('L', None) | ('P', [sockets of the
    closed panel]) | ('B' / 'E', None) - node_update_basis_from_declaration."""
    outs, ins = {}, {}
    if not items:
        return outs, ins, HEADER + 10
    d = HEADER
    for i, (kind, what) in enumerate(items):
        d += MARGIN_TOP[kind] if i == 0 else MARGIN[(items[i - 1][0], kind)]
        if kind == 'S':
            row = what if isinstance(what, tuple) else (what,)
            for s in row:
                (outs if s.is_output else ins)[s.identifier] = d + ROW // 2
            d += max(_row(s) for s in row)
        elif kind == 'L':
            d += ROW
        elif kind == 'P':
            center = d + PANEL_HEADER // 2
            for s in what:
                ins[s.identifier] = center
            d += PANEL_HEADER
    d += MARGIN_BOTTOM[items[-1][0]]
    return outs, ins, max(d, 2 * HEADER)


def _collapsed(node):
    """A collapsed node (node_draw.cc node_update_collapsed): sockets 10 apart around its middle; dy below the node's
    location (not its top - see node_top)."""
    shown_out = [s for s in node.outputs if _visible(s)]
    shown_in = [s for s in node.inputs if _visible(s)]
    step = HEADER // 2
    h = step * max(len(shown_in), len(shown_out), 2) + 2 * BASIS_RAD
    outs = {s.identifier: step - step * (len(shown_out) - 1) / 2 + step * k for k, s in enumerate(shown_out)}
    ins = {s.identifier: step - step * (len(shown_in) - 1) / 2 + step * k for k, s in enumerate(shown_in)}
    return outs, ins, h


def node_top(node):
    """How far the drawn top lies above the node's location: 0, for a collapsed node h / 2 - 10."""
    if node.bl_idname != 'NodeReroute' and node.hide:
        return _collapsed(node)[2] / 2 - HEADER // 2
    return 0


def modelled(node):
    """False for a conventional node whose buttons were not measured (its height counts BUTTONS_UNKNOWN)."""
    if node.bl_idname in ('NodeReroute', 'ShaderNodeGroup') or node.bl_idname in PANELLED or node.hide \
            or node.bl_idname in ALIGNED:
        return True
    return _button_key(node) is not None


def node_height(node):
    """The drawn height of a node in view units (a reroute: 0)."""
    return socket_offsets(node)[2]


def socket_offsets(node):
    """({output identifier: dy}, {input identifier: dy}, height): socket centres below the node's location (its top,
    except for a collapsed node), in view units; a reroute: both 0, height 0."""
    if node.bl_idname == 'NodeReroute':
        return {node.outputs[0].identifier: 0}, {node.inputs[0].identifier: 0}, 0
    if node.hide:
        return _collapsed(node)
    if node.bl_idname == 'ShaderNodeGroup':
        items = [('S', s) for s in node.outputs if _visible(s)]
        items += [('L', None)] + [('S', s) for s in node.inputs if _visible(s)]
        return _declared(items)
    if node.bl_idname in ALIGNED:
        items = []
        for in_name, out_name in ALIGNED[node.bl_idname]:
            # the input hidden: its aligned output alone in the row (add_flat_items_for_socket)
            ins_, outs_ = node.inputs.get(in_name), node.outputs.get(out_name) if out_name else None
            row = tuple(s for s in (ins_, outs_) if s is not None and _visible(s))
            if row:
                items.append(('S', row))
        return _declared(items)
    if node.bl_idname in PANELLED:
        panels, closed_default, with_layout = PANELLED[node.bl_idname]
        in_panel = {name for _, names in panels for name in names}
        items = [('S', s) for s in node.outputs if _visible(s)]
        items += [('S', s) for s in node.inputs if _visible(s) and s.name not in in_panel]
        names = [s.name for s in node.inputs]
        if node.bl_idname == 'ShaderNodeBsdfPrincipled' and 'Thin Wall' not in names and 'Alpha' in names:
            at = next(i for i, (_, s) in enumerate(items) if s.name == 'Alpha') + 1
            items.insert(at, ('S', _ThinWallRow()))
        states = list(getattr(node, 'panel_states', ()))
        for index, (title, names) in enumerate(panels):
            members = [s for s in node.inputs if s.name in names and s.enabled]
            if not members:
                continue
            is_open = (not states[index].is_collapsed) if index < len(states) else not closed_default
            if is_open:
                items += [('P', []), ('B', None)] + ([('L', None)] if title in with_layout else [])
                items += [('S', s) for s in members if not s.hide] + [('E', None)]
            else:
                items.append(('P', members))
        return _declared(items)
    return _conventional(node) if _LISTS is None else _conventional_before_5_3(node, _LISTS[0])


def _top_left(node):
    loc = node.location_absolute if hasattr(node, 'location_absolute') else node.location
    return round(loc[0]), round(loc[1])


def socket_point(node, socket):
    """Where a socket is drawn, in the tree's coordinates (a reroute: its location), rounded."""
    x, y = _top_left(node)
    if node.bl_idname == 'NodeReroute':
        return (x, y)
    outs, ins, _ = socket_offsets(node)
    if socket.is_output:
        return (x + round(node.width), y - outs[socket.identifier])
    return (x, y - ins[socket.identifier])


def node_rect(node):
    """(x0, y_bottom, x1, y_top) as drawn."""
    x, y = _top_left(node)
    _, _, h = socket_offsets(node)
    top = y + node_top(node)
    return (x, top - h, x + round(node.width), top)
