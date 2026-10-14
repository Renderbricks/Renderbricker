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

Every edge, one size (runs 277 and 278; maintainer with a screenshot: "Die Fasen sind unterschiedlich dick. Zu dicke
erzeugen Geometrie-Probleme." - then: "Ich muss doch für alle Kanten einen Bevel bekommen, sonst macht es gar keinen
Sinn. Die Bevels müssen nur die einheitliche Größe haben und mit dem Bevel Shader vergleichbar sein."). A bevel of
faces needs room beside the edge, and after the subdivision only 14 % of the chosen edges have it for the shader's
size (run 277). The shader has no such limit - it changes nothing but the normal. So the two are split:
  the size    is set in the normals (round_in_normals): every corner closer to a chosen edge than the bevel's width
              is turned towards the other side - half the angle on the edge, in a straight line down to nothing at
              the width. That is the run of the normal across a one-segment bevel, which matches the shader.
  the faces   follow where there is room (edge_room): an edge of the copy is bevelled at the full width when its
              own neighbours leave room for it, else not at all. Where the first row of faces is wide the bevel puts
              points where the rounding ends; where the rows are narrow the points are there already.
              A bevel of part of the width was tried first and is out: of 1642 faces that turned over on the part
              78301, 1641 lay at such a bevel, one at a full one (diag_turned.py) - the maintainer's "Zu dicke
              erzeugen Geometrie-Probleme".
The borders of a chamfer Mecabricks modelled (a narrow face between two shallow edges) are left alone. After the
bevel, bevel_copy looks for faces that turned over, takes the bevel near them out and bevels again.

Test build of run 281 (maintainer 2026-10-13: "Entweder alle oder nur Bevel Shader." - "0.15 zerstört nicht mehr
die Stelle. Es gibt lediglich Shading Artefakte." - after the trial of run 280: "Mach erst mal eine Version zum
testen"): the copy gets no bevel of faces any more. The rounding is in the normals at every chosen edge, and the
mesh gets support edges where the rounding ends (edgesupport.py), so it has the same size at every edge and cannot
streak; a net keeps a face plain that a turned normal would still run across. Nothing is moved: the outline of the
part stays as it was. What the notes above say about faces "as far as there is room" describes the builds before;
edge_room, strip_normals and turned_faces are still here for the probes of those runs and are not called.

The real bevel (run 285, UPDATES #50; maintainer 2026-10-14: "Einmal den Bevel Shader, der es faked und einmal eine
echte Bevelkante mit maximal 3 Facetten." - "Der Bevel darf erst nach der Unterteilung angelegt werden."): on top of
the build of run 281 the points inside the band of every chosen edge are moved onto the edge's profile, 1 to 3
straight pieces of the circle that touches both faces at the Radius (edgeshape.py). The outline is round now; the
support edges give the band its border (and with three segments the corners of the middle piece), the net keeps long
faces plain, the shading normals are those of the round surface.

One Radius for both (run 275, maintainer: "Bitte ermittle den passenden Bevelwert zum Bevelshaderwert."): the shader's
radius and the bevel's width are not the same size. Measured on 3004 - the angle of the shading normal across an
edge, the Bevel node at radius 0.20, 0.35 and 0.50 against geometric bevels in steps of 0.025 - the bevel that lies
closest to the shader (0.4 to 1.2 degrees apart) is 0.595 times the radius wide with one segment, 0.521 with two,
0.506 with three, 0.502 with four; the same ratios at all three radii. MATCH holds them: the panel's Radius is the
shader's, the bevel is made MATCH times as wide and so looks the same size.

The Radius in millimetres (maintainer 2026-10-13: "Ich möchte gerne in mm arbeiten. Das gilt auch für den Bevel
Shader." - "mm so machen 0.08 bis 0.2"): the panel's Radius is the edge radius, how far the rounding reaches on each
face from the edge, in millimetres of the real part (the units of the mesh). Edges: Bevel rounds that wide; the
shader's Bevel value has no unit of its own (it is the reach of an average of normals, Cycles svm/bevel.h) and gets
the Radius / MATCH[1], the value that looks that size (shader_radius). The importer's 0.35 is an edge radius of
0.208 mm; the field ends at 0.2.

A live modifier on the objects is not used: thousands of bricks share one baked copy, and the cache file holds it.
"""
import math
import bpy
import bmesh
import numpy as np
from . import config, creases, edgeshape, edgesupport, maps

EDGES = config.opt("--edges", "shader")                     # "shader" or "bevel"; set by the add-on or the command line
EDGE_RADIUS = float(config.opt("--edge-radius", "0.1"))     # the edge radius in mm (the units of the mesh)
BEVEL_SEGMENTS = int(config.opt("--bevel-segments", "2"))
# Edges: Bevel with the shader's rounding on top (maintainer 2026-10-14: "ich möchte gerne mal testen, wie der Bevel
# modus mit und ohne zusätzlichen Bevel Shader aussieht"): the copies read 0 instead of 1, the switch keeps the shader
SHADER_TOO = config.opt("--bevel-shader", "0") == "1"
# open for the test (maintainer 2026-10-14: "für den nächsten Test grenzen wir erst einmal das Eingabefenster nicht
# mehr ein"); before: 0.08 to 0.2 ("mm so machen 0.08 bis 0.2")
RADIUS_MIN, RADIUS_MAX, SEGMENTS_MAX = 0.001, 10.0, 3     # segments: "maximal 3 Facetten" (UPDATES #50)
EDGE_INNER = 85.0                            # an edge inside one island counts from this bend on (the rule W12)
EDGE_WEIGHT = "bevel_weight_edge"            # edge attribute Blender's Bevel reads
EDGE_MARK = "rb_edges"                       # property of a copy: the bevel it carries ("0.200/1"), "" without
EDGE_ATTR = "rb_bevel"                  # custom property of a bevelled copy: 1.0 (the material reads it)
MATCH = {1: 0.595, 2: 0.521, 3: 0.506, 4: 0.502}     # bevel width / shader radius that look alike, by segments (run 275)
ROOM = 0.9                              # share of the room beside an edge the bevel may take (half of it between two)
CHAMFER_ANGLE = 60.0                    # a modelled chamfer: both borders of a face bend by less than this ...
CHAMFER_WIDTH = 1.5                     # ... and the face between them is narrower than this (mm)
TRIES = 6                               # bevel, look for turned faces, take the bevel near them out: at most so often
TURN_MAX = 56.0                         # no corner is turned further: the corner of a box takes 54.7 degrees
SAME_SIDE = 30.0                        # a corner lies on the side of an edge whose normal it has within this angle
TURNED = 0.3                            # a face that was there counts as turned over below this cosine to its old normal
HARDEN = False                          # True: Blender's Harden Normals, as the first test build did (probe only)
STRENGTH = "__mod_weightednormals_faceweight"       # the Bevel modifier's face strength: lower on the faces it made
EDGE_VERSION = 13                        # how a bevelled copy is marked; copies of earlier test builds are made anew
EDGE_FOLDS, EDGE_GAP = "rb_folds", "rb_gap"       # the verdict of the checks, taken before the bevel changed the layout
EDGE_NODE = "rb_bevel_"                      # names of the switch nodes
RADIUS_WAS = "rb_bevel_was"                    # on a group node: the importer's Bevel value before the radius was set
EDGE_FRAME_TEXT = "Renderbricker: no shader rounding on bevelled copies"


def signature():
    """What a copy of the current settings carries in EDGE_MARK: "" for the shader, radius and segments for the bevel."""
    if EDGES != "bevel":
        return ""
    return f"{edge_radius():.3f}/{max(1, min(int(BEVEL_SEGMENTS), SEGMENTS_MAX))}"


def edge_radius():
    """The Radius within its limits: the edge radius in millimetres."""
    return min(max(float(EDGE_RADIUS), RADIUS_MIN), RADIUS_MAX)


def shader_radius():
    """The importer's Bevel value that looks the size of the Radius (Edges: Shader)."""
    return edge_radius() / MATCH[1]


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
    weights when the welded mesh does not have the faces of the import one to one. Of the edges chosen, the borders
    of a modelled chamfer ("chamfer") are taken out again; "bevelled" is what remains."""
    n = {"full": 0, "bevel": 0, "logo": 0, "modelled": 0, "chamfer": 0, "bevelled": 0}
    own = np.arange(len(wm.polygons), dtype=np.int32)      # the import's face of every cage face (W18 cuts some in two)
    if wm.attributes.get("rb_fi") is not None:
        wm.attributes["rb_fi"].data.foreach_get("value", own)
    if len(wm.polygons) < len(orig.polygons) or (len(own) and int(own.max()) >= len(orig.polygons)):
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
            a, b = isl[own[e.link_faces[0].index]], isl[own[e.link_faces[1].index]]
            if a in logos or b in logos:
                n["logo"] += 1
            elif a != b or math.degrees(e.calc_face_angle(0.0)) >= EDGE_INNER:
                n["bevel"] += 1
                w[e.index] = 1.0
            else:
                n["modelled"] += 1
    if n["bevel"]:
        n.update(_leave_chamfers(bm, w))
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
    radius, _segments = sig.split("/")
    return float(radius)                            # the Radius is the edge radius: the rounding reaches that far


def _sides(e, f):
    """The edges of face `f` that leave the ends of its edge `e`, and whether `f` has an edge that does not touch `e`."""
    ev = set(e.verts)
    return [g for g in f.edges if g is not e and (set(g.verts) & ev)], [g for g in f.edges if not (set(g.verts) & ev)]


def _leave_chamfers(bm, w):
    """On the welded cage `bm`: take the borders of modelled chamfers out of the weights `w` - a narrow face between
    two chosen edges that both bend only a little. Returns the counts."""
    bm.edges.ensure_lookup_table()
    on = w > 0.5
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
        w[i] = 0.0
    return {"chamfer": len(chamfer), "bevelled": int((w > 0.5).sum())}


# ---------------------------------------------------------------- the room of an edge, the lines of the edges
def edge_room(cp, weight, width):
    """Bevel weight 1 for the chosen edges of the baked copy `cp` that have room for a bevel `width` wide, 0 for the
    others (their rounding is in the normals alone). The room of an edge is the shortest edge that leaves its ends
    in its two faces, half of it where the face's far edge is chosen too; ROOM of it may be taken."""
    bm = bmesh.new()
    bm.from_mesh(cp)
    on = weight > 0.5
    out = np.zeros(len(bm.edges), np.float32)
    for e in bm.edges:
        if not on[e.index]:
            continue
        r = float("inf")
        for f in e.link_faces:
            sides, far = _sides(e, f)
            both = any(on[g.index] for g in far)
            for g in sides:
                r = min(r, g.calc_length() * (0.5 if both else 1.0))
        if width > 0 and r * ROOM >= width:
            out[e.index] = 1.0
    bm.free()
    return out


def edge_lines(cp, chosen):
    """The chosen edges of the copy `cp` as lines: (start points, end points, normals) - normals[i, side, end] is the
    normal the face on that side of edge i has at that end."""
    n = np.zeros(len(cp.loops) * 3, np.float32)
    cp.corner_normals.foreach_get("vector", n)
    n = n.reshape(-1, 3)
    bm = bmesh.new()
    bm.from_mesh(cp)
    a, b, nn = [], [], []
    for e in bm.edges:
        if not chosen[e.index] or len(e.link_faces) != 2:
            continue
        va, vb = e.verts
        row = []
        for f in e.link_faces:
            at = {lp.vert.index: lp.index for lp in f.loops}
            row.append((n[at[va.index]], n[at[vb.index]]))
        a.append(tuple(va.co))
        b.append(tuple(vb.co))
        nn.append(row)
    bm.free()
    return np.array(a, np.float64).reshape(-1, 3), np.array(b, np.float64).reshape(-1, 3), np.array(nn, np.float64).reshape(-1, 2, 2, 3)


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
    me.normals_split_custom_set(out)
    me.update()
    return int(strip.sum())


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=1), 1e-12)[:, None]


def round_in_normals(me, lines, width):
    """The size of the rounding, in the normals of `me`: every corner closer than `width` to one of the `lines`
    (edge_lines of the copy before the bevel) is turned from the normal of its side of the edge towards the normal
    of the other side - by half the angle between the two on the line itself, falling in a straight line to nothing
    at `width`; a corner that is turned that far already (inside a strip) stays. A corner near several edges takes
    the turn of each. Writes custom normals; returns the number of corners turned."""
    from mathutils import Vector
    from mathutils.kdtree import KDTree
    la, lb, ln = lines
    if not len(la) or width <= 0:
        return 0
    nv, nl = len(me.vertices), len(me.loops)
    co = np.zeros(nv * 3, np.float32); me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    tree = KDTree(nv)
    for i, c in enumerate(co.tolist()):
        tree.insert(c, i)
    tree.balance()
    mid, reach = (la + lb) / 2, np.linalg.norm(lb - la, axis=1) / 2 + width
    vi, li = [], []
    for i, (c, r) in enumerate(zip(mid.tolist(), reach.tolist())):
        found = tree.find_range(Vector(c), r)
        vi.extend(f[1] for f in found)
        li.extend([i] * len(found))
    if not vi:
        return 0
    vi, li = np.array(vi, np.int64), np.array(li, np.int64)
    ab = lb[li] - la[li]
    t = np.clip(((co[vi] - la[li]) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-18), 0.0, 1.0)
    d = np.linalg.norm(co[vi] - (la[li] + ab * t[:, None]), axis=1)
    near = d < width
    vi, li, t, d = vi[near], li[near], t[near], d[near]
    # every corner of those points
    lv = np.zeros(nl, np.int32); me.loops.foreach_get("vertex_index", lv)
    order = np.argsort(lv, kind="stable")
    first, count = np.searchsorted(lv[order], vi), np.bincount(lv, minlength=nv)[vi]
    pair = np.repeat(np.arange(len(vi)), count)
    loop = order[np.repeat(first, count) + (np.arange(len(pair)) - np.repeat(np.cumsum(count) - count, count))]
    li, t, d = li[pair], t[pair], d[pair]
    normals = np.zeros(nl * 3, np.float32); me.corner_normals.foreach_get("vector", normals)
    normals = normals.reshape(-1, 3).astype(np.float64)
    n = normals[loop]
    side = [_unit(ln[li, k, 0] * (1.0 - t)[:, None] + ln[li, k, 1] * t[:, None]) for k in (0, 1)]
    dots = [(n * side[k]).sum(axis=1) for k in (0, 1)]
    own = dots[1] > dots[0]
    n_own = np.where(own[:, None], side[1], side[0])
    n_other = np.where(own[:, None], side[0], side[1])
    theta = np.arccos(np.clip((n_own * n_other).sum(axis=1), -1.0, 1.0))
    have = np.arccos(np.clip(np.maximum(dots[0], dots[1]), -1.0, 1.0))        # how far the corner is turned already
    more = 0.5 * theta * (1.0 - d / width) - have
    towards = n_other - n * (n_other * n).sum(axis=1)[:, None]
    ok = (np.maximum(dots[0], dots[1]) > math.cos(math.radians(45.0 + SAME_SIDE / 2))) & (more > 1e-4) \
        & (np.linalg.norm(towards, axis=1) > 1e-9)
    if not ok.any():
        return 0
    loop, more, n_other, towards = loop[ok], more[ok], n_other[ok], _unit(towards[ok])
    tilt = towards * np.tan(np.minimum(more, 1.4))[:, None]
    # per corner: the strongest turn of each side - the same side reached from the next edge of a run counts once
    rest = np.lexsort((-more, loop))
    total, same = np.zeros((nl, 3)), math.cos(math.radians(SAME_SIDE))
    for _pass in range(4):
        if not len(rest):
            break
        lead = np.r_[True, loop[rest][1:] != loop[rest][:-1]]
        total[loop[rest[lead]]] += tilt[rest[lead]]
        of = rest[lead][np.cumsum(lead) - 1]
        rest = rest[(n_other[rest] * n_other[of]).sum(axis=1) <= same]
    touched = np.unique(loop)
    # where many edges meet (folds of hair) the turns can add up to more than a corner of three edges takes
    size = np.linalg.norm(total[touched], axis=1)
    limit = math.tan(math.radians(TURN_MAX))
    total[touched] *= np.minimum(1.0, limit / np.maximum(size, 1e-12))[:, None]
    normals[touched] = _unit(normals[touched] + total[touched])
    me.normals_split_custom_set(normals)
    me.update()
    return int(len(touched))


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
    """The finished copy `cp` with its chosen edges bevelled, in place: support edges where the bevel ends (and at a
    third of it with three segments), the rounding in the normals, the net, then the points inside the band moved onto
    the profile (edgeshape.py, UPDATES #50). Returns `cp`. A copy without a chosen edge is marked too (it is what these
    settings make of it). On the copy afterwards: rb_bevel = 1 (the material reads it), rb_bevel_normals (corners
    turned), rb_bevel_support (points made), rb_bevel_plain (faces the net kept plain), rb_bevel_moved (points on the
    profile), rb_bevel_back (points put back because a face would have turned over), rb_bevel_flat (corners that kept
    their face's normal: plain_where_off)."""
    sig = signature()
    if not sig:
        return cp
    at = cp.attributes.get(EDGE_WEIGHT)
    w = np.zeros(len(cp.edges), np.float32)
    if at is not None:
        at.data.foreach_get("value", w)
        cp.attributes.remove(at)
    cp[EDGE_MARK] = sig
    cp["rb_edges_v"] = EDGE_VERSION
    chosen = w > 0.5
    if not chosen.any():
        return cp
    width = bevel_width()                           # the Radius: the bevel reaches that far on each face
    segments = int(sig.split("/")[1])
    lines = edge_lines(cp, chosen)
    frames = edgeshape.edge_frames(cp, chosen)
    before = cp.copy()
    try:
        edgeshape.mark_chosen(cp, chosen)
        points, _cuts = edgesupport.support_edges(cp, chosen, width)
        if segments == 3:                           # the corners of the middle facet
            more, _cuts = edgesupport.support_edges(cp, edgeshape.chosen_again(cp), width * edgeshape.SHAPE_ROW3)
            points += more
        edgeshape.chosen_again(cp, drop=True)
        edgesupport.carry_normals(cp, before)
    finally:
        bpy.data.meshes.remove(before)
    plain = np.zeros(len(cp.loops) * 3, np.float32)
    cp.corner_normals.foreach_get("vector", plain)
    turned = round_in_normals(cp, lines, width)
    kept = edgesupport.keep_plain(cp, lines, width, plain.reshape(-1, 3))
    normals = np.zeros(len(cp.loops) * 3, np.float32)
    cp.corner_normals.foreach_get("vector", normals)
    normals = normals.reshape(-1, 3).astype(np.float64)
    moved, back, loops, round_normals = edgeshape.shape_edges(cp, frames, width, segments)
    normals[loops] = round_normals                  # the normals of the round surface where it was moved
    flat = edgeshape.plain_where_off(normals, cp)
    cp.normals_split_custom_set(normals)     # the shading of the rounding, on the new shape
    cp.update()
    cp[EDGE_ATTR] = 0.0 if SHADER_TOO else 1.0     # the material's rounding: off, or on top for the test (SHADER_TOO)
    cp["rb_bevel_normals"], cp["rb_bevel_support"], cp["rb_bevel_plain"] = turned, points, kept
    cp["rb_bevel_moved"], cp["rb_bevel_back"], cp["rb_bevel_flat"] = len(moved), back, flat
    return cp


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
