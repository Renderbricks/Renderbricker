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

Beside a rounded corner of the outline (maintainer 2026-10-14, 18747 with Edges: Bevel: "Rundung klappt. Bevel
nicht." - wedges along the edge from each corner) the faces can be long slivers that fan from the rim to one far
point which itself lies just on the border. No edge of them crossed the border by its ends, so none was cut, and
the rounding ran out to 0.26 mm instead of 0.1 between them. Two things for that: a long edge from inside the
rounding to a point on the border is looked at along its length and gets its point where it first leaves; and a
face is cut wherever three or more of its points in a row lie on or beyond the border - the part beyond becomes a
face of its own, with plain normals.

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
EDGE_FLAT = 1e-4                        # a cut needs a point this far (mm) off its line on either side
EDGE_STEPS = 24                         # rounds at most to find the place on an edge where the rounding ends
EDGE_LONG = 2.0                         # an edge longer than this x width that ends on the border is looked at along
#                                         its length: it may leave the rounding before its end
CARRY_SAME = 0.5                        # carry_normals: the old face of a corner looks its face's way within 60 degrees
CARRY_NEAR = 0.01                       # ... and is looked for this far (mm) beyond the nearest one


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


def _cell(co, cell):
    """The cell of the grid the place `co` lies in."""
    return math.floor(co[0] / cell), math.floor(co[1] / cell), math.floor(co[2] / cell)


def _has_area(vs, i, k):
    """True if a cut from point i to point k of the outline `vs` leaves a face with area on either side: on each side
    a point stands off the line of the cut. (Library run 281: 922 faces without area on 166 parts, cut off along an
    edge that carries several points in a line.)"""
    a, d = vs[i].co, vs[k].co - vs[i].co
    length, n = d.length, len(vs)
    if length < EDGE_FLAT:
        return False
    for lo, hi in ((i, k), (k, i)):
        j = (lo + 1) % n
        while j != hi and (vs[j].co - a).cross(d).length <= EDGE_FLAT * length:
            j = (j + 1) % n
        if j == hi:
            return False
    return True


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
    n_edges = 0
    lo_d, hi_d = EDGE_IN * width, EDGE_ON * width
    cell, grid = max(1.0, 2.5 * lo_d), {}           # the points made so far, by cell (found again by the later runs)
    for A, B in runs * EDGE_SWEEPS:
        AB = B - A
        L2 = np.maximum((AB * AB).sum(axis=1), 1e-18)
        cache = {}

        def at_many(points, A=A, AB=AB, L2=L2):
            """Distances of `points` (n x 3) from the run."""
            out = np.empty(len(points))
            step = max(1, 2000000 // len(A))
            for s in range(0, len(points), step):
                c = points[s:s + step, None, :]
                t = np.clip(((c - A) * AB).sum(axis=2) / L2, 0.0, 1.0)
                out[s:s + step] = np.sqrt(((A + AB * t[:, :, None] - c) ** 2).sum(axis=2).min(axis=1))
            return out

        def learn(verts, cache=cache, at_many=at_many):
            new = [v for v in verts if v not in cache]
            if new:
                cache.update(zip(new, at_many(np.array([tuple(v.co) for v in new], np.float64)).tolist(), strict=True))

        def dist(v, cache=cache, learn=learn):
            d = cache.get(v)
            if d is None:
                learn((v,))
                d = cache[v]
            return d

        near = set()
        for a, b in zip(A, B, strict=True):
            for _co, i, _d in tree.find_range(Vector(((a + b) / 2).tolist()), float(np.linalg.norm(b - a)) / 2 + lo_d):
                near.add(first[i])
        if grid:
            # along the run a place every `cell`, the cells around it: no point closer than lo_d is missed
            box_lo = (np.minimum(A, B).min(axis=0) - lo_d).tolist()
            box_hi = (np.maximum(A, B).max(axis=0) + lo_d).tolist()
            cells = set()
            for a, b in zip(A.tolist(), B.tolist(), strict=True):
                steps = int(math.dist(a, b) / cell) + 1
                for k in range(steps + 1):
                    t = k / steps
                    cells.add(_cell([a[k] + (b[k] - a[k]) * t for k in range(3)], cell))
            beside = (-1, 0, 1)
            around = {(x + dx, y + dy, z + dz) for x, y, z in cells for dx in beside for dy in beside for dz in beside}
            for key in around:
                for v in grid.get(key, ()):
                    if all(box_lo[k] <= v.co[k] <= box_hi[k] for k in range(3)):
                        near.add(v)
        near = [v for v in near if v.is_valid]
        learn(near)
        faces, seen = [], set()
        for v in near:
            if cache[v] >= lo_d:
                continue
            for f in v.link_faces:
                if f not in seen:
                    seen.add(f)
                    faces.append(f)
        if not faces:
            continue
        learn({v for f in faces for v in f.verts})
        # the edges of those faces that cross the border of the rounding get a point there
        crossing, maybe = set(), set()
        for f in faces:
            for e in f.edges:
                da, db = cache[e.verts[0]], cache[e.verts[1]]
                if min(da, db) < lo_d and max(da, db) > hi_d:
                    crossing.add(e)
                elif min(da, db) < lo_d <= max(da, db) and e.calc_length() > EDGE_LONG * width:
                    maybe.add(e)                    # ends on the border: does it leave the rounding before?
        span = {}                                   # per such edge: the part of it (from the near end) looked at
        if maybe:
            maybe = list(maybe)
            near = [(e.verts[0], e.verts[1]) if cache[e.verts[0]] <= cache[e.verts[1]] else (e.verts[1], e.verts[0])
                    for e in maybe]
            p0, p1 = (np.array([tuple(pair[k].co) for pair in near], np.float64) for k in (0, 1))
            for part in (0.25, 0.5, 0.75):
                d_part = at_many(p0 + (p1 - p0) * part)
                for e, d in zip(maybe, d_part.tolist(), strict=True):
                    if d > hi_d and e not in span:
                        span[e] = (part, d)
            crossing.update(span)
        if crossing:
            crossing = list(crossing)
            ends = [(e.verts[0], e.verts[1]) if cache[e.verts[0]] <= cache[e.verts[1]] else (e.verts[1], e.verts[0])
                    for e in crossing]              # the nearer end first
            part = np.array([span[e][0] if e in span else 1.0 for e in crossing])
            pa, pb = (np.array([tuple(pair[k].co) for pair in ends], np.float64) for k in (0, 1))
            pb = pa + (pb - pa) * part[:, None]     # (an edge that leaves before its end: up to where it is outside)
            da = np.array([cache[pair[0]] for pair in ends])
            db = np.array([span[e][1] if e in span else cache[pair[1]] for e, pair in zip(crossing, ends, strict=True)])
            t = (width - da) / (db - da)
            live = np.arange(len(t))
            # the distance from a bent run is not straight along the edge: the step is taken as if it were, but only
            # inside what is known - the near end lies inside the rounding, the far end outside. (Maintainer
            # 2026-10-14, 18747 with Edges: Bevel, dark wedges at the rounded corners: an edge that leaves the rim
            # beside a corner is nearest to the other rim further on; the plain step jumped back and forth between
            # the end of the edge and the first guess, and after three rounds the point sat 0.002 mm from the rim -
            # no support edge there, 22 faces of the viewport copy still reached from inside the rounding to outside.)
            t_in, t_out = np.zeros(len(t)), np.ones(len(t))
            for _again in range(EDGE_STEPS):
                d = at_many(pa[live] + (pb[live] - pa[live]) * t[live, None])
                off = np.abs(d - width) >= 0.01 * width
                live, d = live[off], d[off]
                if not len(live):
                    break
                inside = d < width
                t_in[live] = np.where(inside, t[live], t_in[live])
                t_out[live] = np.where(inside, t_out[live], t[live])
                step = t[live] + (width - d) / np.maximum(db[live] - da[live], 1e-9)
                between = (step > t_in[live]) & (step < t_out[live])
                t[live] = np.clip(np.where(between, step, 0.5 * (t_in[live] + t_out[live])), 0.001, 0.999)
            for e, pair, t_e in zip(crossing, ends, (t * part).tolist(), strict=True):
                _ne, nv = bmesh.utils.edge_split(e, pair[0], t_e)
                cache[nv] = width
                grid.setdefault(_cell(nv.co, cell), []).append(nv)
        # ... and each face is cut from point to point on that border, round every stretch of its outline outside
        work = list(faces)
        while work:
            f = work.pop()
            if not f.is_valid:
                continue
            vs = list(f.verts)
            n = len(vs)
            cls = [0 if dist(v) < lo_d else 2 if dist(v) > hi_d else 1 for v in vs]
            if 0 not in cls or (2 not in cls and cls.count(1) < 3):
                continue
            # each stretch of the outline on or beyond the border, between two points inside: from its first point
            # to its last - if both lie on the border and at least one point lies between them
            cut, start = None, cls.index(0)
            i = 1
            while i < n and cut is None:
                if cls[(start + i) % n] == 0:
                    i += 1
                    continue
                k = i
                while k + 1 < n and cls[(start + k + 1) % n] != 0:
                    k += 1
                a, b = (start + i) % n, (start + k) % n
                if (k - i >= 2 and cls[a] == 1 and cls[b] == 1 and bm.edges.get((vs[a], vs[b])) is None
                        and _has_area(vs, a, b)):
                    cut = (vs[a], vs[b])
                i = k + 1
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
    face = np.repeat(np.arange(nf), lt)
    return n.reshape(-1, 3), co.reshape(-1, 3)[lv], fn.reshape(-1, 3)[face], face, ls, lt


def carry_normals(me, before):
    """Custom normals for `me` from `before`, the same surface with other points: a corner takes the normal `before`
    has at that place - at a point that was there the normal of the same corner, elsewhere the normals of the old
    face's corners weighted for the place. Returns the number of corners that were weighted."""
    on, oco, ofn, _of, ols, olt = _corner_data(before)
    _n, co, fn, face, _ls, _lt = _corner_data(me)
    out = np.zeros((len(co), 3), np.float64)
    # a corner that was there: the same place (to 0.0001) on a face of the same direction (to 0.01)
    old_key = np.hstack([np.rint(oco * np.float32(1e4)), np.rint(ofn * np.float32(100.0))]).astype(np.int64)
    new_key = np.hstack([np.rint(co * np.float32(1e4)), np.rint(fn * np.float32(100.0))]).astype(np.int64)
    mix = np.array([0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9,
                    0x27D4EB2F165667C5, 0x85EBCA77C2B2AE63, 0xFF51AFD7ED558CCD], np.uint64)
    with np.errstate(over="ignore"):                # one number per corner; what it finds is compared in full below
        old_hash = (old_key.astype(np.uint64) * mix).sum(axis=1)
        new_hash = (new_key.astype(np.uint64) * mix).sum(axis=1)
    uniq, first = np.unique(old_hash, return_index=True)
    at = np.minimum(np.searchsorted(uniq, new_hash), len(uniq) - 1)
    j = first[at]
    same = (uniq[at] == new_hash) & (old_key[j] == new_key).all(axis=1)
    out[same] = on[j[same]]
    moved = np.nonzero(~same)[0].tolist()
    if moved:
        verts = np.zeros(len(before.vertices) * 3, np.float32)
        before.vertices.foreach_get("co", verts)
        tree = BVHTree.FromPolygons(verts.reshape(-1, 3).tolist(), [tuple(p.vertices) for p in before.polygons])
        centre = np.zeros(len(me.polygons) * 3, np.float32)
        me.polygons.foreach_get("center", centre)
        centre = centre.reshape(-1, 3)
        old_fn = np.zeros(len(before.polygons) * 3, np.float32)
        before.polygons.foreach_get("normal", old_fn)
        old_fn = old_fn.reshape(-1, 3)
        most = int(olt.max())
        places, toward, own = co[moved].tolist(), centre[face[moved]].tolist(), fn[moved].tolist()
        outline, got, at_face, weights = {}, [], [], []
        for m, i in enumerate(moved):
            p = Vector(places[m])
            inward = p.lerp(Vector(toward[m]), 0.05)        # a little inside the face: which old face it is
            _loc, _nor, f, dist = tree.find_nearest(inward)
            if f is None:
                out[i] = fn[i]
                continue
            n_own = Vector(own[m])
            if n_own.dot(Vector(old_fn[f].tolist())) < CARRY_SAME:
                # the nearest old face is not the one this corner lies on (library run 281: the rail 85977 had 3,585
                # corners with the normal of a face looking the other way): the one near by that looks its way
                f = max((hit[2] for hit in tree.find_nearest_range(inward, dist + CARRY_NEAR)),
                        key=lambda g: n_own.dot(Vector(old_fn[g].tolist())))
                if n_own.dot(Vector(old_fn[f].tolist())) < CARRY_SAME:
                    out[i] = fn[i]
                    continue
            pts = outline.get(f)
            if pts is None:
                a = int(ols[f])
                pts = outline[f] = [Vector(c) for c in oco[a:a + int(olt[f])].tolist()]
            w = poly_3d_calc(pts, p)
            got.append(i)
            at_face.append(f)
            weights.append(list(w) + [0.0] * (most - len(w)))
        if got:
            got, at_face, weights = np.array(got), np.array(at_face), np.array(weights)
            # (weight 0 beyond the corners of the face)
            corner = np.minimum(ols[at_face][:, None] + np.arange(most)[None, :], len(on) - 1)
            v = (weights[:, :, None] * on[corner]).sum(axis=1)
            flat = np.linalg.norm(v, axis=1) <= 1e-9
            v[flat] = fn[got[flat]]
            out[got] = v
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
    if not turned.any() or not len(la):
        return 0
    nf, nv, reach = len(me.polygons), len(me.vertices), EDGE_REACH * width
    ls = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.zeros(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    co = np.zeros(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    of_turned = np.repeat(np.logical_or.reduceat(turned, ls), lt)           # per corner: its face has a turned corner
    points = np.unique(lv[of_turned])
    tree = KDTree(len(points))
    for i, c in enumerate(co[points].tolist()):
        tree.insert(c, i)
    tree.balance()
    # per point the distance from the nearest rounded edge, as far as `reach` (further counts as far)
    vi, li = [], []
    mid, radius = ((la + lb) / 2).tolist(), (np.linalg.norm(lb - la, axis=1) / 2 + reach).tolist()
    for i, (c, r) in enumerate(zip(mid, radius, strict=True)):
        found = tree.find_range(Vector(c), r)
        vi.extend(f[1] for f in found)
        li.extend([i] * len(found))
    far = np.full(nv, np.inf)
    if vi:
        vi, li = points[np.array(vi, np.int64)], np.array(li, np.int64)
        ab = lb[li] - la[li]
        t = np.clip(((co[vi] - la[li]) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-18), 0.0, 1.0)
        np.minimum.at(far, vi, np.linalg.norm(co[vi] - (la[li] + ab * t[:, None]), axis=1))
    streak = of_turned & np.repeat(np.maximum.reduceat(far[lv], ls) > reach, lt)
    count = int(np.logical_and.reduceat(streak, ls).sum())
    if count:
        n[streak] = plain[streak]
        me.normals_split_custom_set(n.tolist())
        me.update()
    return count
