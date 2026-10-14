"""Shrink compensation (UPDATES #51) - round shapes keep their size through the subdivision (rule W19).

The smooth surface of Catmull-Clark lies inside its cage wherever the cage is round: a 16-sided cylinder loses about
2.5 % of its radius at the corners of the cage. Where two pieces of a part only touch in the import (a handle lying on
a plate, 3839v2), the subdivision opened a gap between them (maintainer 2026-10-14: "Durch die Schrumpfung bei SubDiv
entstehen Lücken und Abstände." - "Im Grunde eine Skalierung über die Normalen, aber das darf nur runde Formen
betreffen, die shrinken. Ein Würfel ist ja nicht betroffen."). Measured before (run 286): render copies up to 0.10 to
0.16 mm inside the import.

What is round: a smooth region of the welded cage (faces joined by edges that are not fully creased) that is a whole
cylinder - every face normal square to one axis, the points all round it (no gap of more than SHRINK_GAP degrees) and
at one distance from it (within SHRINK_TRUE of the radius). Bars, studs, tubes, axles, the walls of holes. Not round:
a rounding along an edge, the ends of a flat part (maintainer, after the first build: "Da darf auch nicht in jede
Richtung gegenkorrigiert werden. Z.B. flaches Teil mit zwei Rundungen rechts und links. Das wird dann auch leicht
dicker in der Höhe. Das darf nicht passieren."), a collar round a hole, a bent bar. The first build corrected every
point along its normal: flat parts with rounded edges grew in height, collars came out wavy, and the custom normals
of the moved points tipped with their faces (knotted shading, the maintainer's screenshots of 2026-10-14).

How: every point of a cylinder moves away from its axis - square to it, never along it - until the point of the
smooth surface that belongs to it (Blender's subdivision keeps the cage's point numbers for them: subdiv_foreach.cc,
vertices_corner_offset = 0) lies at the import point's distance from the axis again; damped rounds, the best kept,
no point further than SHRINK_GROW times its own shrink. Only shrink is corrected, never the other way. The cage's
custom normals are set again afterwards as they were (they are stored relative to the faces).
"""
import math

import numpy as np

from . import meshparts, workscene

SHRINK_ROUNDS = 6           # subdivide, measure, correct - at most; a round that leaves more than the one before ends it
SHRINK_STEP = 0.7           # share of the measured shrink corrected per round (the full step overshot on 3839v2)
SHRINK_GROW = 1.5           # a point moves at most this many times its own measured shrink (a uniform cylinder: 1)
SHRINK_MIN = 1e-5           # mm: a point that lies this close to its place is left
SHRINK_MAX = 0.3            # mm: no point moves further from where it was
SHRINK_SQUARE = 0.1         # a cylinder: every face normal within this cosine of square to the axis
SHRINK_GAP = 45.0           # ... its points all round the axis, no gap wider than this (degrees)
SHRINK_TRUE = 0.03          # ... and at one distance from it, within this share of the radius
SHRINK_FREE = "_shrink_free"        # report key: points of the cage that are left free (W17)


def _regions(wm):
    """The smooth regions of `wm`: faces joined by edges that are not fully creased. Returns a list of face index
    arrays."""
    nf = len(wm.polygons)
    parent = list(range(nf))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ce = wm.attributes.get("crease_edge")
    crease = np.zeros(len(wm.edges), np.float32)
    if ce is not None:
        ce.data.foreach_get("value", crease)
    key_index = {e.key: e.index for e in wm.edges}
    edge_faces = {}
    for p in wm.polygons:
        for k in p.edge_keys:
            edge_faces.setdefault(k, []).append(p.index)
    for k, fs in edge_faces.items():
        if len(fs) == 2 and crease[key_index[k]] < 0.99:
            a, b = find(fs[0]), find(fs[1])
            if a != b:
                parent[a] = b
    roots = np.array([find(i) for i in range(nf)])
    return [np.nonzero(roots == r)[0] for r in np.unique(roots)]


def _cylinder(wm, faces, co):
    """(point on the axis, axis) of the region `faces` if it is a whole cylinder, else None."""
    if len(faces) < 4:
        return None
    fn = np.array([wm.polygons[i].normal[:] for i in faces])
    area = np.array([wm.polygons[i].area for i in faces])
    if area.sum() <= 0:
        return None
    _w, vec = np.linalg.eigh((fn * area[:, None]).T @ fn)
    axis = vec[:, 0]
    if np.abs(fn @ axis).max() > SHRINK_SQUARE:
        return None
    pts = co[np.unique([v for i in faces for v in wm.polygons[i].vertices])]
    u = np.cross(axis, [1.0, 0.0, 0.0] if abs(axis[0]) < 0.9 else [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    w = np.cross(axis, u)
    x, y = pts @ u, pts @ w
    sol = np.linalg.lstsq(np.c_[x, y, np.ones(len(x))], -(x * x + y * y), rcond=None)[0]
    cx, cy = -sol[0] / 2, -sol[1] / 2
    r2 = cx * cx + cy * cy - sol[2]
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    if np.abs(np.hypot(x - cx, y - cy) - r).max() > SHRINK_TRUE * r:
        return None
    ang = np.sort(np.degrees(np.arctan2(y - cy, x - cx)))
    if np.diff(np.r_[ang, ang[0] + 360.0]).max() > SHRINK_GAP:
        return None
    return u * cx + w * cy, axis


def _limit_points(work, n):
    """The points of the smooth surface that belong to the first `n` points of the cage of `work` (level 1 of its
    Subdivision modifier, limit surface on)."""
    mod = work.modifiers.get("Subdivision")
    keep = mod.levels
    mod.levels = 1
    try:
        dg = workscene.depsgraph_of(work)
        dg.update()
        ev = work.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            co = np.zeros(len(me.vertices) * 3, np.float64)
            me.vertices.foreach_get("co", co)
        finally:
            ev.to_mesh_clear()
    finally:
        mod.levels = keep
    return co.reshape(-1, 3)[:n]


def compensate_shrink(work, wm, free=()):
    """Widen the whole cylinders of the cage `wm` (on the object `work` with its Subdivision modifier) square to
    their axes until the smooth surface has the import's distance from the axis again. `free`: indices of points
    left as they are. Returns (points moved, largest move in mm, largest shrink left on them in mm, cylinders);
    keeps the old places for undo_shrink."""
    n = len(wm.vertices)
    if not n or not len(wm.polygons) or work.modifiers.get("Subdivision") is None:
        return 0, 0.0, 0.0, 0
    target = np.zeros(n * 3, np.float64)
    wm.vertices.foreach_get("co", target)
    target = target.reshape(-1, 3)
    centre, axis = np.zeros((n, 3)), np.zeros((n, 3))
    on = np.zeros(n, bool)
    found = 0
    for faces in _regions(wm):
        cyl = _cylinder(wm, faces, target)
        if cyl is None:
            continue
        found += 1
        pts = np.unique([v for i in faces for v in wm.polygons[i].vertices])
        pts = pts[~on[pts]]
        centre[pts], axis[pts], on[pts] = cyl[0], cyl[1], True
    on[list(free)] = False
    if not on.any():
        return 0, 0.0, 0.0, found
    radial = target - centre
    radial -= axis * (radial * axis).sum(axis=1)[:, None]
    radial /= np.maximum(np.linalg.norm(radial, axis=1), 1e-12)[:, None]
    normals = np.zeros(len(wm.loops) * 3, np.float32)
    wm.corner_normals.foreach_get("vector", normals)
    # every island of the cage goes its own rounds (UPDATES #54): its shrink left is its own mean, its best round is
    # kept and it stops on its own - the rounds of one stud do not depend on the other studs of a baseplate, so a
    # large mesh can be converted in batches of islands with the same result
    _ids, isl = np.unique(meshparts.point_islands(wm), return_inverse=True)
    k = len(_ids)
    co, best, best_left, reach = target.copy(), target.copy(), np.full(k, np.inf), None
    active = np.ones(k, bool)
    for round_ in range(SHRINK_ROUNDS + 1):
        out = ((target - _limit_points(work, n)) * radial).sum(axis=1)     # > 0: the surface lies nearer the axis
        if reach is None:                           # who takes part, and how far: decided on the first measure
            on &= out > SHRINK_MIN
            reach = np.minimum(SHRINK_GROW * np.maximum(out, 0.0), SHRINK_MAX)
            active &= np.bincount(isl[on], minlength=k) > 0
        out = np.where(on, np.maximum(out, 0.0), 0.0)       # only shrink is corrected
        count = np.bincount(isl[on], minlength=k)
        left = np.bincount(isl[on], weights=out[on], minlength=k) / np.maximum(count, 1)
        better = active & (left < best_left)
        take = better[isl]
        best[take], best_left[better] = co[take], left[better]
        if round_:
            active &= better                        # a round that leaves more than the one before ends the island
        active &= ~((round_ == SHRINK_ROUNDS) | (left < SHRINK_MIN))
        if not active.any():
            break
        step = active[isl]
        co[step] = co[step] + radial[step] * (SHRINK_STEP * out[step])[:, None]
        far = ((co - target) * radial).sum(axis=1)
        over = step & (far > reach)
        co[over] = target[over] + radial[over] * reach[over, None]
        wm.vertices.foreach_set("co", co.astype(np.float32).ravel())
        wm.update()
    co = best
    wm.vertices.foreach_set("co", co.astype(np.float32).ravel())
    wm.update()
    wm.normals_split_custom_set(normals.reshape(-1, 3))       # the normals as they were, on the new places
    moved = np.linalg.norm(co - target, axis=1)
    if not (moved > SHRINK_MIN).any():
        return 0, 0.0, 0.0, found
    rest = np.maximum(((target - _limit_points(work, n)) * radial).sum(axis=1), 0.0)[on]
    WAS[wm.name] = (target, normals)
    return (int((moved > SHRINK_MIN).sum()), round(float(moved.max()), 5),
            round(float(rest.max()) if len(rest) else 0.0, 5), found)


def undo_shrink(work, wm, faces=None):
    """Put the points of `wm` back where they were before compensate_shrink - all, or (UPDATES #54) those of the
    islands of `faces`. Returns the number of points moved back."""
    was = WAS.get(wm.name)
    if was is None or len(was[0]) != len(wm.vertices):
        return 0
    co = np.zeros(len(wm.vertices) * 3, np.float64)
    wm.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    pick = np.ones(len(co), bool)
    if faces is not None:
        lab = meshparts.point_islands(wm)
        lv = np.empty(len(wm.loops), np.int64); wm.loops.foreach_get("vertex_index", lv)
        ls = np.empty(len(wm.polygons), np.int64); wm.polygons.foreach_get("loop_start", ls)
        pick = np.isin(lab, lab[lv[ls[np.asarray(sorted(faces), np.int64)]]])
    back = pick & (np.abs(co - was[0]).max(axis=1) > 0)
    if faces is None or back.all() or pick.all():
        WAS.pop(wm.name, None)
    co[pick] = was[0][pick]
    wm.vertices.foreach_set("co", co.astype(np.float32).ravel())
    wm.update()
    wm.normals_split_custom_set(was[1].reshape(-1, 3))
    workscene.depsgraph_of(work).update()
    return int(back.sum())


WAS = {}                    # cage name -> (the places, the corner normals) before the compensation (undo_shrink)
