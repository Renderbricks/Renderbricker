"""W2b „an arc's last step“ (rules 3.15, run 295, UPDATES #56 / #60): a small flat facet that only continues a
polygonised arc is no edge. On the crab 31577 / 33121 Mecabricks put a flat facet of two faces inside each claw tip,
12.4 deg to the C's inner arc; W2 creased its seams from 10 deg and left a framed flat strip (maintainer, review video
27.10.2026: „hier bleibt der Kante scharf, die müsste aber eigentlich hier rund gemacht werden“).

A seam between a small flat island (<= FACET_FACES faces) and a curved island stays soft when
  - the curved island is a coarse arc there: walking across it from the seam (over the edges that run along the last
    one, within PARALLEL deg) at least ARC_STEPS steps in a row bend STEP_MIN or more the way the seam does, all about
    equal (within ARC_EVEN of each other: a polygonised circle),
  - the seam bends less than ARC_MAX and no more than STEP_TOL times those steps,
  - every seam between the facet and the arc qualifies (else none is softened: 26559 kept a hard patch), and
  - the facet is the arc's last step: its seams to other islands all bend ARC_END or more.
A softened seam gets no sharp_edge (as a hole ring, W5b); at its points the corners of the faces beside it take the
mean of their imported normals (as W18 along a released seam). In the whole Mecabricks library (4,776 parts) this
changes 31577, 33121 and the arch 7302 - narrowed four times by the pictures (run 295, docs/RULES.md W2b).

Called by welding.weld: soften (end of stage 4), seam_points (end of stage 9), average_normals (on the work mesh)."""
import math
from collections import Counter

import numpy as np

FACET_FACES = 4
STEP_TOL = 1.25
PARALLEL = 30.0
ARC_MAX = 30.0       # a coarse arc: the seam and the arc's step both bend less than this (SHARP_TURN)
STEP_MIN = 5.0       # an arc's step bends at least this ...
ARC_STEPS = 3        # ... and the arc has at least this many of them in a row beside the seam
WALK = 8
ARC_EVEN = 1.2       # a polygonised circle: its steps differ by no more than this ratio
ARC_END = 30.0       # the facet is the arc's last step: its other seams are edges of at least this bend


def _bend(e):
    return math.degrees(e.link_faces[0].normal.angle(e.link_faces[1].normal, 0.0))


def arc_steps(isl, e, cu):
    """The arc beside the seam e: walking across the curved island cu from e, face by face over the edge that runs
    along the last one (within PARALLEL deg) - the bends of those edges while they bend the way e does (both convex
    or both concave) and by at least STEP_MIN; stops at the island's end, at a straight or a reversed step, after
    WALK steps."""
    out = []
    for f in e.link_faces:
        if f[isl] != cu:
            continue
        last, face = e, f
        for _ in range(WALK):
            along = (last.verts[1].co - last.verts[0].co).normalized()
            nxt = None
            for x in face.edges:
                if x is last or len(x.link_faces) != 2 or any(g[isl] != cu for g in x.link_faces):
                    continue
                xd = (x.verts[1].co - x.verts[0].co).normalized()
                if math.degrees(math.acos(min(1.0, abs(xd.dot(along))))) <= PARALLEL:
                    nxt = x
                    break
            if nxt is None:
                break
            bend = _bend(nxt)
            if bend < STEP_MIN or nxt.is_convex != e.is_convex:
                break
            out.append(bend)
            last, face = nxt, (nxt.link_faces[1] if nxt.link_faces[0] is face else nxt.link_faces[0])
    return out


def soften(w):
    """End of stage 4. Reads bm, isl, kind_of, cand. Takes the seams of an arc's last step out of cand (they are not
    creased) and adds arc_soft (those edges)."""
    isl, kind_of = w.isl, w.kind_of
    size = Counter(f[isl] for f in w.bm.faces)
    ends = {}            # (facet, arc) -> the facet's seams to other islands all bend ARC_END or more

    def ends_in_edges(fl, cu):
        if (fl, cu) not in ends:
            bends = [_bend(x) for f in w.bm.faces if f[isl] == fl for x in f.edges
                     if len(x.link_faces) == 2 and {g[isl] for g in x.link_faces} not in ({fl}, {fl, cu})]
            ends[(fl, cu)] = all(b >= ARC_END for b in bends)
        return ends[(fl, cu)]

    pairs = {}           # (facet, arc) -> [(seam, bend, its arc steps)]
    for e, d, a, b in w.cand:
        if {kind_of[a], kind_of[b]} != {"curved", "flat"}:
            continue
        fl, cu = (a, b) if kind_of[a] == "flat" else (b, a)
        if size[fl] <= FACET_FACES:
            pairs.setdefault((fl, cu), []).append((e, d, arc_steps(isl, e, cu)))
    soft = set()
    for (fl, cu), seams in pairs.items():
        if not ends_in_edges(fl, cu) or not all(
                len(st) >= ARC_STEPS and max(st) < ARC_MAX and max(st) <= ARC_EVEN * min(st)
                and d < ARC_MAX and d <= STEP_TOL * max(st) for _e, d, st in seams):
            continue
        soft.update(e for e, _d, _st in seams)
    w.cand = [c for c in w.cand if c[0] not in soft]
    w.arc_soft = soft


def seam_points(w):
    """End of stage 9 (the vertex and face numbers of the work mesh): [(point, faces beside the softened seams at
    it)]."""
    soft = w.arc_soft
    if not soft:
        return []
    w.bm.verts.index_update()
    w.bm.faces.index_update()
    return [(v.index, {f.index for e in soft if v in e.verts for f in e.link_faces})
            for v in {v for e in soft if e.is_valid for v in e.verts}]


def average_normals(wm, pts):
    """The normals across a softened seam: at its points the corners of the faces beside it take their mean, the
    import's normals everywhere else (as W18 along a released seam)."""
    if not pts or not wm.has_custom_normals:
        return
    n = np.empty(len(wm.loops) * 3)
    wm.corner_normals.foreach_get("vector", n)
    n = n.reshape(-1, 3)
    corners = {}
    for poly in wm.polygons:
        for li in poly.loop_indices:
            corners.setdefault((wm.loops[li].vertex_index, poly.index), li)
    for vi, faces in pts:
        lis = [corners[(vi, fi)] for fi in faces if (vi, fi) in corners]
        if len(lis) > 1:
            m = n[lis].mean(axis=0)
            n[lis] = m / max(np.linalg.norm(m), 1e-12)
    wm.normals_split_custom_set(n)
