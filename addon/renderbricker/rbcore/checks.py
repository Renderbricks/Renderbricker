"""Checks of a result: self-intersecting and broken faces of the import, folded (flipped) sub-faces."""
import numpy as np
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d
from . import config, copies


def self_intersecting(cos):
    """Polygon whose edges cross each other (bowtie quads in the import, run 29: Technic
    panels 87080/87086/64391/64683 of the Porsche). Checked in the polygon's own plane."""
    n = len(cos)
    if n < 4:
        return False
    nrm = max(((cos[(i + 1) % n] - cos[i]).cross(cos[(i + 2) % n] - cos[(i + 1) % n]) for i in range(n)),
              key=lambda v: v.length)
    if nrm.length < 1e-12:
        return False
    ax = nrm.normalized().orthogonal().normalized(); ay = nrm.normalized().cross(ax)
    P = [Vector((c.dot(ax), c.dot(ay))) for c in cos]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                      # adjacent through the wrap-around
            if intersect_line_line_2d(P[i], P[(i + 1) % n], P[j], P[(j + 1) % n]):
                return True
    return False


_broken = {}


def broken_faces(me):
    """K11: faces of the import without a meaningful normal – zero area or self-intersecting.
    The fold check skips them: their subdivision folds because the original does."""
    key = (me.as_pointer(), len(me.polygons), len(me.vertices))
    if key not in _broken:
        co = [v.co.copy() for v in me.vertices]
        _broken.clear()
        _broken[key] = {p.index for p in me.polygons
                        if p.area <= config.DEGENERATE_AREA or self_intersecting([co[i] for i in p.vertices])}
    return _broken[key]


def sub_offsets(me):
    """Start index of each original face's children in the evaluated mesh (level LEVELS)."""
    sizes = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", sizes)
    return np.concatenate(([0], np.cumsum(sizes * 4 ** (config.LEVELS - 1))))


def flipped_faces(ob, ev=None, me=None):
    """Original face indices whose subdivided children flip (> 90 deg).
    Vectorised (run 30): the same test as the old face-by-face loop, on arrays.
    ev: an evaluated or baked subdivided mesh; me: its original (default ob.data)."""
    me = me or ob.data
    skip = broken_faces(me)
    own = ev is None
    if own:
        dg = copies.depsgraph_of(ob)
        oe = ob.evaluated_get(dg)
        ev = oe.to_mesh()
    starts = sub_offsets(me)
    n, m = len(me.polygons), len(ev.polygons)
    assert starts[-1] == m, (int(starts[-1]), m)
    on = np.empty(n * 3); me.polygons.foreach_get("normal", on)
    en = np.empty(m * 3); ev.polygons.foreach_get("normal", en)
    ea = np.empty(m); ev.polygons.foreach_get("area", ea)
    owner = np.repeat(np.arange(n), np.diff(starts))
    dots = (en.reshape(-1, 3) * on.reshape(-1, 3)[owner]).sum(1)
    bad = set(np.unique(owner[(ea > 1e-12) & (dots < 0.0)]).tolist()) - skip
    if own:
        oe.to_mesh_clear()
    return bad


escalate_faces = {}
