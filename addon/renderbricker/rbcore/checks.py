"""Checks of a result: self-intersecting and broken faces of the import, folded (flipped) sub-faces."""
import numpy as np
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d
from . import config, workscene


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


LAYOUT = "rb_layout"     # on a copy: how the faces of its cage differ from the import's (layout_of)


def layout_of(orig, cage):
    """What a copy baked from `cage` carries as LAYOUT - empty for nearly every part. Rule W18 gives the welded cage
    a point on an edge and cuts a face in two; then the children of the import's faces no longer come in blocks of
    (corners of the import's face) x 4^(level - 1). A flat list: the number k of faces of the import whose cage
    face has other corners, k pairs (face, corners), then a pair (face of the import, corners) for every face the
    cage has beyond the import's - those stand at the end of the cage and belong to the face they were cut from."""
    a = np.empty(len(orig.polygons), np.int64); orig.polygons.foreach_get("loop_total", a)
    b = np.empty(len(cage.polygons), np.int64); cage.polygons.foreach_get("loop_total", b)
    n = len(a)
    if len(b) < n:
        return []
    f = np.nonzero(a != b[:n])[0]
    if not len(f) and len(b) == n:
        return []
    own = np.arange(len(b), dtype=np.int32)
    at = cage.attributes.get("rb_fi")                   # the import's face of every cage face (welding, stage 3)
    if at is not None:
        at.data.foreach_get("value", own)
    return [len(f)] + np.column_stack([f, b[f]]).ravel().tolist() + np.column_stack([own[n:], b[n:]]).ravel().tolist()


def cage_faces(me, ev=None):
    """The faces of the cage that `ev` (a copy of `me`) was subdivided from: (corners per cage face, the face of
    `me` each cage face belongs to) - the faces of `me` itself, with what the copy says about its cage (LAYOUT).
    A cage face has as many children as corners at level 1, four times more per level, in the order of the cage."""
    sizes = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", sizes)
    owner = np.arange(len(sizes))
    lay = list(ev.get(LAYOUT) or []) if ev is not None else []
    if lay:
        k = int(lay[0])
        pairs = np.array(lay[1:], np.int64).reshape(-1, 2)
        sizes[pairs[:k, 0]] = pairs[:k, 1]
        sizes, owner = np.concatenate([sizes, pairs[k:, 1]]), np.concatenate([owner, pairs[k:, 0]])
    return sizes, owner


def sub_offsets(me, ev=None):
    """Start index of each cage face's children in the evaluated mesh `ev` (level LEVELS)."""
    return np.concatenate(([0], np.cumsum(cage_faces(me, ev)[0] * 4 ** (config.LEVELS - 1))))


def flipped_faces(ob, ev=None, me=None):
    """Original face indices whose subdivided children flip (> 90 deg).
    Vectorised (run 30): the same test as the old face-by-face loop, on arrays.
    ev: an evaluated or baked subdivided mesh; me: its original (default ob.data)."""
    me = me or ob.data
    skip = broken_faces(me)
    own = ev is None
    if own:
        dg = workscene.depsgraph_of(ob)
        oe = ob.evaluated_get(dg)
        ev = oe.to_mesh()
    sizes, own_face = cage_faces(me, ev)
    starts = np.concatenate(([0], np.cumsum(sizes * 4 ** (config.LEVELS - 1))))
    n, m = len(me.polygons), len(ev.polygons)
    assert starts[-1] == m, (int(starts[-1]), m)
    on = np.empty(n * 3); me.polygons.foreach_get("normal", on)
    en = np.empty(m * 3); ev.polygons.foreach_get("normal", en)
    ea = np.empty(m); ev.polygons.foreach_get("area", ea)
    owner = np.repeat(own_face, np.diff(starts))
    dots = (en.reshape(-1, 3) * on.reshape(-1, 3)[owner]).sum(1)
    bad = set(np.unique(owner[(ea > 1e-12) & (dots < 0.0)]).tolist()) - skip
    if own:
        oe.to_mesh_clear()
    return bad


escalate_faces = {}
