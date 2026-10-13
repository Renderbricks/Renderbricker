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

The normals (run 276): Harden Normals of the Bevel modifier, used at first, sets the normals of every face beside a
bevelled edge to the face's own normal. Right for a flat face - on a round surface whose rim is bevelled it shows
facets, and at the viewport level 1 nearly every face of a small round part lies beside a bevel (the maintainer's
screenshot: "Was siehst Du hier? Facetten."). The first probe had only looked at flat-sided parts. Now nothing is
hardened, and no normal is left to the modifier: it also garbles the custom normals a copy carries on every face it
rebuilds. strip_normals sets all of them - an old face takes the normals the unbevelled copy has at that place, a
strip takes at each corner the normal of the faces beside it and so shades from the one side's normal to the other's.

One width per part (run 277, maintainer with a screenshot: "Die Fasen sind unterschiedlich dick. Zu dicke erzeugen
Geometrie-Probleme." - the same he had seen with the importer's own bevel option): a run of edges is bevelled at the
full width or not at all. mark_edges decides it on the welded cage, once for all levels: a run needs room for the
width on the finest level; the two borders of a chamfer Mecabricks modelled (a narrow face between two shallow
edges) are left alone - bevelled as well they made a rounding three strips thick. After the bevel, bevel_copy looks
for faces that turned over, takes the bevel near them out and bevels again.

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
CHAMFER_ANGLE = 60.0                    # a modelled chamfer: both borders of a face bend by less than this ...
CHAMFER_WIDTH = 1.5                     # ... and the face between them is narrower than this (mm)
TURNED = 0.3                            # a face that was there counts as turned over below this cosine to its old normal
HARDEN = False                          # True: Blender's Harden Normals, as the first test build did (probe only)
STRENGTH = "__mod_weightednormals_faceweight"       # the Bevel modifier's face strength: lower on the faces it made
EDGE_VERSION = 6                        # how a bevelled copy is marked; copies of the first test build (1) are made anew
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
    weights when the welded mesh does not have the faces of the import one to one. Of the edges chosen, those of a
    modelled chamfer ("chamfer") and those of runs without room for the full width ("narrow") are taken out again;
    "bevelled" is what remains."""
    n = {"full": 0, "bevel": 0, "logo": 0, "modelled": 0, "chamfer": 0, "narrow": 0, "bevelled": 0}
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
    if n["bevel"]:
        n.update(_full_width_or_none(bm, w))
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


def bevel_width():
    """The width of the bevel the current settings ask for (0 without)."""
    sig = signature()
    if not sig:
        return 0.0
    radius, segments = sig.split("/")
    return float(radius) * MATCH.get(int(segments), 0.5)


def _sides(e, f):
    """The edges of face `f` that leave the ends of its edge `e`, and whether `f` has an edge that does not touch `e`."""
    ev = set(e.verts)
    return [g for g in f.edges if g is not e and (set(g.verts) & ev)], [g for g in f.edges if not (set(g.verts) & ev)]


def _full_width_or_none(bm, w):
    """On the welded cage `bm`: take out of the weights `w` the borders of modelled chamfers and every run of edges
    that has no room for the full width on the finest level baked. Returns the counts."""
    width = bevel_width()
    level = max([config.RENDER_LEVEL, config.VIEW_LEVEL, config.LEVELS] + list(config.PRE_LEVELS))
    bm.edges.ensure_lookup_table()
    out = {"chamfer": 0, "narrow": 0, "bevelled": 0}
    on = w > 0.5
    # the borders of a modelled chamfer: a narrow face between two chosen edges that both bend only a little
    shallow = {e.index for e in bm.edges if on[e.index] and math.degrees(e.calc_face_angle(0.0)) < CHAMFER_ANGLE}
    chamfer = set()
    for i in shallow:
        e = bm.edges[i]
        for f in e.link_faces:
            sides, far = _sides(e, f)
            if sides and max(g.calc_length() for g in sides) < CHAMFER_WIDTH and any(g.index in shallow for g in far):
                chamfer.add(i)
                chamfer.update(g.index for g in far if g.index in shallow)
    for i in chamfer:
        w[i], on[i] = 0.0, False
    out["chamfer"] = len(chamfer)
    # the room of every chosen edge on the finest level: the subdivision halves the faces beside it once per level
    for _pass in range(2):                              # a run taken out leaves its neighbours more room
        room = {}
        for e in bm.edges:
            if not on[e.index]:
                continue
            r = float("inf")
            for f in e.link_faces:
                sides, far = _sides(e, f)
                both = any(on[g.index] for g in far)
                for g in sides:
                    r = min(r, g.calc_length() * (0.5 if both else 1.0))
            room[e.index] = r * ROOM / (2 ** level)
        done, dropped = set(), 0
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
                    if len(linked) == 2:                # the run goes on; at a corner (3 and more) it ends
                        for j in linked:
                            if j not in done:
                                done.add(j)
                                stack.append(j)
            if min(room[i] for i in run) < width:
                for i in run:
                    w[i], on[i] = 0.0, False
                dropped += len(run)
        out["narrow"] += dropped
        if not dropped:
            break
    out["bevelled"] = int(on.sum())
    return out


# ---------------------------------------------------------------- the normals of a bevelled copy
def _corners(me):
    """(corner normals, corner positions, face normal per corner, face per corner, loop start and total per face)."""
    nf, nl = len(me.polygons), len(me.loops)
    n = np.zeros(nl * 3, np.float32); me.corner_normals.foreach_get("vector", n)
    lv = np.zeros(nl, np.int32); me.loops.foreach_get("vertex_index", lv)
    co = np.zeros(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    fn = np.zeros(nf * 3, np.float32); me.polygons.foreach_get("normal", fn)
    ls = np.zeros(nf, np.int32); me.polygons.foreach_get("loop_start", ls)
    lt = np.zeros(nf, np.int32); me.polygons.foreach_get("loop_total", lt)
    face = np.repeat(np.arange(nf), lt)
    return n.reshape(-1, 3), co.reshape(-1, 3)[lv], fn.reshape(-1, 3)[face], face, ls, lt, lv


def strip_normals(me, before):
    """Custom normals for `me`, the mesh the Bevel modifier made of the copy `before` (face strength on).
    The custom normals a mesh carries do not survive the modifier on the faces it rebuilds - they are stored relative
    to each corner and come out interpolated as plain numbers (run 276: on the round brick 3062 at level 1, 15 % of
    the untouched corners had turned by more than a degree: the facets of the maintainer's screenshot). So every
    normal is set here:
      a face that was there   takes the normal `before` has at that place - at a point that did not move the normal
                              of the same corner, at a point the bevel slid along an edge the normals of the old
                              face's corners, weighted for that place
      a strip                 every corner takes the mean normal of the old faces at its point; a point inside a
                              strip of several segments the mean of the strip faces around it.
    Returns the number of strip faces."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.interpolate import poly_3d_calc
    fs = me.attributes.get(STRENGTH)
    if fs is None or not len(me.polygons):
        return 0
    strength = np.zeros(len(me.polygons), np.int32)
    fs.data.foreach_get("value", strength)
    strip = strength < strength.max()
    if not strip.any():
        return 0
    on, oco, ofn, _oface, ols, olt, _olv = _corners(before)
    _n, co, fn, face, ls, lt, lv = _corners(me)
    of_strip = strip[face]
    out = np.zeros((len(co), 3), np.float64)
    known = {}
    kp, kn = np.round(oco, 4), np.round(ofn, 2)
    for i in range(len(oco)):
        known.setdefault((kp[i, 0], kp[i, 1], kp[i, 2], kn[i, 0], kn[i, 1], kn[i, 2]), i)
    kp, kn = np.round(co, 4), np.round(fn, 2)
    moved = []
    for i in np.nonzero(~of_strip)[0]:
        j = known.get((kp[i, 0], kp[i, 1], kp[i, 2], kn[i, 0], kn[i, 1], kn[i, 2]))
        if j is None:
            moved.append(i)
        else:
            out[i] = on[j]
    if moved:
        verts = np.zeros(len(before.vertices) * 3, np.float32)
        before.vertices.foreach_get("co", verts)
        tree = BVHTree.FromPolygons(verts.reshape(-1, 3).tolist(), [tuple(p.vertices) for p in before.polygons])
        centre = np.zeros(len(me.polygons) * 3, np.float32)
        me.polygons.foreach_get("center", centre)
        centre = centre.reshape(-1, 3)
        for i in moved:
            p = Vector(co[i].tolist())
            inward = p.lerp(Vector(centre[face[i]].tolist()), 0.05)     # a little inside the face: which old face it is
            _loc, _nor, f, _dist = tree.find_nearest(inward)
            if f is None:
                out[i] = fn[i]
                continue
            a, k = ols[f], olt[f]
            weights = poly_3d_calc([Vector(c.tolist()) for c in oco[a:a + k]], p)
            v = (np.array(weights)[:, None] * on[a:a + k]).sum(axis=0)
            out[i] = v if np.linalg.norm(v) > 1e-9 else fn[i]
    nv = len(me.vertices)
    beside = np.zeros((nv, 3), np.float64)
    np.add.at(beside, lv[~of_strip], out[~of_strip])
    inside = np.zeros((nv, 3), np.float64)
    np.add.at(inside, lv[of_strip], fn[of_strip])
    has = np.linalg.norm(beside, axis=1) > 1e-6
    vn = np.where(has[:, None], beside, inside)
    out[of_strip] = vn[lv[of_strip]]
    out /= np.maximum(np.linalg.norm(out, axis=1), 1e-12)[:, None]
    me.normals_split_custom_set(out.tolist())
    me.update()
    return int(strip.sum())


def turned_faces(me, before):
    """Centres of the faces of the bevelled mesh `me` that were there before and have turned over: their normal
    points away from the normal `before` has at that place (a bevel wider than its room folds the faces beside it)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    fs = me.attributes.get(STRENGTH)
    nf = len(me.polygons)
    if fs is None or not nf:
        return []
    strength = np.zeros(nf, np.int32)
    fs.data.foreach_get("value", strength)
    old = np.nonzero(strength >= strength.max())[0]
    fn = np.zeros(nf * 3, np.float32); me.polygons.foreach_get("normal", fn)
    fc = np.zeros(nf * 3, np.float32); me.polygons.foreach_get("center", fc)
    area = np.zeros(nf, np.float32); me.polygons.foreach_get("area", area)
    fn, fc = fn.reshape(-1, 3), fc.reshape(-1, 3)
    on = np.zeros(len(before.polygons) * 3, np.float32); before.polygons.foreach_get("normal", on)
    on = on.reshape(-1, 3)
    verts = np.zeros(len(before.vertices) * 3, np.float32)
    before.vertices.foreach_get("co", verts)
    tree = BVHTree.FromPolygons(verts.reshape(-1, 3).tolist(), [tuple(p.vertices) for p in before.polygons])
    bad = []
    for i in old:
        if area[i] < 1e-10:
            continue
        _loc, _nor, f, _dist = tree.find_nearest(Vector(fc[i].tolist()))
        if f is not None and float(fn[i] @ on[f]) < TURNED:
            bad.append(fc[i].copy())
    return bad


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
    segments = int(sig.split("/")[1])
    width = bevel_width()                           # as wide as the shader's rounding of this radius looks
    if not (w > 0.5).any():
        if at is not None:
            cp.attributes.remove(at)
        cp[EDGE_MARK] = sig
        cp["rb_edges_v"] = EDGE_VERSION
        return cp
    new, taken_out = None, 0
    for attempt in range(3):
        ob = bpy.data.objects.new(workscene.WORK_NAME + " bevel", cp)
        workscene.link_work(ob)
        try:
            mod = ob.modifiers.new("Bevel", 'BEVEL')
            mod.limit_method, mod.offset_type = 'WEIGHT', 'OFFSET'
            mod.width, mod.segments, mod.profile = width, segments, 0.5
            mod.use_clamp_overlap, mod.harden_normals, mod.loop_slide = False, HARDEN, True     # the limit: mark_edges
            mod.face_strength_mode = 'FSTR_ALL'         # tells the strips from the faces that were there
            dg = workscene.depsgraph_of(ob)
            dg.update()
            new = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        finally:
            bpy.data.objects.remove(ob)
        bad = turned_faces(new, cp) if attempt < 2 else []
        if not len(bad):
            break
        # the bevel near a face that turned over is taken out, the copy bevelled again
        ev = np.zeros(len(cp.edges) * 2, np.int32)
        cp.edges.foreach_get("vertices", ev)
        vco = np.zeros(len(cp.vertices) * 3, np.float32)
        cp.vertices.foreach_get("co", vco)
        mid = vco.reshape(-1, 3)[ev.reshape(-1, 2)].mean(axis=1)
        near = np.zeros(len(mid), bool)
        for c in bad:
            near |= np.linalg.norm(mid - c, axis=1) < 4.0 * width
        near &= w > 0.5
        if not near.any():
            break
        taken_out += int(near.sum())
        w = np.where(near, 0.0, w).astype(np.float32)
        at.data.foreach_set("value", w)
        cp.update()
        bpy.data.meshes.remove(new)
        new = None
    if new is None:                                 # nothing left to bevel after the check
        cp.attributes.remove(at)
        cp[EDGE_MARK] = sig
        cp["rb_edges_v"] = EDGE_VERSION
        return cp
    if not HARDEN:
        strip_normals(new, cp)
    left = new.attributes.get(STRENGTH)
    if left is not None:
        new.attributes.remove(left)
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
    new["rb_bevel_out"] = taken_out                 # edges whose bevel the check took out again
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
