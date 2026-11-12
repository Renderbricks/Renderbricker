"""W21 - the round outline of a flat face, and the copy's points on it (rules 3.16, UPDATES #67; designed in run 303,
fitlib.close_round_outlines, prototype 9 of run 302).

    close_round   a flat face of the part whose outline is one loop on a circle - every outline edge has two faces,
                  8 points or more, all within 3 % of one distance from their middle - and hard (crease >= HARD) on
                  half of its edges or more but not on all: the whole outline gets crease 1.0 and the edge mark
                  CLOSED (23443: the round end was hard on one half and slid off its circle on the other)
    stay_points   the copy's points on the CLOSED edges - the cage's points of those edges and the 2^level - 1 points
                  the subdivision puts on each - do not slide (W14c): a point slid along the surface left the closed
                  outline (run 303, finding 2: the small spot); only these, holding every chain point made dark dashes
                  (89678's hole rim)

NO_CLOSE[0] names import faces (rb_fi) whose flat faces get no W21: the islands whose copy folded with it
(welding._bake_weld, as W18's NO_ENDS).
"""
import numpy as np

from . import cagegeom

CLOSED = "rb_closed"        # FLOAT, EDGE: 1.0 on the edges of an outline W21 closed
NO_CLOSE = [None]           # import faces (rb_fi) whose flat faces are left out
MIN_POINTS = 8              # an outline of fewer points is no circle
ROUND_TOL = 0.03            # every point within this share of the mean distance from the middle
HARD_SHARE = 0.5            # hard on this share of the outline or more (but not on all of it)


def close_round(wm):
    """Close the round outlines of the flat faces of the cage `wm`: crease_edge 1.0 and CLOSED on their edges.
    Returns the number of outlines closed."""
    if not len(wm.polygons) or wm.attributes.get("crease_edge") is None:
        return 0
    T = cagegeom.arrays(wm)
    roots, flat = cagegeom.flat_faces(T)
    cr, co, ev, nf = T["cr"], T["co"], T["ev"], T["nf"]
    off = NO_CLOSE[0]
    left_out = np.zeros(nf, bool)
    if off:
        own = np.arange(nf, dtype=np.int32)
        at = wm.attributes.get("rb_fi")
        if at is not None:
            at.data.foreach_get("value", own)
        skip = np.isin(own, np.fromiter(off, np.int64, len(off)))
        np.logical_or.at(left_out, roots, skip)             # a flat face of the part is left out with any of its faces
    # outline edges of every flat face of the part: an edge with two faces of two different groups is on the outline
    # of both (an edge with one face, or more than two, is not counted - the outline must be closed)
    e, f, g = cagegeom._face_pairs(T)
    apart = roots[f] != roots[g]
    e, f, g = e[apart], f[apart], g[apart]
    grp = np.concatenate((roots[f], roots[g]))
    edg = np.concatenate((e, e))
    want = np.zeros(nf, bool)
    want[roots[flat]] = True
    want &= ~left_out
    pick = want[grp]
    grp, edg = grp[pick], edg[pick]
    order = np.argsort(grp, kind="stable")
    grp, edg = grp[order], edg[order]
    cuts = np.nonzero(np.diff(grp))[0] + 1
    hard = cr >= cagegeom.HARD
    done = []
    for border in np.split(edg, cuts) if len(edg) else ():
        border = np.unique(border)
        vs = np.unique(ev[border])
        if len(vs) < MIN_POINTS or len(border) != len(vs):
            continue
        dist = np.linalg.norm(co[vs] - co[vs].mean(axis=0), axis=1)
        if np.abs(dist - dist.mean()).max() > ROUND_TOL * dist.mean():
            continue
        h = hard[border]
        if h.mean() < HARD_SHARE or h.all():
            continue
        done.append(border)
    if not done:
        return 0
    closed = np.concatenate(done)
    cr[closed] = 1.0
    wm.attributes["crease_edge"].data.foreach_set("value", cr)
    mark = np.zeros(len(cr), np.float32)
    mark[closed] = 1.0
    at = wm.attributes.get(CLOSED) or wm.attributes.new(CLOSED, 'FLOAT', 'EDGE')
    at.data.foreach_set("value", mark)
    wm.update()
    return len(done)


def stay_points(cage, level, n_copy):
    """Per point of the copy of `cage` at `level` (n_copy points): whether it lies on a CLOSED edge of the cage - the
    edge's two cage points and the 2^level - 1 points on it. The subdivision numbers the cage's points first, then the
    points on its edges, edge by edge (Blender, subdiv_foreach.cc 208-211). None without CLOSED edges or with another layout."""
    at = cage.attributes.get(CLOSED)
    if at is None or not level:
        return None
    ne, nv = len(cage.edges), len(cage.vertices)
    mark = np.zeros(ne, np.float32)
    at.data.foreach_get("value", mark)
    e = np.nonzero(mark > 0.5)[0]
    per = 2 ** level - 1
    if not len(e) or n_copy < nv + ne * per:
        return None
    ev = np.zeros(ne * 2, np.int64)
    cage.edges.foreach_get("vertices", ev)
    stay = np.zeros(n_copy, bool)
    stay[ev.reshape(-1, 2)[e].ravel()] = True
    stay[nv + (e[:, None] * per + np.arange(per)[None, :]).ravel()] = True
    return stay
