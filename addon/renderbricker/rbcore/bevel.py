"""Edges: Shader or Bevel (UPDATES #43) - real rounded edges in the smooth copies, in place of the bevel shader.

The importer rounds edges in the material: a Bevel node for Cycles, a baked map for EEVEE. In close views the node's
highlights are blotchy, it costs render time, and EEVEE has no rounding at all on parts without a map. With
Edges: Bevel the copies get the rounding as geometry (maintainer 2026-10-13: "Echte Fasen über Bevel. Ziel: Wechsel
zwischen Bevel und Bevel Shader.").

Which edges (run 273, second pass): the part's own sharp edges - a fully creased edge of the welded cage that was a
border between two islands of the import, or an edge inside one island that bends by EDGE_INNER degrees or more (W12).
Left out: the logos, and the outline of a rounding Mecabricks modelled already (W13: rim and foot of a stud) -
"Mecabricks Noppen benötigen keine Bevels, weil sie schon gebaut wurden."

How (run 274): the choice is written as bevel weight on the welded cage; the subdivision carries an edge attribute
to the edges that lie on the old edge. The finished copy - checked for folds and gaps as always - is bevelled by
Blender's Bevel modifier (by weight, Harden Normals) and replaced by the result. Measured on 3004 and 3040, both
shading variants: the strips' corner normals sweep the full angle of the edge, all other faces keep the normals of
the unbevelled copy (variant A within 0.03 degrees, B within 0.8).

A bevelled copy carries a mark, the custom property rb_bevel = 1 on the mesh. Through it the importer's material
switches its own rounding off for these meshes: the radius of the Bevel node and the strength of the EEVEE normal map
are multiplied by (1 - mark). The Attribute node reads it as an object attribute (a custom property of the object,
else of its mesh): one value per object. Import meshes and unbevelled copies have no such property and read 0:
nothing changes for them.
A point attribute of the mesh was the first choice and is wrong: fed into the radius of Cycles' Bevel node it gave
white streaks all over the part (run 274, matrix_probe.py - found in a control picture after the build, before the
maintainer had accepted anything). The same mark as an object attribute, or as a constant, renders clean.

The width (run 275): Blender's Clamp Overlap limits the width of every edge of a mesh to what its tightest spot allows.
On 3004 that made the bevel about 0.02 mm wide whatever radius was asked for - the first test build had a Radius that
did nothing (found when the maintainer said "0,35 ist offenbar sehr klein" and asked for the bevel value that matches
the shader's). The clamp is off; edge_room gives every run of bevelled edges its own limit - what the faces beside it
leave - as bevel weight, by which Blender scales the width of an edge.

One Radius for both (run 275, maintainer: "Bitte ermittle den passenden Bevelwert zum Bevelshaderwert."): the shader's
radius and the bevel's width are not the same size. Measured on 3004 - the angle of the shading normal across an
edge, the Bevel node at radius 0.20, 0.35 and 0.50 against geometric bevels in steps of 0.025 - the bevel that lies
closest to the shader (0.4 to 1.2 degrees apart) is 0.595 times the radius wide with one segment, 0.521 with two,
0.506 with three, 0.502 with four; the same ratios at all three radii. MATCH holds them: the panel's Radius is the
shader's, the bevel is made MATCH times as wide and so looks the same size.

A live modifier on the objects is not used: thousands of bricks share one baked copy, and the cache file holds it.
"""
import math
import bpy
import bmesh
import numpy as np
from . import config, creases, maps, workscene

EDGES = config.opt("--edges", "shader")                     # "shader" or "bevel"; set by the add-on or the command line
BEVEL_RADIUS = float(config.opt("--bevel-radius", "0.35"))  # in the units of the mesh (mm); the importer's value
BEVEL_SEGMENTS = int(config.opt("--bevel-segments", "1"))
RADIUS_MAX, SEGMENTS_MAX = 0.5, 4       # maintainer 2026-10-13: "0 bis 0,5" - LEGO edges leave little room
EDGE_INNER = 85.0                            # an edge inside one island counts from this bend on (the rule W12)
EDGE_WEIGHT = "bevel_weight_edge"            # edge attribute Blender's Bevel reads
EDGE_MARK = "rb_edges"                       # property of a copy: the bevel it carries ("0.350/1"), "" without
EDGE_ATTR = "rb_bevel"                  # custom property of a bevelled copy: 1.0 (the material reads it)
MATCH = {1: 0.595, 2: 0.521, 3: 0.506, 4: 0.502}     # bevel width / shader radius that look alike, by segments (run 275)
ROOM = 0.9                              # share of the room beside an edge the bevel may take (half of it between two)
MIN_WEIGHT = 0.05                       # a run with less room than this share of the radius is left sharp
EDGE_VERSION = 4                        # how a bevelled copy is marked; copies of the first test build (1) are made anew
EDGE_FOLDS, EDGE_GAP = "rb_folds", "rb_gap"       # the verdict of the checks, taken before the bevel changed the layout
EDGE_NODE = "rb_bevel_"                      # names of the switch nodes
RADIUS_WAS = "rb_bevel_was"                    # on a group node: the importer's Bevel value before the radius was set
EDGE_FRAME_TEXT = "Renderbricker: no shader rounding on bevelled copies"


def signature():
    """What a copy of the current settings carries in EDGE_MARK: "" for the shader, radius and segments for the bevel."""
    if EDGES != "bevel" or BEVEL_RADIUS <= 0.0:
        return ""
    return f"{min(BEVEL_RADIUS, RADIUS_MAX):.3f}/{max(1, min(int(BEVEL_SEGMENTS), SEGMENTS_MAX))}"


def is_bevelled(cp):
    return bool(cp.get(EDGE_MARK))


def is_current(cp):
    """The copy is what the current settings make: the same bevel (or none), marked the current way."""
    sig = signature()
    return cp.get(EDGE_MARK, "") == sig and (not sig or cp.get("rb_edges_v") == EDGE_VERSION)


# ---------------------------------------------------------------- which edges
def mark_edges(orig, wm):
    """Bevel weight 1 on the part's own sharp edges of the welded cage `wm`; the sharp flag is taken off them (a
    bevelled edge is no hard edge any more). Returns the counts {"full", "bevel", "logo", "modelled"}; without
    weights when the welded mesh does not have the faces of the import one to one."""
    n = {"full": 0, "bevel": 0, "logo": 0, "modelled": 0}
    if len(wm.polygons) != len(orig.polygons):
        return n
    bm = bmesh.new()
    bm.from_mesh(orig)
    isl, logos = np.zeros(len(bm.faces), np.int32), set()
    for k, (kind, comp, _n) in enumerate(creases.classify(bm)):
        for f in comp:
            isl[f.index] = k
        if kind == "logo":
            logos.add(k)
    bm.free()
    bm = bmesh.new()
    bm.from_mesh(wm)
    cl = bm.edges.layers.float.get("crease_edge")
    w = np.zeros(len(bm.edges), np.float32)
    if cl is not None:
        for e in bm.edges:
            if e[cl] < 0.99 or len(e.link_faces) != 2:
                continue
            n["full"] += 1
            a, b = isl[e.link_faces[0].index], isl[e.link_faces[1].index]
            if a in logos or b in logos:
                n["logo"] += 1
            elif a != b or math.degrees(e.calc_face_angle(0.0)) >= EDGE_INNER:
                n["bevel"] += 1
                w[e.index] = 1.0
            else:
                n["modelled"] += 1
    bm.free()
    at = wm.attributes.get(EDGE_WEIGHT) or wm.attributes.new(EDGE_WEIGHT, 'FLOAT', 'EDGE')
    at.data.foreach_set("value", w)
    sharp = wm.attributes.get("sharp_edge")
    if sharp is not None and n["bevel"]:
        v = np.zeros(len(wm.edges), bool)
        sharp.data.foreach_get("value", v)
        sharp.data.foreach_set("value", v & (w < 0.5))
    wm.update()
    return n


# ---------------------------------------------------------------- the room of an edge
def edge_room(cp, weight, radius):
    """Bevel weights 0..1 for the weighted edges of the baked copy `cp`: the share of `radius` each run of edges has
    room for. The room of an edge is the shortest side edge of its two faces (the edges that leave its ends), half
    of it where the face's far edge is bevelled too; a run - weighted edges linked through points where just two of
    them meet - takes the smallest room along it, so its width does not change from face to face."""
    bm = bmesh.new()
    bm.from_mesh(cp)
    bm.edges.ensure_lookup_table()
    on = weight > 0.5
    room = {}
    for e in bm.edges:
        if not on[e.index]:
            continue
        r = float("inf")
        for f in e.link_faces:
            far = any(on[g.index] for g in f.edges if g is not e and not (set(g.verts) & set(e.verts)))
            for g in f.edges:
                if g is not e and (set(g.verts) & set(e.verts)):
                    r = min(r, g.calc_length() * (0.5 if far else 1.0))
        room[e.index] = r * ROOM
    done, out = set(), np.zeros(len(bm.edges), np.float32)
    for start in room:
        if start in done:
            continue
        run, stack = [], [start]
        done.add(start)
        while stack:
            i = stack.pop()
            run.append(i)
            for v in bm.edges[i].verts:
                linked = [g.index for g in v.link_edges if on[g.index]]
                if len(linked) == 2:                    # the run goes on; at a corner (3 and more) it ends
                    for j in linked:
                        if j not in done:
                            done.add(j)
                            stack.append(j)
        share = min(1.0, min(room[i] for i in run) / radius) if radius > 0 else 0.0
        if share >= MIN_WEIGHT:
            out[run] = share
    bm.free()
    return out


# ---------------------------------------------------------------- the bevelled copy
def bevel_copy(cp):
    """The finished copy `cp` with its weighted edges bevelled: a new mesh with the properties of `cp`, which is
    removed. Returns the new mesh - `cp` itself when the settings ask for no bevel. A copy without a weighted edge
    is marked too (it is what these settings make of it)."""
    sig = signature()
    if not sig:
        return cp
    at = cp.attributes.get(EDGE_WEIGHT)
    w = np.zeros(len(cp.edges), np.float32)
    if at is not None:
        at.data.foreach_get("value", w)
    radius, segments = float(sig.split("/")[0]), int(sig.split("/")[1])
    width = radius * MATCH.get(segments, 0.5)       # as wide as the shader's rounding of this radius looks
    if (w > 0.5).any():
        w = edge_room(cp, w, width)
        at.data.foreach_set("value", w)
        cp.update()
    if not (w > 0.0).any():
        if at is not None:
            cp.attributes.remove(at)
        cp[EDGE_MARK] = sig
        cp["rb_edges_v"] = EDGE_VERSION
        return cp
    ob = bpy.data.objects.new(workscene.WORK_NAME + " bevel", cp)
    workscene.link_work(ob)
    try:
        mod = ob.modifiers.new("Bevel", 'BEVEL')
        mod.limit_method, mod.offset_type = 'WEIGHT', 'OFFSET'
        mod.width, mod.segments, mod.profile = width, segments, 0.5
        mod.use_clamp_overlap, mod.harden_normals, mod.loop_slide = False, True, True       # the limit: edge_room
        dg = workscene.depsgraph_of(ob)
        dg.update()
        new = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    finally:
        bpy.data.objects.remove(ob)
    for key in cp.keys():
        new[key] = cp[key]
    name = cp.name
    cp.user_remap(new)
    bpy.data.meshes.remove(cp)
    new.name = name
    new.use_fake_user = True
    left = new.attributes.get(EDGE_WEIGHT)
    if left is not None:
        new.attributes.remove(left)
    new[EDGE_ATTR] = 1.0
    new[EDGE_MARK] = sig
    new["rb_edges_v"] = EDGE_VERSION
    return new


# ---------------------------------------------------------------- the switch in the importer's material
def _keep_factor(tree, x, y):
    """Nodes in `tree` that give 1 for an import or a plain copy and 0 for a bevelled copy. Returns the output."""
    at = tree.nodes.new("ShaderNodeAttribute")
    at.name, at.label, at.attribute_type, at.attribute_name = EDGE_NODE + "attribute", "Bevelled copy?", 'OBJECT', EDGE_ATTR
    at.location = (x - 420, y)
    inv = tree.nodes.new("ShaderNodeMath")
    inv.name, inv.label, inv.operation, inv.use_clamp = EDGE_NODE + "keep", "1 - mark", 'SUBTRACT', True
    inv.inputs[0].default_value = 1.0
    inv.location = (x - 210, y)
    tree.links.new(at.outputs["Fac"], inv.inputs[1])
    frame = tree.nodes.new("NodeFrame")
    frame.name, frame.label = EDGE_NODE + "frame", EDGE_FRAME_TEXT
    at.parent = inv.parent = frame
    return inv.outputs[0], frame


def _switch_socket(tree, node, sock, label):
    """Multiply what goes into `sock` of `node` by the keep factor. Nothing when the switch is there already (one of
    the first test build reads a point attribute: set right)."""
    old = tree.nodes.get(EDGE_NODE + "attribute")
    if old is not None and old.attribute_type != 'OBJECT':
        old.attribute_type = 'OBJECT'
    if any(n.name.startswith(EDGE_NODE) for n in tree.nodes):
        return False
    keep, frame = _keep_factor(tree, node.location.x, node.location.y - 260)
    mul = tree.nodes.new("ShaderNodeMath")
    mul.name, mul.label, mul.operation = EDGE_NODE + "times", label, 'MULTIPLY'
    mul.location = (node.location.x - 210, node.location.y - 120)
    mul.parent = frame
    if sock.is_linked:
        src = sock.links[0].from_socket
        tree.links.remove(sock.links[0])
        tree.links.new(src, mul.inputs[0])
    else:
        mul.inputs[0].default_value = sock.default_value
    tree.links.new(keep, mul.inputs[1])
    tree.links.new(mul.outputs[0], sock)
    return True


def build_switches(orig):
    """The material of this part stops rounding its edges on bevelled copies: the Bevel node's radius (Cycles) and
    the strength of the normal maps EEVEE alone reads. Returns the number of switches built now."""
    built = 0
    found = maps.find_bevel(orig)
    if found is not None:
        node = found[0]
        built += _switch_socket(node.id_data, node, node.inputs["Radius"], "Radius x keep")
    for slot in maps.find_maps(orig):
        for n in slot.tree.nodes:
            if n.type == 'NORMAL_MAP':
                built += _switch_socket(slot.tree, n, n.inputs["Strength"], "Strength x keep")
                break
    return built


def remove_edge_switch(tree):
    """Take the switch out of a tree again: the socket gets back what went into the multiplication."""
    mul = tree.nodes.get(EDGE_NODE + "times")
    if mul is not None and mul.outputs[0].is_linked:
        target = mul.outputs[0].links[0].to_socket
        if mul.inputs[0].is_linked:
            src = mul.inputs[0].links[0].from_socket
            tree.links.remove(mul.outputs[0].links[0])
            tree.links.new(src, target)
        else:
            value = mul.inputs[0].default_value
            tree.links.remove(mul.outputs[0].links[0])
            target.default_value = value
    for n in [n for n in tree.nodes if n.name.startswith(EDGE_NODE)]:
        tree.nodes.remove(n)


def drop_unused_switches(everything=False):
    """After Remove: no bevelled copy left in the file - the switches go. Returns how many trees were cleaned."""
    if not everything and any(m.get(EDGE_MARK) for m in bpy.data.meshes):
        return 0
    n = 0
    for tree in list(bpy.data.node_groups):
        if any(node.name.startswith(EDGE_NODE) for node in tree.nodes):
            remove_edge_switch(tree)
            n += 1
    return n


# ---------------------------------------------------------------- the shader's radius
def _radius_nodes(orig):
    for mt in orig.materials:
        if mt is None or mt.node_tree is None:
            continue
        for n in mt.node_tree.nodes:
            if n.type == 'GROUP' and n.node_tree is not None and "Bevel" in n.inputs and "Scale" in n.inputs \
                    and not n.inputs["Bevel"].is_linked:
                yield n


def set_shader_radius(orig, radius):
    """Edges: Shader - the importer's Bevel value of this part's materials follows the Radius of the panel. The value
    it had is kept on the node and comes back with restore_shader_radius. Returns the number of nodes changed."""
    changed = 0
    for n in _radius_nodes(orig):
        sock = n.inputs["Bevel"]
        if abs(sock.default_value - radius) > 1e-6:
            if RADIUS_WAS not in n:
                n[RADIUS_WAS] = sock.default_value
            sock.default_value = radius
            changed += 1
    return changed


def restore_shader_radius(orig):
    changed = 0
    for n in _radius_nodes(orig):
        if RADIUS_WAS in n:
            n.inputs["Bevel"].default_value = n[RADIUS_WAS]
            del n[RADIUS_WAS]
            changed += 1
    return changed
