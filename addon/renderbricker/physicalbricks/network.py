# SPDX-License-Identifier: GPL-3.0-or-later
"""Building and removing the physical network of one material beside its Mecabricks tree.

Part of Physicalbricks (see __init__.py)."""
import bpy

from . import host
from .colour import from_acescg, to_working
from .constants import (
    CLASS_GROUPS,
    EEVEE_GROUP,
    EEVEE_PARAMS,
    EEVEE_WALL_MM,
    EFFECT_INPUTS,
    FLAKE_DEFAULTS,
    FLAKE_INPUTS,
    GLASS,
    GLITTER_OPAQUE,
    IRIDESCENCE_INPUTS,
    MARK,
    NET,
    OLD_TRACES,
    PART_BUMP,
    PARTICLE_DEFAULTS,
    PARTICLE_INPUTS,
    REFRACTION,
    VIEWPORT,
)
from .groups import (
    base_nodes,
    cycles_output,
    kind_of,
    solid_random_walk_group,
    swap_tree,
)
from .layout import layout
from .lite_trees import mix_tree, print_tree

# base_material_nodes, colour_id_of, output moved to readers.py (plan part 3, task 1) and stay importable from here:
# R&D scripts and the suite's run 146/147 tests import them from network
from .readers import base_material_nodes, colour_id_of, find, output, read  # noqa: F401 re-exported
from .scene import AFTERGLOW, afterglow_strength
from .soft_alpha import soft_alpha_tree
from .surface import SETTINGS_GROUP, surface_active


def revert_v1(tree):
    """Fork 40/41 swapped mb_base_<type> for mb_phys_<type> (rb_phys_<type> once renamed on open) in place; put the
    Mecabricks groups back."""
    out = cycles_output(tree)
    for node in base_nodes(tree):
        if not node.node_tree.name.startswith('rb_phys_') or node.get(NET):
            continue                                  # the network's own groups are removed, not swapped
        kind = kind_of(node)
        target = bpy.data.node_groups.get('mb_base_' + kind)
        if target is None:
            continue
        if out is not None:
            for link in [l for l in tree.links if l.from_node == node and l.to_node == out]:
                tree.links.remove(link)
        swap_tree(tree, node, target)
        if MARK in node:
            del node[MARK]

def remove_network(material):
    """Delete the physical network and give the outputs back to the Mecabricks nodes. A network of part 4b's files goes
    with its taps and trace reroutes (they carry NET), and the mark its traces left on the tree (constants.OLD_TRACES)
    goes too, so the Mecabricks tree is as before the switch."""
    tree = material.node_tree
    if OLD_TRACES in tree:
        del tree[OLD_TRACES]
    nodes = [n for n in tree.nodes if n.get(NET)]
    if not nodes:
        return False
    for node in nodes:
        tree.nodes.remove(node)
    if REFRACTION in material:                        # the glass's raytrace-refraction flag, as before Physical
        material.use_raytrace_refraction = bool(material[REFRACTION])
        del material[REFRACTION]
    if VIEWPORT in material:                          # the viewport (Solid) colour, as before Physical
        material.diffuse_color = list(material[VIEWPORT])
        del material[VIEWPORT]
    # the way back follows the tree's structure, not its name: a material renamed after the switch (no reader knows it
    # then) still gets Nicolas' outputs back - before part 3 this found them by label too (final review, finding 2)
    reading = read(material)
    if reading is not None:
        mix, eevee = reading.mix, reading.eevee
        out_c, out_e = reading.out_cycles, reading.out_eevee
    else:
        mix, eevee = find(tree, 'Mix Shader'), find(tree, 'Eevee Shader')
        out_c, out_e = output(tree, 'CYCLES'), output(tree, 'EEVEE')
    if out_c is not None and mix is not None and not out_c.inputs['Surface'].is_linked:
        tree.links.new(mix.outputs['Shader'], out_c.inputs['Surface'])
    if out_e is not None and eevee is not None and not out_e.inputs['Surface'].is_linked:
        tree.links.new(eevee.outputs['Shader'], out_e.inputs['Surface'])
    return True

def part_bump_tree(tree, relief_mm):
    """The copy of a Mecabricks normal tree whose part bump has the physical relief (shared by every material with the
    same tree and relief; not used by Mecabricks, so a file saved in mode Mecabricks drops it)."""
    name = f'{tree.name}.phys_{relief_mm:g}mm'
    copy = bpy.data.node_groups.get(name)
    if copy is not None and abs(copy.get(PART_BUMP, -1.0) - relief_mm) < 1e-9:
        return copy
    copy = tree.copy()
    copy.name = name
    copy[PART_BUMP] = relief_mm
    gin = next(n for n in copy.nodes if n.bl_idname == 'NodeGroupInput')
    for bump in [n for n in copy.nodes if n.label == 'Bump']:
        mul = copy.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.label = 'relief (mm) x scale'
        mul.inputs[1].default_value = relief_mm
        mul.location = (bump.location.x - 200, bump.location.y - 120)
        copy.links.new(gin.outputs['Scale'], mul.inputs[0])
        copy.links.new(mul.outputs[0], bump.inputs[0])
    return copy

def record_working_colour(record):
    """The record's colour in the working space: colour.acescg where the colour lies beyond Rec.709 (190 Fire Yellow,
    user 01.11.2026 - Rec.709 had no room left, the view showed it too pale), else colour.rgb (linear Rec.709)."""
    colour = record['colour']
    if 'acescg' in colour:
        return [max(v, 0.0) for v in from_acescg(colour['acescg'])]
    return to_working(colour['rgb'])

def render_kind(record):
    """How a record renders: its class; a glitter record with body "opaque" (132, 287-291 „with Glitter“, materials
    version 8) is 'glitter_opaque' - the glitter's flakes on the opaque core, no glass (not in GLASS). None without
    a record."""
    if not record:
        return None
    if record['class'] == 'glitter' and record.get('body') == 'opaque':
        return 'glitter_opaque'
    return record['class']

def class_group(kind, record):
    """The class group a record of render_kind `kind` renders with: CLASS_GROUPS by its class; 'glitter_opaque' takes
    rb_phys_glitter_opaque (group version 36; 35: rb_phys_speckle_glitter for a speckle record with flakes, user
    02.11.2026: „nur mit unserem Glitter statt Speckle“). None for a kind without a group."""
    if kind == 'glitter_opaque':
        return GLITTER_OPAQUE
    return CLASS_GROUPS.get(kind)

def effect_value(key, value):
    """The value of a record 'effect' key for its group input (EFFECT_INPUTS): metal_rgb a linear Rec.709 colour, a
    key ending in _acescg an ACEScg colour (specular_tint_acescg, group version 34) - both into the working space with
    alpha 1; a number as it is."""
    if key in ('metal_rgb', 'metal_f82_rgb'):                  # chrome: F0 and F82 tint, linear Rec.709
        return to_working(value) + [1.0]
    if key.endswith('_acescg'):
        return [max(v, 0.0) for v in from_acescg(value)] + [1.0]
    return value

def build_network(material, with_surface=None, reading=None, after=()):
    """Build the physical network of one material; False when the material lacks the Mecabricks nodes it reads, or
    when the colour of none of its base nodes is known (colour_id_of: no mb_colour_id and no id in the name) - such a
    material keeps its tree untouched and is counted as skipped, never coloured by a guess.
    with_surface: with the surface node (None: as the context scene's sliders say); reading: what the material's
    importer built (readers.read; None: read it now) - a tree no reader knows is skipped.
    after: functions(material) that add the host's nodes (host.AFTER_NETWORK, from switch.set_material_system),
    called on the built network before its layout, so it is placed once with them (speed profile run 261115: it was
    placed here and again after them, 0.32 s on 136 materials)."""
    from . import records
    tree = material.node_tree
    nodes, links = tree.nodes, tree.links
    reading = reading if reading is not None else read(material)
    if reading is None:
        return False
    mix, eevee = reading.mix, reading.eevee
    scale, normal = reading.scale, reading.normal
    out_c, out_e = reading.out_cycles, reading.out_eevee
    bases = reading.bases
    if not any(records.of(material, i) for i in reading.colour_ids):
        return False
    surface = normal
    made = []

    def new(kind, label):
        node = nodes.new(kind)
        node.label = label
        node[NET] = True
        made.append(node)
        return node

    def input_of(group_node, identifier):
        return next(s for s in group_node.inputs if s.identifier == identifier)

    # a legacy part's own bump map: Mecabricks feeds its height 0-1 with Bevel (0.35 BU) as bump distance
    # (add_legacy_bump links Group Input outputs[0], which became Bevel) - a saturated bump, hidden in Mecabricks
    # under 1 mm of subsurface.
    # The network uses its own instance of the part's normal group with a copied tree, in which the bump distance is
    # the record's relief (mm) x Scale; the Mecabricks tree and node stay as they are
    # A legacy decoration reads the same bump image through its 'Bump' input: there the image is the decoration's
    # relief, which rb_phys_decoration builds - the part relief is 0 then (no double relief)
    # Only the legacy bump (add_legacy_bump: distance wired from Bevel) is affected; version-2 maps are moulding marks
    # (logo, part and mould numbers) at 1.0 = 1 mm, which is physical, and keep the Mecabricks normal
    if any(n.label == 'Bump' and n.inputs[0].is_linked and n.inputs[0].links[0].from_socket.name == 'Bevel'
           for n in normal.node_tree.nodes):
        mdec_ = reading.decoration
        legacy_decoration = mdec_ is not None and 'Bump' in mdec_.inputs and mdec_.inputs['Bump'].is_linked
        relief = 0.0 if legacy_decoration else records.surface().get('part_bump_relief_mm', 0.1)
        pnormal = new('ShaderNodeGroup', 'Physical Normal')
        pnormal.node_tree = part_bump_tree(normal.node_tree, relief)
        for socket in normal.inputs:
            target = next((x for x in pnormal.inputs if x.identifier == socket.identifier), None)
            if target is None:
                continue
            if socket.is_linked:
                links.new(socket.links[0].from_socket, target)
            elif hasattr(socket, 'default_value'):
                target.default_value = socket.default_value
        normal = surface = pnormal
    # LDraw slopes (renderdraw slope_grain.insert_slope_grain): the grain sits between the Normal group and the
    # Mecabricks Customize group - the physical network reads after it too. Until 2.1.17.84 it read the Normal group
    # itself and LDraw slopes rendered smooth in Physical (found in run 144, 03.11.2026)
    grain = find(tree, 'Slope Grain')
    if grain is not None and 'Normal' in grain.outputs and 'Height' in grain.outputs:
        normal = surface = grain
    # Nicolas' Customize (Advanced as shipped; spec §2, maintainer 08.11.: his extra effects stay in Physical until
    # RenderFX): its scratches, dents and deformation reach the physical base through its Normal and Height, its
    # fingerprints and dirt as the difference of its Roughness to the same group at rest - read live, so a change in
    # his panel after the switch acts. Dev reads past its Customize (Reading.customize None): it has its own layers
    cust = reading.customize
    rough_delta = None
    if cust is not None:
        normal = surface = cust
        at_rest = new('ShaderNodeGroup', 'Customize at rest')
        at_rest.node_tree = cust.node_tree
        for socket in cust.inputs:
            target = next((x for x in at_rest.inputs if x.identifier == socket.identifier), None)
            if target is None:
                continue
            if socket.name in ('Normal', 'Height', 'Scale') and socket.is_linked:
                links.new(socket.links[0].from_socket, target)
            elif isinstance(getattr(target, 'default_value', None), float):
                target.default_value = 0.0            # every effect off
        rough_delta = new('ShaderNodeMath', 'Customize roughness (effects - at rest)')
        rough_delta.operation = 'SUBTRACT'
        links.new(cust.outputs['Roughness'], rough_delta.inputs[0])
        links.new(at_rest.outputs['Roughness'], rough_delta.inputs[1])
    # the surface of the part (UPDATES #91): moulding unevenness and micro surface on the clean normal, before
    # everything that reads it - the decoration and the class groups, so plastic and print carry it. Its values are
    # the panel's (surface.py). Built only while a slider is above 0: at 0 it changed no picture but cost render time
    psurface = None
    if (surface_active() if with_surface is None else with_surface) and host.SURFACE_BRANCH is not None:
        psurface = host.SURFACE_BRANCH(tree, normal, scale, new)     # the carrying add-on's branch (Dev: the layers)
    if psurface is not None:
        normal = surface = psurface
    # the physical mix: a second instance of the material's Mix Shader group, every Mecabricks input carried over
    pmix = new('ShaderNodeGroup', 'Physical Mix')
    # Lite mixes shaders only: a copy of its mix with Advanced's interface mixes the Eevee values too (lite_trees)
    pmix.node_tree = mix_tree(mix.node_tree) if reading.case == 'lite' else mix.node_tree
    for link in [l for l in links if l.to_node == mix]:
        links.new(link.from_socket, input_of(pmix, link.to_socket.identifier))
    # decorated parts: a second instance of the Mecabricks Decoration group, fed with the clean normal and
    # the scale, gives the data (colour, Alpha = print coverage, Sticker = blue channel, Metallic = red/green); the
    # group rb_phys_decoration makes ink, metallic ink and laminated sticker of it and the decorated relief
    mdec = reading.decoration
    if mdec is not None and mdec.node_tree is not None and 'rb_phys_decoration' in bpy.data.node_groups:
        values = records.decoration()
        data = new('ShaderNodeGroup', 'Decoration data')
        # a copy of the Mecabricks decoration tree that also gives the softened mask (the print's visible relief)
        # Lite: his decoration lacks Color and Metallic - a copy with them (lite_trees.print_tree)
        data.node_tree = soft_alpha_tree(print_tree(mdec.node_tree) if reading.case == 'lite' else mdec.node_tree)
        # every input of the Mecabricks Decoration reaches the data instance from the same source (legacy decorations
        # read their bump image through 'Bump': without it every legacy sticker and chrome foil became ink),
        # except the wear: Normal and Height come from the clean bevel normal instead of Customize
        for link in [l for l in links if l.to_node == mdec]:
            if link.from_node.label == 'Customize':
                continue
            target = next((x for x in data.inputs if x.identifier == link.to_socket.identifier), None)
            if target is not None:
                links.new(link.from_socket, target)
        for name in ('Normal', 'Height'):
            if name in data.inputs and not data.inputs[name].is_linked and name in normal.outputs:
                links.new(normal.outputs[name], data.inputs[name])
        if 'Scale' in data.inputs and not data.inputs['Scale'].is_linked:
            links.new(scale.outputs[0], data.inputs['Scale'])
        pdec = new('ShaderNodeGroup', 'Physical Decoration')
        pdec.node_tree = bpy.data.node_groups['rb_phys_decoration']
        for name in ('Color', 'Alpha', 'Sticker', 'Metallic'):
            if name in data.outputs:
                links.new(data.outputs[name], pdec.inputs[name])
        if 'Soft Alpha' in pdec.inputs and 'Alpha' in data.outputs:
            soft = data.outputs['Soft Alpha' if 'Soft Alpha' in data.outputs else 'Alpha']
            links.new(soft, pdec.inputs['Soft Alpha'])
        links.new(normal.outputs['Normal'], pdec.inputs['Normal'])
        if 'Height' in normal.outputs:                 # Lite's Normal has none: the print's relief on a flat part
            links.new(normal.outputs['Height'], pdec.inputs['Height'])
        links.new(scale.outputs[0], pdec.inputs['Scale'])
        for name, key in (('Ink Roughness', 'ink_roughness'), ('Ink Height', 'ink_height_mm'),
                          ('Metal Ink Roughness', 'metal_ink_roughness'), ('Sticker Roughness', 'sticker_roughness'),
                          ('Sticker Print Roughness', 'sticker_print_roughness'),
                          ('Sticker Thickness', 'sticker_thickness_mm'),
                          ('Foil Roughness', 'foil_roughness'), ('Metal Ink Grain', 'metal_ink_grain_mm'),
                          ('Metal Ink Relief', 'metal_ink_relief_mm')):
            if key in values and name in pdec.inputs:
                pdec.inputs[name].default_value = values[key]
        # every physical-mix input the Mecabricks decoration fed (mask, legacy colour masks) now comes from the data
        for link in [l for l in links if l.to_node == pmix and l.from_node == mdec]:
            target, name = link.to_socket, link.from_socket.name
            links.remove(link)
            if name == 'Alpha' and 'Alpha' in pdec.outputs:
                links.new(pdec.outputs['Alpha'], target)       # the print's alpha with its wear (panel Surface)
            elif name in data.outputs:
                links.new(data.outputs[name], target)
        for slot, output_name in (('Shader Dec.', 'Shader'), ('Color Dec.', 'Color'), ('Metallic Dec.', 'Metallic'),
                                  ('Roughness Dec.', 'Roughness'), ('Height Dec.', 'Height')):
            if slot in pmix.inputs:
                for link in list(pmix.inputs[slot].links):
                    links.remove(link)
                links.new(pdec.outputs[output_name], pmix.inputs[slot])
        surface = pdec
    ids = list(reading.colour_ids)
    recs = [records.of(material, i) for i in ids]
    kinds = [render_kind(r) for r in recs]
    single_glass = all(k in GLASS for k in kinds) and len(set(ids)) == 1
    shaders = []                                 # the physical class groups, in the order of the colours
    volume = None
    effects = []
    settings = None                              # the settings group node, one per network (Yellowing)
    for index, (base, record, kind) in enumerate(zip(bases, recs, kinds, strict=True), 1):
        name = class_group(kind, record)
        group = bpy.data.node_groups.get(name) if name else None
        if kind == 'solid' and record['sss'].get('method') == 'random_walk':
            group = solid_random_walk_group()
        if group is None or (kind in GLASS and not single_glass):
            continue                                  # stays the Mecabricks base output (carried over above)
        phys = new('ShaderNodeGroup', 'Physical #' + str(index) + ': ' + record['name'])
        phys.node_tree = group
        trans = record.get('transmittance') if kind in GLASS else None
        colour_source = None                         # the colour into the class group, when not `colour` itself
        if trans:
            # the matched transmittance lies partly outside Rec.709 - typed as three numbers (no colour
            # picker, whose HSV clamps saturation at 1), converted from ACEScg into the working space. The label is
            # short (part 4b, acceptance point 5: the frame's title says the rest; until then '(<source>, transmittance
            # after 4 mm)' followed it)
            colour = new('ShaderNodeCombineColor', 'Colour #' + str(index))
            # the group expects the transmittance after 4 mm: a record measured over another depth is converted
            # (Beer-Lambert, T_4 = T_d ^ (4 / d))
            depth = trans.get('depth_mm', 4.0) or 4.0
            numbers = [max(v, 0.0) for v in from_acescg([max(c, 1e-6) ** (4.0 / depth) for c in trans['acescg']])]
            for channel, value, socket in zip('RGB', numbers, colour.inputs, strict=False):
                number = new('ShaderNodeValue', 'Transmittance ' + channel + ' #' + str(index))
                number.outputs[0].default_value = value
                links.new(number.outputs[0], socket)
            yellowing = record.get('yellowing')
            if yellowing and SETTINGS_GROUP in bpy.data.node_groups:
                # group version 38: the panel's slider Yellowing (one value in the settings group for the whole
                # file) blends the transmittance towards the record's yellowing end - 20 Nature (materials version
                # 16; user 06.11.2026: „Das Material braucht einen Regler für den Vergilbungseffekt.“)
                end = new('ShaderNodeCombineColor', 'Yellow end #' + str(index))
                ydepth = yellowing.get('depth_mm', 4.0) or 4.0
                yellow = [max(v, 0.0) for v in from_acescg([max(c, 1e-6) ** (4.0 / ydepth)
                                                             for c in yellowing['acescg']])]
                for channel, value, socket in zip('RGB', yellow, end.inputs, strict=False):
                    number = new('ShaderNodeValue', 'Yellow ' + channel + ' #' + str(index))
                    number.outputs[0].default_value = value
                    links.new(number.outputs[0], socket)
                settings = settings or new('ShaderNodeGroup', 'Physical Settings')
                settings.node_tree = bpy.data.node_groups[SETTINGS_GROUP]
                blend = new('ShaderNodeMix', 'Yellowing #' + str(index))
                blend.data_type = 'RGBA'
                links.new(settings.outputs['Yellowing'], blend.inputs['Factor'])
                links.new(colour.outputs[0], blend.inputs[6])
                links.new(end.outputs[0], blend.inputs[7])
                t = settings.node_tree.nodes['Yellowing'].outputs[0].default_value
                numbers = [a + (b - a) * t for a, b in zip(numbers, yellow, strict=True)]
                colour_source = blend.outputs[2]
            if VIEWPORT not in material:                  # Solid view shows the glass in its own colour (restored)
                material[VIEWPORT] = list(material.diffuse_color)
            material.diffuse_color = [min(v, 1.0) for v in numbers] + [material.diffuse_color[3]]
        else:
            colour = new('ShaderNodeRGB', 'Colour #' + str(index))          # until part 4b '(<source>)' followed
            colour.outputs[0].default_value = record_working_colour(record) + [1.0]
            if index == 1:                                # Solid view shows the physical colour
                if VIEWPORT not in material:
                    material[VIEWPORT] = list(material.diffuse_color)
                rgb = record_working_colour(record)
                material.diffuse_color = [min(v, 1.0) for v in rgb] + [material.diffuse_color[3]]
        rough = new('ShaderNodeValue', 'Roughness #' + str(index))
        rough.outputs[0].default_value = record['roughness']
        if cust is not None:
            # his colour variation (Advanced: a group between Customize's Color Variation and the base's Color): the
            # physical colour goes through a second instance of it, its Variation from the same live source - for every
            # class, as in his look. At Variation 0 it passes a colour through unchanged, glass colours and values
            # above 1 included (run 153 test_colour_variation.py: emission values, max difference 1e-6)
            feed = base.inputs['Color'].links[0].from_node if ('Color' in base.inputs
                                                                 and base.inputs['Color'].is_linked) else None
            if (feed is not None and feed.bl_idname == 'ShaderNodeGroup' and 'Variation' in feed.inputs
                    and 'Color' in feed.inputs and feed.inputs['Variation'].is_linked):
                vary = new('ShaderNodeGroup', 'Colour variation #' + str(index))
                vary.node_tree = feed.node_tree
                links.new(feed.inputs['Variation'].links[0].from_socket, vary.inputs['Variation'])
                links.new(colour_source or colour.outputs[0], vary.inputs['Color'])
                colour_source = vary.outputs['Color']
        links.new(colour_source or colour.outputs[0], phys.inputs['Color'])
        scaled = None
        roughness = rough.outputs[0]
        if psurface is not None:                       # the micro surface lowers the roughness (Müller: 0.4 -> 0.25)
            scaled = new('ShaderNodeMath', 'Roughness #' + str(index) + ' x surface')
            scaled.operation = 'MULTIPLY'
            links.new(rough.outputs[0], scaled.inputs[0])
            links.new(psurface.outputs['Roughness Factor'], scaled.inputs[1])
            roughness = scaled.outputs[0]
        if rough_delta is not None:                    # Customize's fingerprints and dirt on top (Advanced)
            plus = new('ShaderNodeMath', 'Roughness #' + str(index) + ' + Customize')
            plus.operation, plus.use_clamp = 'ADD', True
            links.new(roughness, plus.inputs[0])
            links.new(rough_delta.outputs[0], plus.inputs[1])
            roughness = plus.outputs[0]
        links.new(roughness, phys.inputs['Roughness'])
        links.new(surface.outputs['Normal'], phys.inputs['Normal'])
        if 'Height' in surface.outputs:
            links.new(surface.outputs['Height'], phys.inputs['Height'])
        if psurface is not None and 'Grease' in phys.inputs and 'Grease' in psurface.outputs:
            # a faint, very rough second reflection (solid plastic)
            links.new(psurface.outputs['Grease'], phys.inputs['Grease'])
        if 'Scale' in phys.inputs:
            links.new(scale.outputs[0], phys.inputs['Scale'])
        if 'IOR' in phys.inputs:
            phys.inputs['IOR'].default_value = record['ior']
        if 'Abbe Number' in phys.inputs:              # dispersion (group version 37); a record without one: none
            phys.inputs['Abbe Number'].default_value = record.get('abbe', 0.0)
        if kind in ('solid', 'speckle', 'glitter_opaque'):
            phys.inputs['SSS Depth'].default_value = record['sss']['depth_mm']
            own = record['sss'].get('radius')
            if own and 'SSS Own Radius' in phys.inputs:  # its own scatter radius per channel (group version 39, 358)
                phys.inputs['SSS Radius'].default_value = own
                phys.inputs['SSS Own Radius'].default_value = 1.0
        if kind == 'speckle' and 'particles' in record:  # particles from the record
            for name, key in PARTICLE_INPUTS.items():
                phys.inputs[name].default_value = record['particles'].get(key, PARTICLE_DEFAULTS.get(key))
            particle = from_acescg(record['particles']['acescg'])
            phys.inputs['Particle Color'].default_value = [max(v, 0.0) for v in particle] + [1.0]
        if kind == 'glitter_opaque':                     # the glitter's foil flakes on the opaque core (group v36)
            for name, key in FLAKE_INPUTS.items():
                if name in phys.inputs:
                    phys.inputs[name].default_value = record['flakes'].get(key, FLAKE_DEFAULTS.get(key))
        if kind in GLASS:
            sigma = record['haze']['sigma_mm']
            top = max(sigma) or 1.0
            phys.inputs['Haze Color'].default_value = to_working([s / top for s in sigma]) + [1.0]   # sigma: Rec.709
            phys.inputs['Haze Density'].default_value = max(sigma)
            phys.inputs['Haze Anisotropy'].default_value = record['haze']['anisotropy']
            # fluorescence (UPDATES #85): a gain of the volume's scattering in the class group - it follows the light
            # that falls on the part. Until group version 17 an Emission of fixed strength in the volume, which shone
            # in the dark
            glow = record.get('glow') or {}
            if 'Glow Strength' in phys.inputs:
                phys.inputs['Glow Strength'].default_value = glow.get('strength', 0.0)
                if glow:
                    phys.inputs['Glow Color'].default_value = [max(v, 0.0) for v in from_acescg(glow['acescg'])] + [1.0]
            for name, key in FLAKE_INPUTS.items():           # glitter: foil flakes from the record
                if name in phys.inputs and 'flakes' in record:
                    phys.inputs[name].default_value = record['flakes'].get(key, FLAKE_DEFAULTS.get(key))
            if 'Fine Color' in phys.inputs:                  # glitter (group version 37): the fine fraction's bright
                # resin hue, colour x 0.8 / its largest channel (run 88g) - until 36 a chain of nodes in the group
                resin = numbers if trans else record_working_colour(record)
                top = max(resin)
                phys.inputs['Fine Color'].default_value = [0.8 * v / top if top > 0 else 0.0 for v in resin] + [1.0]
            for name, key in IRIDESCENCE_INPUTS.items():     # opal: platelets from the record
                if name in phys.inputs and 'iridescence' in record:
                    phys.inputs[name].default_value = record['iridescence'][key]
            for name in ('Diffuse Fac', 'Emission'):      # neon and glow colours: typed on the Mecabricks node
                if name in base.inputs and name in phys.inputs and not base.inputs[name].is_linked:
                    phys.inputs[name].default_value = base.inputs[name].default_value
            volume = phys
        for name, key in EFFECT_INPUTS.items():           # pearl, metallic, chrome
            if name in phys.inputs and key in record.get('effect', {}):   # presence, never truthiness: coat 0
                phys.inputs[name].default_value = effect_value(key, record['effect'][key])
        if 'Flake Own Color' in phys.inputs:              # group version 43, as SSS Own Radius (39): the metallic
            # share in the record's own Flake Color where it has one, else in the body colour, which arrives through a
            # link and so cannot be copied into Flake Color
            phys.inputs['Flake Own Color'].default_value = 1.0 if 'flake_acescg' in record.get('effect', {}) else 0.0
        for name in ('Shader',) + EEVEE_PARAMS:
            target = pmix.inputs.get(name + str(index))
            if target is None:
                continue
            for link in list(target.links):
                links.remove(link)
            if name in phys.outputs:
                links.new(phys.outputs[name], target)
        shaders.append(phys)
        if 'Eevee Base' in phys.inputs:                # glitter, opal, speckle: their effect in Eevee too (#61)
            effects.append((phys, kind))
    # Eevee follows: the library's own Eevee shader (rb_phys_eevee, group version 40), fed as the material's Eevee
    # Shader group is - by the physical mix instead of the Mecabricks mix, every other input (Scale, the baked bevel map
    # of an import with Eevee Bevel Maps) from the same source - and with the subsurface radius and depth the solid
    # group renders with in Cycles. Until 39 a second instance of the material's own Eevee group
    peevee = new('ShaderNodeGroup', 'Physical Eevee')
    own = bpy.data.node_groups.get(EEVEE_GROUP)
    peevee.node_tree = own if own is not None else eevee.node_tree
    for link in [l for l in links if l.to_node == eevee]:
        source = pmix.outputs[link.from_socket.name] if link.from_node == mix else link.from_socket
        target = (peevee.inputs.get(link.to_socket.name) if own is not None
                  else input_of(peevee, link.to_socket.identifier))
        if target is not None:
            links.new(source, target)
    if reading.normal_map is not None and own is not None and not peevee.inputs['Normal Map'].is_linked:
        links.new(reading.normal_map, peevee.inputs['Normal Map'])
    if reading.normal_map_tree is not None and own is not None and not peevee.inputs['Normal Map'].is_linked:
        # Advanced: his part normal maps and Mecabricks' bevel maps live in the material's Eevee group - an instance
        # of that group (no inputs) gives them to the library's Eevee shader, as Dev's baked bevel map
        nmap = new('ShaderNodeGroup', 'Physical Eevee Normal Map')
        nmap.node_tree = reading.normal_map_tree
        links.new(nmap.outputs[0], peevee.inputs['Normal Map'])
    if eevee is None:                               # Lite: no Eevee group - its values from the physical mix
        for name in EEVEE_PARAMS:
            if name in pmix.outputs and peevee.inputs.get(name) is not None:
                links.new(pmix.outputs[name], peevee.inputs[name])
        if peevee.inputs.get('Scale') is not None:
            links.new(scale.outputs[0], peevee.inputs['Scale'])
    first = next((p for p in shaders if 'SSS Radius' in p.outputs), None)
    if own is not None and first is not None:
        links.new(first.outputs['SSS Radius'], peevee.inputs['SSS Radius'])
        links.new(first.outputs['SSS Scale'], peevee.inputs['SSS Scale'])
    if out_c is None or out_e is None:
        # Lite has one output for both engines: the network brings its own for Cycles and Eevee. Blender takes the
        # output of the exact target before one for all (node_shader_tree.cc 241-247, ntreeShaderOutputNode), so
        # Lite's output stays as it is; the way back deletes these with the network
        out_c = new('ShaderNodeOutputMaterial', 'Output Cycles')
        out_c.target = 'CYCLES'
        out_e = new('ShaderNodeOutputMaterial', 'Output Eevee')
        out_e.target = 'EEVEE'
    for link in list(out_c.inputs['Surface'].links) + list(out_e.inputs['Surface'].links):
        links.remove(link)
    links.new(pmix.outputs['Shader'], out_c.inputs['Surface'])
    links.new(peevee.outputs['Shader'], out_e.inputs['Surface'])
    if volume is not None and single_glass:
        links.new(volume.outputs['Volume'], out_c.inputs['Volume'])
        # Eevee: glass goes through the library's Eevee shader like every other part (Physical Eevee above). It refracts
        # a LEGO part as the shell it is: the wall at the Eevee output's Thickness, in the part's space (mm). Unlinked,
        # Eevee takes the object's smallest bounding-box side (eevee_shader.cc:1405-1424) and a 2x2 brick refracted
        # like a 10 mm block, dark and dense (run 148: ΔE to Cycles 10.1 -> 7.4 with the wall alone)
        wall = new('ShaderNodeValue', 'Physical Wall Thickness')
        wall.outputs[0].default_value = EEVEE_WALL_MM
        links.new(wall.outputs[0], out_e.inputs['Thickness'])
    # Effects in Eevee: glitter flakes, opal platelets and speckle flecks laid over the Mecabricks Eevee shader
    # (Physical Eevee) by their class
    # group - in a second instance used by the Eevee output only (the Eevee shader linked into the instance Cycles
    # renders turned the part black in Cycles); same inputs, so the effect sits where Cycles has it. Single colour only
    if len(effects) == 1 and len(set(ids)) == 1:
        phys, kind = effects[0]
        eff = new('ShaderNodeGroup', 'Physical ' + kind.title() + ' for Eevee')
        eff.node_tree = phys.node_tree
        for socket in phys.inputs:
            target = next((x for x in eff.inputs if x.identifier == socket.identifier), None)
            if target is None:
                continue
            if socket.is_linked:
                links.new(socket.links[0].from_socket, target)
            elif hasattr(socket, 'default_value'):
                target.default_value = socket.default_value
        links.new(peevee.outputs['Shader'], eff.inputs['Eevee Base'])
        for link in list(out_e.inputs['Surface'].links):
            links.remove(link)
        links.new(eff.outputs['Eevee Effect'], out_e.inputs['Surface'])
    # Phosphorescence (UPDATES #74): the afterglow of a glow-in-the-dark colour, added to the Cycles and the Eevee
    # surface; it shines only while the scene's Glow in the dark is on (strength = record strength x Glow strength)
    glowing = recs[0].get('phosphorescence') if len(set(ids)) == 1 and recs and recs[0] else None
    if glowing and glowing.get('strength', 0) > 0:
        emit = new('ShaderNodeEmission', 'Physical Afterglow')
        emit.inputs['Color'].default_value = [max(v, 0.0) for v in from_acescg(glowing['acescg'])] + [1.0]
        emit[AFTERGLOW] = glowing['strength']
        emit.inputs['Strength'].default_value = afterglow_strength(glowing['strength'])
        for out in (out_c, out_e):
            source = out.inputs['Surface'].links[0].from_socket if out.inputs['Surface'].is_linked else None
            add = new('ShaderNodeAddShader', 'Physical Afterglow + ' + ('Cycles' if out == out_c else 'Eevee'))
            if source is not None:
                links.new(source, add.inputs[0])
            links.new(emit.outputs[0], add.inputs[1])
            links.new(add.outputs[0], out.inputs['Surface'])
    for host_nodes in after:
        host_nodes(material)
    layout(tree, made)                             # the steps and their frames: layout.network_columns
    return True
