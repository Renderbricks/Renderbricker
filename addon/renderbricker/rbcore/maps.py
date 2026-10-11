"""Bevel maps for EEVEE, baked from the smooth copies (UPDATES #40).

EEVEE has no Bevel node. The importer shows Mecabricks' baked normal map there instead - made for the coarse import
mesh, 256 px, with scalloped round rims. Here the map is made from the smooth copy itself: the normals Cycles' Bevel
node gives on the render copy, with the bevel of the part's own material, written into a normal map the material
uses on the copies (maintainer, 2026-10-11: "Das hochaufgelöste Mesh ist die neue Quelle." - "Es geht nur darum,
dass die saubere Rundung in die Map kommt.").

    find_maps      where a part's material reads its normal map: a node group whose output comes from a tangent
                   Normal Map node fed by one image (the importer's mb_normal_texture). Anything built differently
                   is left alone.
    bevel_tree     the part's Bevel node with the radius its material gives it, as a node group of its own.
    mark_copy      the copies of a part with a map carry the mesh attribute rb_smooth_map. Its value is a number of
                   the part's shape (from rb_src), so a copy only ever switches to a map made for its own shape.
    fit_maps       make the map (small Cycles bakes on the processor, in a scene of its own, and some arithmetic -
                   see "the bake") and build the switch into the group: Attribute -> is it this shape? -> Mix between
                   the importer's colour and the new image, in front of the Normal Map node. The import mesh has no
                   attribute and keeps Mecabricks' map.
    drop_unused_maps   a switch lives as long as a marked copy of its shape exists; then the group is put back as
                   it was and the image removed.

One material serves the import mesh and its copies, and all colours of a part share one group - nothing is copied.
The images are packed into the scene file. This module needs nothing of the modules below it: the callers hand in
(import mesh, render copy, world matrix of one of its objects).
"""
import time

import bmesh
import bpy
import numpy as np

from . import config, workscene

ATTR = "rb_smooth_map"          # mesh attribute of the copies (Float, per point): the number of the shape
MARK = "rb_map"                 # the same number as a property of the copy (readable without the geometry)
NODE = "rb_map_"                # names of the nodes of a switch
IMAGE_OF, IMAGE_SRC = "rb_map_of", "rb_map_src"     # image: the importer's image it stands in for, the shape
MAP_SCENE = "RB map scene"
FRAME_TEXT = "Renderbricker: bevel map baked from the smooth copy"

SMOOTH_MAPS = config.opt("--smooth-maps", "0") == "1"     # set by the add-on or the command line
# The map is as large as the importer's map (mostly 256 px): about a second a part. Twice and four times that size
# were built and taken out again - "Original klappt wie gewünscht ... Das reicht für EEVEE aus." (maintainer,
# 2026-10-11; measured in run 261: 0.9 / 0.5 / 0.4 degrees to the Bevel node, 1.1 / 1.9 / 5.1 s a part).
BEVEL_SAMPLES = 64              # per texel of the bevel pass (16: 1.2 instead of 0.9 degrees)
FRAME_SAMPLES = 4               # the frame passes are plain shading normals
CHECK_SAMPLES = 16              # the second look at texels that several faces share
CONFLICT_ANGLE = 12.0           # degrees: faces sharing a texel that want normals further apart than this
NO_PLACE = 1e-3                 # a face with less than this share of the part's mean texel density has no place


class NoBevel(Exception):
    """The part's material has no Bevel node this module can read."""


class Slot:
    """One normal map of a part: the group, its Normal Map node, the image node in front of it, the UV layer."""

    def __init__(self, tree, normal, image_node, uv):
        self.tree, self.normal, self.image_node, self.uv = tree, normal, image_node, uv
        self.image = image_node.image


def _socket(sockets, identifier):
    return next(s for s in sockets if s.identifier == identifier)


def _images_before(sock, seen=None):
    """The image nodes that feed a socket inside its tree; through a switch only the importer's side."""
    seen = set() if seen is None else seen
    out = []
    for l in sock.links:
        n = l.from_node
        if n in seen:
            continue
        seen.add(n)
        if n.type == 'TEX_IMAGE':
            if n.image is not None:
                out.append(n)
        elif n.name == NODE + "mix":
            out += _images_before(_socket(n.inputs, "A_Color"), seen)
        elif n.type != 'GROUP':
            for i in n.inputs:
                out += _images_before(i, seen)
    return out


def _uv_of(image_node):
    """Name of the UV layer an image node reads ("" = the layer active for rendering), None: not a plain UV."""
    links = image_node.inputs["Vector"].links
    if not links:
        return ""
    n = links[0].from_node
    return n.uv_map if n.type == 'UVMAP' else None


def _slot_of(tree):
    out = next((n for n in tree.nodes if n.type == 'GROUP_OUTPUT' and n.inputs and n.inputs[0].links), None)
    if out is None:
        return None
    normal = out.inputs[0].links[0].from_node
    if normal.type != 'NORMAL_MAP' or normal.space != 'TANGENT':
        return None
    if normal.inputs["Strength"].links or abs(normal.inputs["Strength"].default_value - 1.0) > 1e-6:
        return None                         # the new map holds the whole tilt: a strength would scale it again
    images = _images_before(normal.inputs["Color"])
    if len(images) != 1:
        return None
    uv = _uv_of(images[0])
    if uv is None or (normal.uv_map and uv and normal.uv_map != uv):
        return None
    return Slot(tree, normal, images[0], uv or normal.uv_map)


def _trees_behind(tree, target):
    """The node groups that feed the material outputs of one render engine (target 'EEVEE' or 'CYCLES'; an output
    for all engines counts for both), with the groups inside them."""
    found = set()

    def inside(t, depth):
        for n in t.nodes:
            if n.type == 'GROUP' and n.node_tree is not None and n.node_tree not in found and depth < 8:
                found.add(n.node_tree)
                inside(n.node_tree, depth + 1)

    todo = [n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.target in (target, 'ALL')]
    seen = set(todo)
    while todo:
        n = todo.pop()
        if n.type == 'GROUP' and n.node_tree is not None and n.node_tree not in found:
            found.add(n.node_tree)
            inside(n.node_tree, 0)
        for i in n.inputs:
            for l in i.links:
                if l.from_node not in seen:
                    seen.add(l.from_node)
                    todo.append(l.from_node)
    return found


def find_maps(orig):
    """The normal maps of a part (Slot), one per group, found through the materials of its import mesh. Only maps
    the material reads for EEVEE alone: a tangent normal map that Cycles reads too (the part's own detail map -
    the hair 25379, the textiles 66830 and 66831) is not ours to replace."""
    slots, seen = [], set()

    def walk(tree, depth, eevee, cycles):
        for n in tree.nodes:
            if n.type != 'GROUP' or n.node_tree is None or n.node_tree in seen:
                continue
            seen.add(n.node_tree)
            s = _slot_of(n.node_tree)
            if s is not None:
                if n.node_tree in eevee and n.node_tree not in cycles:
                    slots.append(s)
            elif depth < 8:
                walk(n.node_tree, depth + 1, eevee, cycles)

    for mt in orig.materials:
        if mt is not None and mt.node_tree is not None:
            walk(mt.node_tree, 0, _trees_behind(mt.node_tree, 'EEVEE'), _trees_behind(mt.node_tree, 'CYCLES'))
    return slots


# ---------------------------------------------------------------- the part's bevel
def find_bevel(orig):
    """(Bevel node, the group nodes that lead to it from the material's tree) - the first one found, or None."""
    def walk(tree, stack):
        for n in tree.nodes:
            if n.type == 'BEVEL' and not n.mute:
                return n, stack
        for n in tree.nodes:
            if n.type == 'GROUP' and n.node_tree is not None and len(stack) < 8 and n not in stack:
                found = walk(n.node_tree, stack + [n])
                if found:
                    return found
        return None

    for mt in orig.materials:
        if mt is not None and mt.node_tree is not None:
            found = walk(mt.node_tree, [])
            if found:
                return found
    return None


def _feed(wrap, to_sock, sock, stack, depth=0):
    """Give `to_sock` (in the new tree) what `sock` gets in the material: its value, or copies of the Value, Math
    and group nodes in front of it. A group's input is followed out to the node that fills it one level up."""
    if depth > 16:
        raise NoBevel("the radius is wired too deep")
    if not sock.links:
        to_sock.default_value = sock.default_value
        return
    src, src_out = sock.links[0].from_node, sock.links[0].from_socket
    if src.type == 'GROUP_INPUT':
        if not stack:
            raise NoBevel("the radius comes from outside the material")
        _feed(wrap, to_sock, _socket(stack[-1].inputs, src_out.identifier), stack[:-1], depth + 1)
    elif src.type == 'REROUTE':
        _feed(wrap, to_sock, src.inputs[0], stack, depth + 1)
    elif src.type == 'VALUE':
        to_sock.default_value = src.outputs[0].default_value
    elif src.type == 'MATH':
        n = wrap.nodes.new("ShaderNodeMath")
        n.operation, n.use_clamp = src.operation, src.use_clamp
        for i, s in enumerate(src.inputs):
            _feed(wrap, n.inputs[i], s, stack, depth + 1)
        wrap.links.new(n.outputs[0], to_sock)
    elif src.type == 'GROUP' and src.node_tree is not None:
        n = wrap.nodes.new("ShaderNodeGroup")
        n.node_tree = src.node_tree
        for i, s in enumerate(src.inputs):
            _feed(wrap, n.inputs[i], s, stack, depth + 1)
        wrap.links.new(_socket(n.outputs, src_out.identifier), to_sock)
    else:
        raise NoBevel(f"the radius comes from a {src.bl_label} node")


def bevel_tree(orig):
    """A node group with one output: the normal of the part's Bevel node, with the radius and the samples the
    material gives it (Renderbricks Dev: Bevel 0.35 x the scale of the import). Raises NoBevel."""
    found = find_bevel(orig)
    if found is None:
        raise NoBevel("no Bevel node in the material")
    node, stack = found
    if node.inputs["Normal"].links:
        raise NoBevel("the Bevel node bevels another normal")
    wrap = bpy.data.node_groups.new("RB bevel", "ShaderNodeTree")
    try:
        wrap.interface.new_socket("Normal", in_out='OUTPUT', socket_type='NodeSocketVector')
        out = wrap.nodes.new("NodeGroupOutput")
        bevel = wrap.nodes.new("ShaderNodeBevel")
        bevel.samples = node.samples
        _feed(wrap, bevel.inputs["Radius"], node.inputs["Radius"], stack)
        wrap.links.new(bevel.outputs["Normal"], out.inputs[0])
    except Exception:
        bpy.data.node_groups.remove(wrap)
        raise
    return wrap


# ---------------------------------------------------------------- the mark on the copies
def map_value(src):
    """The number of a shape (rb_src): 1 to 65,536. Small on purpose - the Attribute node hands it on as the average
    of three channels, and for numbers in the millions that average is off by up to 1 in a 32-bit float: the
    comparison in the switch failed for the whole part (run 264: 80179 and 11609 never showed their map)."""
    return float(1 + int(src[:4], 16))


def is_marked(cp):
    return bool(cp.get(MARK)) and ATTR in cp.attributes


def mark_copy(cp, orig):
    """A copy baked just now gets the mark when its part has a map (bake_copy, with SMOOTH_MAPS)."""
    if not cp.get("rb_src") or not find_maps(orig):
        return False
    value = map_value(cp["rb_src"])
    at = cp.attributes.get(ATTR) or cp.attributes.new(ATTR, 'FLOAT', 'POINT')
    at.data.foreach_set("value", np.full(len(cp.vertices), value, np.float32))
    cp[MARK] = value
    return True


def mark_existing(orig, cps):
    """Copies converted before the option was on: marked now. False when one of them cannot be - a copy in the cache
    file is not ours to change here, its part is converted again."""
    if not find_maps(orig):
        return True
    for cp in cps:
        if is_marked(cp):
            continue
        if cp.library is not None or cp.override_library is not None:
            return False
        mark_copy(cp, orig)
    return True


# ---------------------------------------------------------------- the switch in the importer's group
def _trees():
    yield from bpy.data.node_groups
    for mt in bpy.data.materials:
        if mt.node_tree is not None:
            yield mt.node_tree


def switch_of(tree):
    """The nodes of the switch in a tree ({short name: node}), None without one."""
    found = {n.name[len(NODE):]: n for n in tree.nodes if n.name.startswith(NODE)}
    return found if "mix" in found else None


def _switch_image(sw):
    return sw["image"].image if "image" in sw else None


def _switch_src(sw):
    """The shape (rb_src) the switch's image was made for; None without an image."""
    img = _switch_image(sw)
    return img.get(IMAGE_SRC) if img is not None else None


def build_switch(slot, image, src):
    """Attribute -> "is it this shape?" -> Mix in front of the Normal Map node; laid out below the importer's nodes,
    in a frame of its own."""
    nodes, links = slot.tree.nodes, slot.tree.links
    before = slot.normal.inputs["Color"].links[0].from_socket
    low = min(n.location.y - max(n.height, 260.0) for n in nodes)
    x0, y0 = slot.normal.location.x - 180.0, low - 140.0     # the Mix node: below the gap in front of the Normal Map

    frame = nodes.new("NodeFrame")
    frame.name, frame.label, frame.label_size = NODE + "frame", FRAME_TEXT, 14

    def new(kind, short, label, dx, dy, width):
        n = nodes.new(kind)
        n.name, n.label, n.parent, n.width = NODE + short, label, frame, width
        n.location = (x0 + dx, y0 + dy)
        return n

    attr = new("ShaderNodeAttribute", "attribute", "Copy mark", -480.0, -320.0, 170.0)
    attr.attribute_type, attr.attribute_name = 'GEOMETRY', ATTR
    same = new("ShaderNodeMath", "shape", "This shape?", -250.0, -320.0, 170.0)
    same.operation = 'COMPARE'
    same.inputs[1].default_value, same.inputs[2].default_value = map_value(src), 0.5
    img = new("ShaderNodeTexImage", "image", "Bevel map of the smooth copy", -480.0, 0.0, 240.0)
    img.image = image
    img.interpolation, img.extension = slot.image_node.interpolation, slot.image_node.extension
    img.projection = slot.image_node.projection
    mix = new("ShaderNodeMix", "mix", "Import: A, copy: B", 0.0, -40.0, 160.0)
    mix.data_type, mix.blend_type, mix.clamp_factor = 'RGBA', 'MIX', True
    for l in slot.image_node.inputs["Vector"].links:
        links.new(l.from_socket, img.inputs["Vector"])
    links.new(attr.outputs["Fac"], same.inputs[0])
    links.new(same.outputs[0], _socket(mix.inputs, "Factor_Float"))
    links.new(before, _socket(mix.inputs, "A_Color"))
    links.new(img.outputs["Color"], _socket(mix.inputs, "B_Color"))
    links.new(_socket(mix.outputs, "Result_Color"), slot.normal.inputs["Color"])
    for n in (attr, img, mix):
        for s in list(n.outputs) + list(n.inputs):
            if not s.is_linked and s.enabled:
                s.hide = True


def remove_switch(tree):
    """The group as the importer made it: the Normal Map node reads its old colour again, our nodes go."""
    sw = switch_of(tree)
    if sw is None:
        return None
    mix = sw["mix"]
    a = _socket(mix.inputs, "A_Color").links
    if a:
        for l in list(_socket(mix.outputs, "Result_Color").links):
            tree.links.new(a[0].from_socket, l.to_socket)
    image = _switch_image(sw)
    for n in [n for n in tree.nodes if n.name.startswith(NODE)]:
        tree.nodes.remove(n)
    return image


def baked_maps():
    return [i for i in bpy.data.images if i.get(IMAGE_OF)]


def _drop_unused_images():
    for img in baked_maps():
        if img.users == 0 or (img.users == 1 and img.use_fake_user):
            bpy.data.images.remove(img)


def drop_unused_maps(everything=False):
    """Switches whose shape has no marked copy left (everything: all of them) are taken out and their images
    removed. Returns the number of switches removed."""
    live = set() if everything else {m["rb_src"] for m in bpy.data.meshes
                                    if m.get("rb_original") and m.get(MARK) and m.get("rb_src")}
    n = 0
    for tree in list(_trees()):
        sw = switch_of(tree)
        if sw is not None and _switch_src(sw) not in live:
            remove_switch(tree)
            n += 1
    _drop_unused_images()
    return n


# ---------------------------------------------------------------- the bake
# What the map has to hold: the normal the Bevel node gives on the render copy, written in the copy's tangent space.
# Per texel, from plain object-space normal bakes of the copy alone:
#     S   what the copy shows with the Bevel node       Nc  its shading normal
#     T, B  its tangent and bitangent, as the render has them
#     S = x T + y B + z Nc   solved for the colour (x, y, z)
# Not Blender's tangent bake: it takes the FACE normal for faces marked sharp (bake.cc,
# RE_bake_normal_world_to_tangent) while the render takes the custom normals, and every face of an import and of a
# copy is marked sharp (run 260: a map baked onto its own mesh came back with stripes of 3 degrees).
# Two kinds of texels stay flat (the copy's own normal, no bevel):
#   - under faces without a place in the map: their UVs are collapsed (26047: the whole stud lies in less than a texel
#     at the map's corner). Such a face reads one texel with a broken frame; a tilted normal there made the stud dark.
#   - where faces share a texel and want different normals. Mecabricks lays mirrored halves over each other - they
#     want the same colour and share it. Found by baking the copy a second time with its faces in reverse order;
#     only areas count: on the outline of an island the two bakes pick different faces at single texels (run 262:
#     1 % of the covered texels, all on the bevels - left flat they would be holes in the rounding).
def _plain_copy(name, mesh, uv, scene, matrix=None):
    """A local object with a copy of a mesh (an override from the cache file cannot be a bake target)."""
    tmp = bpy.data.objects.new(name + " tmp", mesh)
    try:
        me = bpy.data.meshes.new_from_object(tmp, preserve_all_data_layers=True)
    finally:
        bpy.data.objects.remove(tmp)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    if matrix is not None:
        ob.matrix_world = matrix            # the bevel's radius counts in the scene's space
    layer = me.uv_layers.get(uv) if uv else next((u for u in me.uv_layers if u.active_render), None)
    if layer is None:
        return ob, False
    me.uv_layers.active = layer
    layer.active_render = True
    me.materials.clear()
    return ob, True


def _reversed(ob, scene):
    """The same object with its faces in reverse order: where faces share a texel, a bake shows the other one."""
    me = ob.data.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        n = len(bm.faces)
        for f in bm.faces:
            f.index = n - 1 - f.index
        bm.faces.sort()
        bm.to_mesh(me)
    finally:
        bm.free()
    twin = bpy.data.objects.new(ob.name + " reversed", me)
    scene.collection.objects.link(twin)
    twin.matrix_world = ob.matrix_world.copy()
    return twin


def _material(name, image):
    """A plain material that bakes into `image`; returns (material, its shader node). A Diffuse BSDF: it takes
    the normal as it comes - a glossy one bends normals that tilt far from the face (valid reflection)."""
    mt = bpy.data.materials.new(name)
    if mt.node_tree is None:
        mt.use_nodes = True
    nt = mt.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = image
    nt.nodes.active = tex
    return mt, bsdf


def _map_scene():
    sc = bpy.data.scenes.get(MAP_SCENE) or bpy.data.scenes.new(MAP_SCENE)
    sc.render.engine = 'CYCLES'             # raises without the Cycles add-on
    sc.cycles.device, sc.cycles.samples = 'CPU', FRAME_SAMPLES     # small maps: a GPU mostly adds its start (run 261)
    bk = sc.render.bake
    bk.use_selected_to_active, bk.use_clear, bk.target, bk.margin = False, True, 'IMAGE_TEXTURES', 0
    bk.normal_space, bk.normal_r, bk.normal_g, bk.normal_b = 'OBJECT', 'POS_X', 'POS_Y', 'POS_Z'
    return sc


def drop_map_scene():
    sc = bpy.data.scenes.get(MAP_SCENE)
    if sc is not None and len(bpy.data.scenes) > 1:
        workscene.remove_scene(sc, empty_only=True)


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=1), 1e-9)[:, None]


def _shown(sc, ob, w, h, group=None, colour=None, uv="", samples=FRAME_SAMPLES):
    """Object-space normals an object shows, per texel (h*w, 3), and which texels it covers. group: with this normal
    group in the material; colour: with a tangent Normal Map node of this constant colour (the tangent frame)."""
    img = bpy.data.images.new("RB map pass", w, h, alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    mt, bsdf = _material("RB map pass", img)
    nt = mt.node_tree
    if group is not None:
        g = nt.nodes.new("ShaderNodeGroup")
        g.node_tree = group
        nt.links.new(g.outputs[0], bsdf.inputs["Normal"])
    elif colour is not None:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.space, nm.uv_map = 'TANGENT', uv
        nm.inputs["Color"].default_value = (*colour, 1.0)
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    sc.cycles.samples = samples
    try:
        ob.data.materials.clear()
        ob.data.materials.append(mt)
        with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0], active_object=ob, object=ob,
                                       selected_objects=[ob], selected_editable_objects=[ob]):
            r = bpy.ops.object.bake(type='NORMAL')
        if r != {'FINISHED'}:
            raise RuntimeError(f"bake {r}")
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
    finally:
        ob.data.materials.clear()
        bpy.data.materials.remove(mt)
        bpy.data.images.remove(img)
    n = px.reshape(-1, 4)[:, :3] * 2.0 - 1.0
    length = np.linalg.norm(n, axis=1)
    covered = np.abs(length - 1.0) < 0.2
    return n / np.maximum(length, 1e-9)[:, None], covered


def _spread(values, covered, w, h, steps):
    """Carry values from covered texels to their uncovered neighbours, `steps` texels far (the margin of a bake)."""
    v, m = values.reshape(h, w, -1).copy(), covered.reshape(h, w).copy()
    for _k in range(steps):
        if m.all():
            break
        acc, cnt = np.zeros_like(v), np.zeros((h, w), np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a = (slice(1, None) if dy == 1 else slice(None, -1) if dy == -1 else slice(None),
                 slice(1, None) if dx == 1 else slice(None, -1) if dx == -1 else slice(None))
            b = (slice(None, -1) if dy == 1 else slice(1, None) if dy == -1 else slice(None),
                 slice(None, -1) if dx == 1 else slice(1, None) if dx == -1 else slice(None))
            acc[a] += v[b] * m[b][..., None]
            cnt[a] += m[b]
        new = ~m & (cnt > 0)
        v[new] = acc[new] / cnt[new][:, None]
        m |= new
    return v.reshape(-1, values.shape[1]), m.ravel()


def _areas(mask):
    """A mask (2D) without its thin parts: only texels whose eight neighbours are set too, and their neighbours."""
    core = mask.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                core &= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    core[0, :] = core[-1, :] = core[:, 0] = core[:, -1] = False
    out = core.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out |= np.roll(np.roll(core, dy, axis=0), dx, axis=1)
    return out & mask


def no_place(me, uv_name, w, h):
    """Texels (h*w, bool) under faces that have no place in the map, and the share of the surface such faces have."""
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    tl = np.empty(n * 3, np.int64)
    me.loop_triangles.foreach_get("loops", tl)
    tv = np.empty(n * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tv)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[uv_name].data.foreach_get("uv", uv)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    t, p = uv.reshape(-1, 2)[tl.reshape(-1, 3)], co.reshape(-1, 3)[tv.reshape(-1, 3)]
    a_uv = 0.5 * np.abs((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1])
                        - (t[:, 2, 0] - t[:, 0, 0]) * (t[:, 1, 1] - t[:, 0, 1]))
    a_3d = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    mask = np.zeros((h, w), bool)
    if a_3d.sum() <= 0 or a_uv.sum() <= 0:
        return mask.ravel(), 0.0
    lost = (a_uv / np.maximum(a_3d, 1e-12) < NO_PLACE * a_uv.sum() / a_3d.sum()) & (a_3d > 0)
    lo = np.floor(t[lost].min(1) * (w, h) - 1.0).astype(int)
    hi = np.ceil(t[lost].max(1) * (w, h) + 1.0).astype(int)
    for (x0, y0), (x1, y1) in {(tuple(a), tuple(b)) for a, b in zip(lo.tolist(), hi.tolist())}:
        mask[max(y0, 0):min(y1, h - 1) + 1, max(x0, 0):min(x1, w - 1) + 1] = True
    return mask.ravel(), float(a_3d[lost].sum() / a_3d.sum())


def _tangent_colours(sc, ob, bevel, uv, w, h, samples):
    """(x, y, z) of the Bevel node's normal in the object's tangent frame per texel, where it could be solved, and
    the texels the object covers."""
    S, in_s = _shown(sc, ob, w, h, group=bevel, samples=samples)
    Nc, in_c = _shown(sc, ob, w, h)
    # the frame, read half way between the axis and the normal (a normal at 90 degrees to the face is no safe bake):
    # the render shows normalize(T + Nc), so T = 2 (shown . Nc) shown - Nc
    Tn, in_t = _shown(sc, ob, w, h, colour=(1.0, 0.5, 1.0), uv=uv)
    Bn, in_b = _shown(sc, ob, w, h, colour=(0.5, 1.0, 1.0), uv=uv)
    T = _unit(Tn * (2.0 * (Tn * Nc).sum(1))[:, None] - Nc)
    side = np.sign((np.cross(Nc, T) * Bn).sum(1))[:, None]
    frame = np.stack([T, np.cross(Nc, T) * np.where(side == 0, 1.0, side), Nc], axis=2)   # the render's bitangent
    ok = in_s & in_c & in_t & in_b & (np.abs(np.linalg.det(frame)) > 0.05)
    xyz = np.zeros_like(S)
    xyz[:, 2] = 1.0
    if ok.any():
        xyz[ok] = np.linalg.solve(frame[ok], S[ok][:, :, None])[:, :, 0]
    xyz[:, 2] = np.maximum(xyz[:, 2], 0.0)
    return _unit(xyz), ok, in_c


def map_colours(sc, target, bevel, uv, w, h):
    """The colours of the map (h*w, 3 in 0..1), the texels the copy covers, and a report of the texels left flat:
    {"no place": share of the surface, "shared": share of the covered texels}."""
    W, H = w, h
    xyz, ok, in_c = _tangent_colours(sc, target, bevel, uv, W, H, BEVEL_SAMPLES)
    lost, share = no_place(target.data, uv or target.data.uv_layers.active.name, W, H)
    # texels that faces share: once more with the faces the other way round
    twin = _reversed(target, sc)
    try:
        a, ok_a = xyz, ok
        b, ok_b, _c = _tangent_colours(sc, twin, bevel, uv, w, h, CHECK_SAMPLES)
    finally:
        me = twin.data
        bpy.data.objects.remove(twin)
        bpy.data.meshes.remove(me)
    apart = np.degrees(np.arccos(np.clip((a * b).sum(1), -1.0, 1.0))) > CONFLICT_ANGLE
    clash = _areas((ok_a & ok_b & apart).reshape(h, w))     # single texels on an island's outline are no clash
    clash = clash.ravel() & ~lost
    flat = in_c & (~ok | lost | clash)                  # covered, but nothing to write: the copy's own normal
    xyz[flat | lost] = (0.0, 0.0, 1.0)
    margin = max(2, W // 64)
    colours, filled = _spread(xyz * 0.5 + 0.5, in_c & ~lost, W, H, margin)
    colours[~filled | lost] = (0.5, 0.5, 1.0)
    rep = {"no place": share, "shared": float(clash[in_c].mean()) if in_c.any() else 0.0}
    return np.clip(colours, 0.0, 1.0), in_c, rep


def bake_map(slot, orig, rc, src, matrix=None):
    """The bevel map of the render copy `rc` of `orig` for a slot: a new packed image as large as the importer's.
    matrix: the world matrix of one of the part's objects. Raises NoBevel or RuntimeError."""
    w, h = slot.image.size
    if not w or not h:
        raise RuntimeError("the original map has no pixels")
    bevel = bevel_tree(orig)
    sc = _map_scene()
    target = None
    try:
        target, ok = _plain_copy("RB map target", rc, slot.uv, sc, matrix)
        if not ok:
            raise RuntimeError(f"UV layer {slot.uv!r} missing")
        colours, covered, rep = map_colours(sc, target, bevel, slot.uv, w, h)
    finally:
        if target is not None:
            me = target.data
            bpy.data.objects.remove(target)
            bpy.data.meshes.remove(me)
        bpy.data.node_groups.remove(bevel)
    if not covered.any():
        raise RuntimeError("the copy covers no texel of the map")
    image = bpy.data.images.new(f"{slot.image.name} bevel"[:63], w, h, alpha=False)
    image.colorspace_settings.name = slot.image.colorspace_settings.name
    rgba = np.concatenate([colours, np.ones((len(colours), 1), np.float32)], axis=1).astype(np.float32)
    image.pixels.foreach_set(rgba.ravel())
    image.pack()
    image[IMAGE_OF], image[IMAGE_SRC] = slot.image.name, src
    image["rb_map_no_place"], image["rb_map_shared"] = rep["no place"], rep["shared"]
    return image


def _todo(pairs):
    """(import mesh, render copy, matrix, slot, shape) still without its switch, and the number of slots another
    shape holds. A shape is listed once per group."""
    todo, taken, seen = [], 0, set()
    for orig, rc, matrix in pairs:
        if rc is None or not rc.get(MARK) or not rc.get("rb_src"):
            continue
        src = rc["rb_src"]
        for slot in find_maps(orig):
            key = (slot.tree.name, src)
            if key in seen:
                continue
            seen.add(key)
            sw = switch_of(slot.tree)
            have = _switch_src(sw) if sw is not None else None
            if have is None:                    # no switch, or one that lost its image
                todo.append((orig, rc, matrix, slot, src))
            elif have != src:
                taken += 1
    return todo, taken


def maps_pending(pairs):
    """How many maps fit_maps would make for these (import mesh, render copy, matrix) - cheap, for Apply."""
    return len(_todo(pairs)[0])


def fit_maps_steps(pairs):
    """Generator: yields (fraction, text) after every map. Returns a report {fitted, shared, taken, failed, seconds}:
    fitted = made now, shared = a map of the same shape was there already, taken = the group holds the map
    of another shape (two different meshes with one map - the first keeps it), failed = [(name, why)]."""
    t0 = time.time()
    drop_unused_maps()
    todo, taken = _todo(pairs)
    rep = {"fitted": 0, "shared": 0, "taken": taken, "failed": [], "seconds": 0.0}
    try:
        for i, (orig, rc, matrix, slot, src) in enumerate(todo):
            yield (i / len(todo), f"baking the bevel maps {i}/{len(todo)}")
            if switch_of(slot.tree) is not None:        # one that lost its image: built anew
                remove_switch(slot.tree)
            image = next((im for im in baked_maps() if im[IMAGE_OF] == slot.image.name and im.get(IMAGE_SRC) == src),
                         None)
            try:
                if image is None:
                    image = bake_map(slot, orig, rc, src, matrix)
                    rep["fitted"] += 1
                else:
                    rep["shared"] += 1
                build_switch(slot, image, src)
            except Exception as e:                      # one part without its map never stops the rest
                rep["failed"].append((orig.name, str(e) if isinstance(e, NoBevel) else f"{type(e).__name__}: {e}"))
    finally:
        drop_map_scene()
        _drop_unused_images()
    rep["seconds"] = time.time() - t0
    return rep


def fit_maps(pairs):
    gen = fit_maps_steps(pairs)
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def maps_text(rep):
    """One piece of a summary line."""
    if not rep:
        return ""
    parts = [f"{rep['fitted']} bevel map{'' if rep['fitted'] == 1 else 's'} baked"]
    if rep["taken"]:
        parts.append(f"{rep['taken']} left (another shape uses the same map)")
    if rep["failed"]:
        parts.append(f"{len(rep['failed'])} without ({rep['failed'][0][0]}: {rep['failed'][0][1]})")
    return ", " + ", ".join(parts)
