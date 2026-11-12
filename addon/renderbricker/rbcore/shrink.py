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
import itertools
import math

import numpy as np

from . import cagegeom, meshparts, workscene

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

COARSE = 0.17               # a point whose residual is larger than this x its shortest edge is a coarse corner, no rounding
CHAIN_LAM = 1e-6            # the damping of a chain run that has coarse corners (their moves are then free)


def fit_chains(T, C, d, moved):
    """W22 (rules 3.16, run 303 stage 1): the points of hard chains move square to their chain - the directions `u` of
    cagegeom.classes - until their limit point (x[a] + 4 x[i] + x[b]) / 6 (a point with two hard edges, the creases
    infinitely sharp) lies on the import point q[i] in those directions; x = q + d. `T`, `C`: cagegeom.arrays /
    classes of the cage at the import's places; `d` (n,3) the moves so far (W19's); `moved` (n) the points W19 moved -
    they keep their place, as every point that does not move, and count as fixed neighbours.
    Solved exactly per connected run of moving chain points. A coarse corner (residual before the solve larger than
    COARSE x its shortest edge) keeps its unknowns and loses its equations; a run with one is solved damped,
    |M a - b|^2 + CHAIN_LAM |a|^2. No point further than SHRINK_GROW x its own residual and SHRINK_MAX (cut).
    Returns (the moves (n,3), points moved, coarse corners left, cut (n) bool). No Blender call."""
    n = T["n"]
    q = np.asarray(T["co"], np.float64)
    d = np.asarray(d, np.float64)
    d_new = d.copy()
    cut = np.zeros(n, bool)
    nb, u = C["nb"], C["u"]
    act = (C["kind"] == 2) & (C["ku"] > 0) & ~np.asarray(moved, bool)
    if not act.any():
        return d_new, 0, 0, cut
    # the residual before the solve, in the move directions (unused directions of u are zero rows)
    x = q + d
    idx = np.nonzero(act)[0]
    lim = (x[nb[idx, 0]] + 4.0 * x[idx] + x[nb[idx, 1]]) / 6.0
    b = np.einsum("nkj,nj->nk", u[idx], q[idx] - lim)                  # (m,2)
    own = np.linalg.norm(b, axis=1)
    coarse = own > COARSE * C["short"][idx]
    b[coarse] = 0.0                                                     # a coarse corner has no equation
    # the runs: moving chain points joined by their hard edges
    pos = np.full(n, -1, np.int64)
    pos[idx] = np.arange(len(idx))
    pa, pb = pos[nb[idx, 0]], pos[nb[idx, 1]]
    m = len(idx)
    lab = np.arange(m)              # every point's label: the smallest point of its run (label jumps, as cagegeom)
    while True:
        new = lab.copy()
        for p in (pa, pb):
            ok = np.nonzero(p >= 0)[0]
            low = np.minimum(new[ok], new[p[ok]])
            np.minimum.at(new, ok, low)
            np.minimum.at(new, p[ok], low)
        new = new[new]
        if np.array_equal(new, lab):
            break
        lab = new
    order = np.argsort(lab, kind="stable")
    bounds = np.r_[0, np.nonzero(np.diff(lab[order]))[0] + 1, m]
    rank = np.empty(m, np.int64)
    a_all = np.zeros((m, 2))
    for s, e in itertools.pairwise(bounds.tolist()):
        run = order[s:e]                                                # local numbers of the run's points
        k = len(run)
        rank[run] = np.arange(k)
        U = u[idx[run]]                                                 # (k,2,3)
        M = np.zeros((k, 2, k, 2))
        r = np.arange(k)
        M[r, :, r, :] = (4.0 / 6.0) * np.einsum("kij,klj->kil", U, U)
        for p in (pa, pb):
            nbp = p[run]
            ok = np.nonzero(nbp >= 0)[0]
            j = rank[nbp[ok]]
            M[ok, :, j, :] += (1.0 / 6.0) * np.einsum("kij,klj->kil", U[ok], U[j])
        M[coarse[run]] = 0.0                                            # no equations of coarse corners
        M = M.reshape(2 * k, 2 * k)
        rhs = b[run].reshape(-1)
        if coarse[run].any():
            M = np.vstack([M, math.sqrt(CHAIN_LAM) * np.eye(2 * k)])
            rhs = np.r_[rhs, np.zeros(2 * k)]
        a_all[run] = np.linalg.lstsq(M, rhs, rcond=None)[0].reshape(k, 2)
    dc = np.einsum("nk,nkj->nj", a_all, u[idx])
    # no point further than SHRINK_GROW x its own residual and SHRINK_MAX
    reach = np.minimum(SHRINK_GROW * own, SHRINK_MAX)
    far = np.linalg.norm(dc, axis=1)
    over = far > reach + 1e-9
    dc[over] *= (reach[over] / np.maximum(far[over], 1e-12))[:, None]
    d_new[idx] = d[idx] + dc
    cut[idx[over]] = True
    return d_new, int((np.linalg.norm(dc, axis=1) > SHRINK_MIN).sum()), int(coarse.sum()), cut


FIT_ROUNDS = 6              # W23: subdivide, measure, correct - at most
FIT_STEP = 0.8              # W23: share of the measured residual corrected per round


def _set_points(wm, x):
    wm.vertices.foreach_set("co", np.asarray(x, np.float32).ravel())
    wm.update()


def fit_surface(work, wm, T, C, d, held):
    """W23 (rules 3.16, run 303 stage 2): the surface points - no or one hard edge, the directions `u` of
    cagegeom.classes, one each: the point normal without the normals of its flat faces - move along that direction
    until their limit point lies on the import point in it, both signs. Rounds through Blender as W19's: residual
    r = u . (q - limit point) with the cage at q + d + the moves of the rounds; the first round decides who takes part
    (|r| > SHRINK_MIN, not a coarse corner: |r| <= COARSE x its shortest edge) and how far (min(SHRINK_GROW |r|,
    SHRINK_MAX)); every round moves by FIT_STEP r u; per island of the cage the round with the smallest mean |r| is
    kept and an island stops when a round leaves more than the one before. `held` (n) bool: points that keep their
    place (W19's). Leaves the cage at the places of its last round. Returns (the moves (n,3), points moved, coarse
    corners left, largest residual left on the points that took part in mm)."""
    n = T["n"]
    q = np.asarray(T["co"], np.float64)
    d = np.asarray(d, np.float64)
    on = (C["kind"] == 1) & (C["ku"] > 0) & ~np.asarray(held, bool)
    if not on.any() or work.modifiers.get("Subdivision") is None:
        return d.copy(), 0, 0, 0.0
    u = C["u"][:, 0]
    _ids, isl = np.unique(meshparts.point_islands(wm), return_inverse=True)
    k = len(_ids)
    dj, best = np.zeros((n, 3)), np.zeros((n, 3))
    best_r = np.zeros(n)
    best_left = np.full(k, np.inf)
    active = np.ones(k, bool)
    reach, coarse = None, 0
    for round_ in range(FIT_ROUNDS + 1):
        _set_points(wm, q + d + dj)
        r = ((q - _limit_points(work, n)) * u).sum(axis=1)
        if reach is None:                           # who takes part, and how far: decided on the first measure
            far_off = on & (np.abs(r) > COARSE * C["short"])
            coarse = int(far_off.sum())
            on &= (np.abs(r) > SHRINK_MIN) & ~far_off
            reach = np.minimum(SHRINK_GROW * np.abs(r), SHRINK_MAX)
            active &= np.bincount(isl[on], minlength=k) > 0
            if not active.any():
                break
        r = np.where(on, r, 0.0)
        count = np.bincount(isl[on], minlength=k)
        left = np.bincount(isl[on], weights=np.abs(r[on]), minlength=k) / np.maximum(count, 1)
        better = active & (left < best_left)
        take = better[isl]
        best[take], best_r[take], best_left[better] = dj[take], np.abs(r[take]), left[better]
        if round_:
            active &= better                        # a round that leaves more than the one before ends the island
        active &= ~((round_ == FIT_ROUNDS) | (left < SHRINK_MIN))
        if not active.any():
            break
        step = active[isl] & on
        dj[step] = dj[step] + u[step] * (FIT_STEP * r[step])[:, None]
        far = np.linalg.norm(dj, axis=1)
        over = step & (far > reach)
        dj[over] *= (reach[over] / np.maximum(far[over], 1e-12))[:, None]
    moved = np.linalg.norm(best, axis=1) > SHRINK_MIN
    return d + best, int(moved.sum()), coarse, round(float(best_r[on].max()) if on.any() else 0.0, 5)


def compensate(work, wm, free=()):
    """The shrink compensation of rules 3.16 on the cage `wm` (on the object `work` with its Subdivision modifier),
    in this order: W19 (compensate_shrink, as built - what it moves is done), W22 (fit_chains), W23 (fit_surface),
    W24 (contacts; not yet - its keys are 0). `free`: points left as they are (W17). No point moves further than
    SHRINK_MAX in all. The cage's custom normals are set again once at the end, as they were; WAS keeps the places
    and normals before W19 for undo_shrink. Returns a dict: points, max (mm), left (mm: the largest residual left -
    W19's shrink, W23's residual), cylinders, chain_points, surface_points, coarse_left, contact_points,
    contact_moved."""
    out = {"points": 0, "max": 0.0, "left": 0.0, "cylinders": 0, "chain_points": 0, "surface_points": 0,
           "coarse_left": 0, "contact_points": 0, "contact_moved": 0}
    n = len(wm.vertices)
    if not n or not len(wm.polygons) or work.modifiers.get("Subdivision") is None:
        return out
    T = cagegeom.arrays(wm)                         # the import's places and shading, before any move
    q = T["co"].copy()
    normals = np.zeros(len(wm.loops) * 3, np.float32)
    wm.corner_normals.foreach_get("vector", normals)
    _roots, flat = cagegeom.flat_faces(T)
    C = cagegeom.classes(T, free, flat)
    _pts19, _max19, left19, out["cylinders"] = compensate_shrink(work, wm, free)
    x = np.zeros(n * 3, np.float64)
    wm.vertices.foreach_get("co", x)
    d = x.reshape(-1, 3) - q
    moved = np.linalg.norm(d, axis=1) > 1e-6        # W19's points: done, the others build on their places
    d, out["chain_points"], coarse_c, _cut = fit_chains(T, C, d, moved)
    d, out["surface_points"], coarse_s, left_s = fit_surface(work, wm, T, C, d, moved)
    out["coarse_left"] = coarse_c + coarse_s
    far = np.linalg.norm(d, axis=1)
    d *= np.minimum(1.0, SHRINK_MAX / np.maximum(far, 1e-12))[:, None]       # no point further than SHRINK_MAX
    _set_points(wm, q + d)
    wm.normals_split_custom_set(normals.reshape(-1, 3))       # the normals as they were, on the new places
    x = np.zeros(n * 3, np.float64)
    wm.vertices.foreach_get("co", x)
    far = np.linalg.norm(x.reshape(-1, 3) - q, axis=1)
    if not (far > SHRINK_MIN).any():
        WAS.pop(wm.name, None)
        return out
    WAS[wm.name] = (q, normals)
    out.update({"points": int((far > SHRINK_MIN).sum()), "max": round(float(far.max()), 5),
                "left": round(max(float(left19), float(left_s)), 5)})
    return out
