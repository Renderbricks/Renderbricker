"""Support edges for Edges: Bevel (UPDATES #43, run 280) - the points a rounding in the normals needs.

A normal can only change from one point of the mesh to the next. Where the next point beside a rounded edge lies
millimetres away, the rounding runs across all of that face: streaks (the maintainer's screenshots of 2026-10-13,
"Es gibt lediglich Shading Artefakte"). So every face that reaches from inside the rounding of a chosen edge to
outside it is cut where the rounding ends:

  for each run of chosen edges (a straight or gently bent piece) every point of the mesh has a distance from the
  run; the line on the surface where that distance equals the width is the border of the rounding. The edges of a
  face that cross it get a point there, the points are joined across the face.

Runs are done one after the other, twice round: where the borders of two runs cross (a corner of a face) the second
finds the first as edges of the mesh and crosses them like any other edge. Nothing is moved - every new point lies
on an edge that was there, so nothing can fold or tear.

Below it a net (keep_plain): a face a turned normal would still run across gets its plain normals back.

Tried first and dropped (run 280, support.py): going edge by edge - split the two edges that leave a rounded edge,
join the points. It left streak faces wherever the mesh is not a plain grid: fans of faces round a corner, cuts that
cross in a corner, points of other faces close to a rounded edge (54 such faces on the hinge brick 3830, level 1;
none with the rule above).
"""
import math
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc
from mathutils.kdtree import KDTree

EDGE_TMP = "rb_edge_rounded"            # edge layer while the cuts are made: the chosen edges, also after a split
EDGE_IN, EDGE_ON = 0.93, 1.25           # inside the rounding below EDGE_IN x width, on its border up to EDGE_ON x width
EDGE_BEND = 50.0                        # a run ends where the line of chosen edges bends by more than this (a corner;
#                                         the pieces of a small rounded corner bend by 20 to 45 degrees: one run)
EDGE_REACH = 1.5                        # the net: a face with a turned corner may reach this x width from the edges
EDGE_SWEEPS = 2                         # a point a later run makes can lie inside the rounding of an earlier one


def edge_runs(bm, mark):
    """The marked edges of `bm` as runs: chains through points where just two of them meet and the line bends by
    less than EDGE_BEND degrees. Returns a list of lists of edges."""
    done, runs, straight = set(), [], -math.cos(math.radians(EDGE_BEND))
    for e in bm.edges:
        if e[mark] <= 0.5 or e in done:
            continue
        run, stack = [e], [e]
        done.add(e)
        while stack:
            c = stack.pop()
            for v in c.verts:
                linked = [g for g in v.link_edges if g[mark] > 0.5]
                if len(linked) != 2:
                    continue
                o = linked[0] if linked[1] is c else linked[1]
                if o in done:
                    continue
                d1, d2 = (c.other_vert(v).co - v.co).normalized(), (o.other_vert(v).co - v.co).normalized()
                if d1.dot(d2) > straight:
                    continue
                done.add(o)
                run.append(o)
                stack.append(o)
        runs.append(run)
    return runs


def support_edges(me, chosen, width):
    """Support edges in the mesh `me`, in place: every face that reaches from inside the rounding of a chosen edge
    (`chosen`: per edge) to outside it is cut where the rounding ends, `width` from the edge. Returns
    (points made, edges made). Custom normals do not survive this - carry_normals sets them again."""
    bm = bmesh.new()
    bm.from_mesh(me)
    mark = bm.edges.layers.float.new(EDGE_TMP)      # (a new layer makes earlier references to edges stale: first)
    for e in bm.edges:
        if chosen[e.index] and len(e.link_faces) == 2:
            e[mark] = 1.0
    runs = [(np.array([tuple(e.verts[0].co) for e in run]), np.array([tuple(e.verts[1].co) for e in run]))
            for run in edge_runs(bm, mark)]
    first = list(bm.verts)
    tree = KDTree(len(first))
    for i, v in enumerate(first):
        tree.insert(v.co, i)
    tree.balance()
    added, n_edges = [], 0
    lo_d, hi_d = EDGE_IN * width, EDGE_ON * width
    for A, B in runs * EDGE_SWEEPS:
        AB = B - A
        L2 = np.maximum((AB * AB).sum(axis=1), 1e-18)
        cache = {}

        def at(co, A=A, AB=AB, L2=L2):
            c = np.array(co)
            t = np.clip(((c - A) * AB).sum(axis=1) / L2, 0.0, 1.0)
            return float(np.sqrt(((A + AB * t[:, None] - c) ** 2).sum(axis=1).min()))

        def dist(v, cache=cache, at=at):
            d = cache.get(v)
            if d is None:
                d = cache[v] = at(v.co)
            return d

        near = set()
        for a, b in zip(A, B, strict=True):
            for _co, i, _d in tree.find_range(Vector(((a + b) / 2).tolist()), float(np.linalg.norm(b - a)) / 2 + lo_d):
                near.add(first[i])
        box_lo, box_hi = np.minimum(A, B).min(axis=0) - lo_d, np.maximum(A, B).max(axis=0) + lo_d
        for v in added:
            c = v.co
            if box_lo[0] <= c.x <= box_hi[0] and box_lo[1] <= c.y <= box_hi[1] and box_lo[2] <= c.z <= box_hi[2]:
                near.add(v)
        faces, seen = [], set()
        for v in near:
            if not v.is_valid or dist(v) >= lo_d:
                continue
            for f in v.link_faces:
                if f not in seen:
                    seen.add(f)
                    faces.append(f)
        if not faces:
            continue
        # the edges of those faces that cross the border of the rounding get a point there
        crossing = set()
        for f in faces:
            for e in f.edges:
                da, db = dist(e.verts[0]), dist(e.verts[1])
                if min(da, db) < lo_d and max(da, db) > hi_d:
                    crossing.add(e)
        for e in crossing:
            a, b = e.verts
            if dist(a) > dist(b):
                a, b = b, a
            da, db = dist(a), dist(b)
            t = (width - da) / (db - da)
            for _again in range(3):                 # the distance from a bent run is not straight along the edge
                d = at(a.co.lerp(b.co, t))
                if abs(d - width) < 0.01 * width:
                    break
                t = min(0.999, max(0.001, t + (width - d) / max(db - da, 1e-9)))
            _ne, nv = bmesh.utils.edge_split(e, a, t)
            cache[nv] = width
            added.append(nv)
        # ... and each face is cut from point to point on that border, round every stretch of its outline outside
        work = list(faces)
        while work:
            f = work.pop()
            if not f.is_valid:
                continue
            vs = list(f.verts)
            n = len(vs)
            cls = [0 if dist(v) < lo_d else 2 if dist(v) > hi_d else 1 for v in vs]
            if 0 not in cls or 2 not in cls:
                continue
            cut, i = None, 0
            for _turn in range(n):                  # each stretch outside: from the point before it to the point after
                if cls[i] != 2 and cls[(i + 1) % n] == 2:
                    k = (i + 1) % n
                    while cls[k] == 2:
                        k = (k + 1) % n
                    if cls[i] == 1 and cls[k] == 1 and vs[i] is not vs[k] and bm.edges.get((vs[i], vs[k])) is None:
                        cut = (vs[i], vs[k])
                        break
                    if k <= i:
                        break
                    i = k
                else:
                    i += 1
                    if i >= n:
                        break
            if cut is None:
                continue
            try:
                new_face, loop = bmesh.utils.face_split(f, cut[0], cut[1])
            except ValueError:
                continue
            if loop is None:
                continue
            n_edges += 1
            work.append(f)
            work.append(new_face)
    n_points = len(bm.verts) - len(me.vertices)
    bm.edges.layers.float.remove(mark)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return n_points, n_edges


def _corner_data(me):
    """(corner normals, corner positions, face normal per corner, face per corner, loop start and total per face)."""
    nf, nl = len(me.polygons), len(me.loops)
    n = np.zeros(nl * 3, np.float32)
    me.corner_normals.foreach_get("vector", n)
    lv = np.zeros(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    co = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    fn = np.zeros(nf * 3, np.float32)
    me.polygons.foreach_get("normal", fn)
    ls = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    return n.reshape(-1, 3), co.reshape(-1, 3)[lv], fn.reshape(-1, 3)[np.repeat(np.arange(nf), lt)], np.repeat(np.arange(nf), lt), ls, lt


def carry_normals(me, before):
    """Custom normals for `me` from `before`, the same surface with other points: a corner takes the normal `before`
    has at that place - at a point that was there the normal of the same corner, elsewhere the normals of the old
    face's corners weighted for the place. Returns the number of corners that were weighted."""
    on, oco, ofn, _of, ols, olt = _corner_data(before)
    _n, co, fn, face, _ls, _lt = _corner_data(me)
    out = np.zeros((len(co), 3), np.float64)
    known = {}
    kp, kn = np.round(oco, 4), np.round(ofn, 2)
    for i in range(len(oco)):
        known.setdefault((kp[i, 0], kp[i, 1], kp[i, 2], kn[i, 0], kn[i, 1], kn[i, 2]), i)
    kp, kn = np.round(co, 4), np.round(fn, 2)
    moved = []
    for i in range(len(co)):
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
            _loc, _nor, f, _dist = tree.find_nearest(p.lerp(Vector(centre[face[i]].tolist()), 0.05))
            if f is None:
                out[i] = fn[i]
                continue
            a, k = ols[f], olt[f]
            weights = poly_3d_calc([Vector(c.tolist()) for c in oco[a:a + k]], p)
            v = (np.array(weights)[:, None] * on[a:a + k]).sum(axis=0)
            out[i] = v if np.linalg.norm(v) > 1e-9 else fn[i]
    out /= np.maximum(np.linalg.norm(out, axis=1), 1e-12)[:, None]
    me.normals_split_custom_set(out.tolist())
    me.update()
    return len(moved)


def keep_plain(me, lines, width, plain):
    """The net under the support edges: takes the rounding off every face of `me` it would streak across. A face
    with a corner turned away from `plain` (the corner normals ahead of the rounding, n x 3) and with a point further
    than EDGE_REACH x width from every rounded edge (`lines`: start points, end points, ...) gets the normals of
    `plain` back. Returns the number of such faces."""
    la, lb = lines[0], lines[1]
    n = np.zeros(len(me.loops) * 3, np.float32)
    me.corner_normals.foreach_get("vector", n)
    n = n.reshape(-1, 3)
    turned = (n * plain).sum(axis=1) < math.cos(math.radians(0.5))
    co = np.zeros(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    ab = lb - la
    l2 = np.maximum((ab * ab).sum(axis=1), 1e-18)
    far, count = {}, 0
    for p in me.polygons:
        if not turned[p.loop_start:p.loop_start + p.loop_total].any():
            continue
        for vi in p.vertices:
            if vi not in far:
                c = co[vi]
                t = np.clip(((c - la) * ab).sum(axis=1) / l2, 0.0, 1.0)
                far[vi] = float(np.linalg.norm(la + ab * t[:, None] - c, axis=1).min())
        if max(far[vi] for vi in p.vertices) > EDGE_REACH * width:
            n[p.loop_start:p.loop_start + p.loop_total] = plain[p.loop_start:p.loop_start + p.loop_total]
            count += 1
    if count:
        me.normals_split_custom_set(n.tolist())
        me.update()
    return count
