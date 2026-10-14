"""Shrink compensation (UPDATES #51) - round surfaces keep their size through the subdivision.

The smooth surface of Catmull-Clark lies inside its cage wherever the cage is round: a 16-sided cylinder loses about
2.5 % of its radius at the corners of the cage. Where two pieces of a part only touch in the import (a cylinder lying
on a block, 3839v2), the subdivision opened a gap between them (maintainer 2026-10-14: "Durch die Schrumpfung bei
SubDiv entstehen Lücken und Abstände." - "Im Grunde eine Skalierung über die Normalen, aber das darf nur runde Formen
betreffen, die shrinken. Ein Würfel ist ja nicht betroffen."). Measured before (run 286): render copies up to 0.10 to
0.16 mm inside the import.

How: every point of the welded cage is moved until the point of the smooth surface that belongs to it (Blender's
subdivision keeps the cage's point numbers for them: subdiv_foreach.cc, vertices_corner_offset = 0) lies on the
import point again - a few rounds of subdivide, measure, correct. Where the surface does not shrink - flat faces,
fully creased edges and corners, a cube - the two are the same and nothing moves. On a round surface the correction
points along the normal: the scaling over the normals the maintainer described; on a creased round rim it points
outwards in the plane of the rim.

Left free: the middle points of coarse roundings (W17) - they are meant to give a little, a rounding that went back
through the import corner would be sharp again.
"""
import numpy as np

from . import workscene

SHRINK_ROUNDS = 6           # subdivide, measure, correct - at most; a round that leaves more than the one before ends it
SHRINK_GROW = 1.5           # a point moves at most this many times its own measured shrink (a uniform cylinder: 1)
SHRINK_STEP = 0.7           # share of the measured shrink corrected per round (the full step overshot on 3839v2)
SHRINK_MIN = 1e-5           # mm: a point that lies this close to its place is left
SHRINK_MAX = 0.3            # mm: no point moves further from where it was (a wild correction stays out)
SHRINK_SHARE = 0.15         # a point takes part when its shrink is at most this share of its cage edges' length
SHRINK_FREE = "_shrink_free"        # report key: points of the cage that are left free (W17)


def _limit_points(work, n):
    """The points of the smooth surface that belong to the first `n` points of the cage of `work` (level 1 of its
    Subdivision modifier, limit surface on), and the surface's normals there."""
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
            nor = np.zeros(len(me.vertices) * 3, np.float64)
            me.vertex_normals.foreach_get("vector", nor)
        finally:
            ev.to_mesh_clear()
    finally:
        mod.levels = keep
    return co.reshape(-1, 3)[:n], nor.reshape(-1, 3)[:n]


def _edge_scale(wm):
    """Per point of `wm`: the mean length of its edges."""
    ev = np.zeros(len(wm.edges) * 2, np.int32)
    wm.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    co = np.zeros(len(wm.vertices) * 3, np.float64)
    wm.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    length = np.linalg.norm(co[ev[:, 0]] - co[ev[:, 1]], axis=1)
    total, count = np.zeros(len(co)), np.zeros(len(co))
    for k in (0, 1):
        np.add.at(total, ev[:, k], length)
        np.add.at(count, ev[:, k], 1.0)
    return total / np.maximum(count, 1.0)


def compensate_shrink(work, wm, free=()):
    """Move the points of the cage `wm` (on the object `work` with its Subdivision modifier) along the normal until
    the smooth surface passes through where they are now. Only round surfaces whose shrink is small against the
    cage's edges there: a rounding Mecabricks modelled much finer than its cage (the rim of a stud: 0.2 mm on edges of
    0.2 mm) cannot be pulled back to its corner and is left (run 286, 3839v2: there the correction ran away and folded
    the faces). `free`: indices of points left as they are. Returns (points moved, largest move in mm, what is left
    on the points moved after the last round in mm); keeps the old places for undo_shrink."""
    n = len(wm.vertices)
    if not n or work.modifiers.get("Subdivision") is None:
        return 0, 0.0, 0.0
    target = np.zeros(n * 3, np.float64)
    wm.vertices.foreach_get("co", target)
    target = target.reshape(-1, 3)
    co = target.copy()
    hold = np.zeros(n, bool)
    hold[list(free)] = True
    scale = _edge_scale(wm)
    best, best_left = co.copy(), np.inf
    for round_ in range(SHRINK_ROUNDS + 1):
        limit, nor = _limit_points(work, n)
        along = ((target - limit) * nor).sum(axis=1)
        if round_ == 0:                             # which points take part: decided once, on the first measure
            hold |= np.abs(along) > SHRINK_SHARE * scale
            hold |= np.abs(along) < SHRINK_MIN
            reach = SHRINK_GROW * np.abs(along)     # how far each point may go: its own shrink and a half
        along[hold] = 0.0
        take = ~hold
        left = float(np.abs(along[take]).mean()) if take.any() else 0.0     # the mean: one stubborn point must
        if left < best_left:                        # not end the rounds; the best cage so far, a worse round undone
            best, best_left = co.copy(), left
        elif round_:
            break
        if round_ == SHRINK_ROUNDS or left < SHRINK_MIN:
            break
        co = co + nor * (SHRINK_STEP * along)[:, None]
        away = co - target
        far = np.linalg.norm(away, axis=1)
        cap = np.minimum(reach, SHRINK_MAX)
        over = far > cap
        co[over] = target[over] + away[over] * (cap[over] / far[over])[:, None]
        wm.vertices.foreach_set("co", co.astype(np.float32).ravel())
        wm.update()
    if not np.array_equal(best, co):
        co = best
        wm.vertices.foreach_set("co", co.astype(np.float32).ravel())
        wm.update()
    moved = np.linalg.norm(co - target, axis=1)
    if not (moved > SHRINK_MIN).any():
        return 0, 0.0, 0.0
    WAS[wm.name] = target
    limit, nor = _limit_points(work, n)
    rest = np.abs(((target - limit) * nor).sum(axis=1))[~hold]
    return int((moved > SHRINK_MIN).sum()), round(float(moved.max()), 5), round(float(rest.max()) if len(rest) else 0.0, 5)


def undo_shrink(work, wm):
    """Put the points of `wm` back where they were before compensate_shrink. Returns True if there was something."""
    was = WAS.pop(wm.name, None)
    if was is None or len(was) != len(wm.vertices):
        return False
    wm.vertices.foreach_set("co", was.astype(np.float32).ravel())
    wm.update()
    workscene.depsgraph_of(work).update()
    return True


WAS = {}                    # cage name -> the places before the compensation (undo_shrink)
