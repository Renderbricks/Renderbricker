"""W28 (rework 2, run 306): two shells lying on each other in one plane - the copy of the smaller one goes a hair
behind the other.

Some imports cover a flat wall twice: a face of one shell lies in the plane of a face of another shell, facing the
same way (43712: the triangles 562 and 564 on the inner wall x = 8.04, 1.5 mm2). Exactly coincident faces are noise
for a ray tracer: the camera ray meets one of them, the shadow ray from there meets the other - black slivers in
Cycles (seen from the front: no back of a face, no open edge off its surface, so neither check saw them). The import
shows the same place as a grey band; in the copy, whose two faces are cut into children that differ, the noise
becomes hard black stripes. The import's meshes are not touched; in the copy the points of the covered children of
the smaller shell move COVER_SINK along their normal, under the other shell.
"""
import numpy as np
from mathutils.bvhtree import BVHTree

from . import meshparts

COVER = 2e-5                # mm: faces this close in one plane cover each other
COVER_COS = 0.9999          # ... their normals within 0.8 degrees
COVER_SINK = 0.003          # mm: the covered points of the smaller shell go this far behind
COVER_MIN = 0.01            # mm2: smaller triangles are not asked - small covers are left (92092: 72 of 0.003 mm2 and less between its
                            # shells that only touch; sinking them lifted 31 folded slivers out of the plane)
COVER_MAX = 400_000         # triangles: a larger copy is left (prototype: the loop below is Python)
SUNK = [0]                  # points moved on the last copy - read by the tests


def _arrays(cp):
    co = meshparts.positions(cp)
    lv = meshparts.corner_verts(cp)
    cp.calc_loop_triangles()
    nt = len(cp.loop_triangles)
    tl = meshparts.fget(cp.loop_triangles, "loops", nt * 3, np.int64)
    tp = meshparts.fget(cp.loop_triangle_polygons, "value", nt, np.int64)
    tri = lv[tl].reshape(-1, 3)
    tn = np.cross(co[tri[:, 1]] - co[tri[:, 0]], co[tri[:, 2]] - co[tri[:, 0]])
    ta = np.linalg.norm(tn, axis=1) / 2
    tn /= np.maximum(2 * ta, 1e-30)[:, None]
    return co, tri, tp, tn, ta


def pairs(cp):
    """The triangles of `cp` whose middle lies on another triangle in one plane with it, facing the same way - not of
    its own face, and the middle well inside its own triangle (a neighbour in the same plane only touches its edge):
    (triangle, the triangle under or over it), and the arrays."""
    co, tri, tp, tn, ta = _arrays(cp)
    out = []
    if not len(tri) or len(tri) > COVER_MAX:
        return out, (co, tri, tp, tn, ta)
    tree = BVHTree.FromPolygons(co.tolist(), tri.tolist())
    p = co[tri]
    cen = p.mean(axis=1)
    longest = np.maximum(np.maximum(np.linalg.norm(p[:, 1] - p[:, 0], axis=1), np.linalg.norm(p[:, 2] - p[:, 1], axis=1)),
                         np.linalg.norm(p[:, 0] - p[:, 2], axis=1))
    inside = 2 * ta / np.maximum(longest, 1e-30) / 3          # the middle's distance to the longest edge
    ask = np.nonzero((ta > COVER_MIN) & (inside > 20 * COVER))[0]
    for t, c in zip(ask.tolist(), cen[ask].tolist(), strict=True):      # (the middles as Python lists at once)
        for _loc, _n, t2, _d in tree.find_nearest_range(c, COVER):
            if tp[t2] != tp[t] and float(tn[t] @ tn[t2]) > COVER_COS:
                out.append((t, t2))
                break
    return out, (co, tri, tp, tn, ta)


def sink(cp, parent=None):
    """Move the covered points COVER_SINK behind: of every pair the triangle whose import face (`parent`: per face of
    the copy its import face's number and area; without it the copy's own face) is the smaller one - but not its
    points that the covering face's children use too (the hinge the two share stays). Returns the points moved."""
    SUNK[0] = 0
    found, (co, tri, tp, tn, _ta) = pairs(cp)
    if not found:
        return 0
    if parent is None:
        area = meshparts.fget(cp.polygons, "area", len(cp.polygons))
        own = np.arange(len(cp.polygons))
    else:
        own, area = parent
    move = np.zeros((len(co), 3))
    hit = np.zeros(len(co), bool)
    keep = np.zeros(len(co), bool)
    down, up = set(), set()
    for t, t2 in found:
        fa, fb = tp[t], tp[t2]
        if own[fa] == own[fb]:
            continue
        if (area[own[fa]], -own[fa]) < (area[own[fb]], -own[fb]):         # the smaller import face goes down
            down.add(int(own[fa])); up.add(int(own[fb]))
            move[tri[t]] -= tn[t]
            hit[tri[t]] = True
    if not hit.any():
        return 0
    up -= down
    keep[tri[np.isin(own[tp], sorted(up))].ravel()] = True     # the points of the covering faces stay
    hit &= ~keep
    if not hit.any():
        return 0
    ln = np.linalg.norm(move[hit], axis=1)
    move[~hit] = 0.0
    move[hit] = move[hit] / np.maximum(ln, 1e-30)[:, None] * COVER_SINK
    normals = np.zeros(len(cp.loops) * 3, np.float32)
    custom = cp.has_custom_normals
    if custom:
        cp.corner_normals.foreach_get("vector", normals)
    cp.vertices.foreach_set("co", (co + move).astype(np.float32).ravel())
    cp.update()
    if custom:
        cp.normals_split_custom_set(normals.reshape(-1, 3))
    SUNK[0] = int(hit.sum())
    return SUNK[0]
