"""The real bevel of Edges: Bevel (UPDATES #50) - the outline of a rounded edge, made after the subdivision.

Maintainer 2026-10-14, with a plate seen straight on: "Die Kanten sehen in der Perspektive rund aus, sind aber alle im
Profil weiterhin eckig." - "Ich möchte zwei Varianten. Einmal den Bevel Shader, der es faked und einmal eine echte
Bevelkante mit maximal 3 Facetten." - "Der Bevel darf erst nach der Unterteilung angelegt werden." His target: a cube
of the brick's size with Blender's Bevel modifier, 0.1 mm wide, 3 segments, in profile.

How: no faces are added by a bevel tool. The support edges (edgesupport.py) put a row of points where the rounding of
a chosen edge ends, `width` from it, and with 3 segments a second row at a third of the width. Every point inside that
band is moved onto the profile of its edge: the circle that touches both faces `width` from the edge (what Blender's
Bevel makes with the offset type Offset and profile 0.5), as `segments` straight pieces. A point at the distance d on
one side goes to the place s = (1 - d / width) / 2 along the profile from that side, the edge itself to the middle.
So the width is the same at every edge, and nothing can overlap: points only move, each by a smooth function of where
it lies, never further than the profile from its old place.

Tried before and dropped (runs 274 to 279): Blender's Bevel modifier on the subdivided copy. It makes new faces beside
every edge; where the rows of faces beside an edge are narrower than the width (after the subdivision most of them)
those overlap and turn over, and a smaller width there made the bevels of different size ("Die Fasen sind
unterschiedlich dick. Zu dicke erzeugen Geometrie-Probleme.").

Where several edges meet (the corner of a box) a point lies in several bands: it takes the smallest move that goes as
far as each edge asks along that edge's own direction - no dent in the corner. Pieces of one run of edges ask the same
and count once. A point is only moved when it lies on one of the two faces of the edge (its way from the edge runs
along that face), so a surface that merely passes close by stays. A face that would still turn over is put back with
its points (rb_bevel_back on the copy).

The shading normals are the rounding in the normals (bevel.round_in_normals): the run of the circle's normal across
the band, the same as the profile - the facets shade round, as the shader does.
"""
import math

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import edgesupport

SHAPE_SAME = 30.0           # two moves of a point within this angle come from the same edge (pieces of one run)
SHAPE_ON = 0.6              # a point lies on a face of the edge: its way from the edge runs along it within 53 degrees
SHAPE_FLAT = 1.0            # an edge that bends by less than this (degrees) gets no profile
SHAPE_SHARP = 178.0         # an edge that bends further (a knife edge) is profiled as if it bent this far
SHAPE_TURN = -0.1           # a face whose normal ends up below this cosine to its old one is put back
SHAPE_BACK = 4              # rounds of putting faces back: half the move each time, nothing in the last
SHAPE_MEET = 0.05           # edges meet in a ball corner when their circles' centre lines pass this x width apart
SHAPE_ROW3 = 1.0 - math.tan(math.radians(30.0))   # three segments: the second row of points, x width (90-degree edge)
SHAPE_APART = 60.0          # a point whose faces stand further off their mean keeps its normals
BACK_PLACES = []            # the points the last shape_edges put back (probes)
SHAPE_OFF = 75.0            # plain_where_off: a corner normal further off its face takes the face's
SHAPE_STILL = 0.002            # a point that would move by less than this x width stays
SHAPE_CHOSEN = "rb_edge_chosen"     # edge attribute while the support edges are cut: the chosen edges, also when split


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1), 1e-12)[..., None]


def edge_frames(me, chosen):
    """The chosen edges of `me` with the two faces beside them: (start points, end points, normals, ways) - normals[i,
    side, end] is the normal the face on that side of edge i has at that end, ways[i, side, end] the direction on that
    face away from the edge, square to it; islands[i] the island of edge i (UPDATES #54: a profile moves the points of
    its own island only)."""
    from . import meshparts
    island = meshparts.point_islands(me)
    n = np.zeros(len(me.loops) * 3, np.float32)
    me.corner_normals.foreach_get("vector", n)
    n = n.reshape(-1, 3).astype(np.float64)
    bm = bmesh.new()
    bm.from_mesh(me)
    a, b, nn, tt, isl = [], [], [], [], []
    for e in bm.edges:
        if not chosen[e.index] or len(e.link_faces) != 2:
            continue
        va, vb = e.verts
        along = np.array(vb.co - va.co)
        if np.linalg.norm(along) < 1e-12:
            continue
        isl.append(int(island[va.index]))
        along /= np.linalg.norm(along)
        mid = np.array((va.co + vb.co) / 2)
        rn, rt = [], []
        for f in e.link_faces:
            at = {lp.vert.index: lp.index for lp in f.loops}
            ends = (n[at[va.index]], n[at[vb.index]])
            inward = np.array(f.calc_center_median()) - mid
            ways = []
            for nrm in ends:
                w = np.cross(along, nrm)
                w /= max(np.linalg.norm(w), 1e-12)
                ways.append(w if w @ inward >= 0 else -w)
            rn.append(ends)
            rt.append(ways)
        a.append(tuple(va.co))
        b.append(tuple(vb.co))
        nn.append(rn)
        tt.append(rt)
    bm.free()
    f64 = np.float64
    return (np.array(a, f64).reshape(-1, 3), np.array(b, f64).reshape(-1, 3),
            np.array(nn, f64).reshape(-1, 2, 2, 3), np.array(tt, f64).reshape(-1, 2, 2, 3), np.array(isl, np.int64))


def mark_chosen(me, chosen):
    """Keep the chosen edges of `me` as an edge attribute: the support edges split some of them."""
    at = me.attributes.get(SHAPE_CHOSEN) or me.attributes.new(SHAPE_CHOSEN, 'FLOAT', 'EDGE')
    at.data.foreach_set("value", np.asarray(chosen, np.float32))


def chosen_again(me, drop=False):
    """The chosen edges of `me` after the cuts (per edge); `drop` takes the attribute off the mesh."""
    at = me.attributes.get(SHAPE_CHOSEN)
    out = np.zeros(len(me.edges), np.float32)
    if at is not None:
        at.data.foreach_get("value", out)
        if drop:
            me.attributes.remove(at)
    return out > 0.5


def _arc(c, r, a, b, omega, sigma):
    """Points at the share `sigma` of the arcs around `c` (radius `r`) from the unit directions `a` to `b`."""
    so = np.sin(omega)
    wa, wb = np.sin((1.0 - sigma) * omega) / so, np.sin(sigma * omega) / so
    return c + r[:, None] * (wa[:, None] * a + wb[:, None] * b)


def _combine(moves):
    """The smallest move that goes as far as each of `moves` asks, along its own direction. Moves that point away from
    each other (an edge rounded outwards meets one rounded inwards: a saddle) are added instead - asked to go as far
    as both, the move grew to 0.08 mm at a point of 11477 and folded the faces round it (run 285)."""
    ds = [d for d in moves if d @ d > 1e-24]
    if not ds:
        return np.zeros(3)
    m = np.array(ds)
    if (m @ m.T < 0).any():
        return m.sum(axis=0)
    while True:
        g = m @ m.T
        c = np.linalg.lstsq(g, (m * m).sum(axis=1), rcond=None)[0]
        if (c >= -1e-9).all() or len(m) == 1:
            break
        m = np.delete(m, int(np.argmin(c)), axis=0)
    x = c @ m
    longest = max(math.sqrt(d @ d) for d in ds)
    size = math.sqrt(x @ x)
    return x * min(1.0, 2.0 * longest / max(size, 1e-12))      # never more than twice the furthest single move


def _face_normals(co, lv, ls, lt):
    """Newell normals of all faces (not unit) for the points `co`."""
    nxt = np.arange(len(lv)) + 1
    ends = ls + lt
    nxt[ends - 1] = ls
    p, q = co[lv], co[lv[nxt]]
    cross = np.cross(p, q)
    face = np.repeat(np.arange(len(ls)), lt)
    out = np.zeros((len(ls), 3))
    np.add.at(out, face, cross)
    return out


def _candidates(co, frames, width, island=None):
    """Pairs (point, edge) of the points `co` that lie within reach of a chosen edge: two index arrays. With `island`
    (per point) only the points of the edge's own island (UPDATES #54)."""
    la, lb = frames[0], frames[1]
    tree = KDTree(len(co))
    for i, c in enumerate(co.tolist()):
        tree.insert(c, i)
    tree.balance()
    mid, reach = (la + lb) / 2, np.linalg.norm(lb - la, axis=1) / 2 + width
    vi, li = [], []
    for i, (c, r) in enumerate(zip(mid.tolist(), reach.tolist(), strict=True)):
        found = tree.find_range(Vector(c), r)
        vi.extend(f[1] for f in found)
        li.extend([i] * len(found))
    vi, li = np.array(vi, np.int64), np.array(li, np.int64)
    if island is not None and len(frames) > 4 and len(vi):
        own = island[vi] == frames[4][li]
        vi, li = vi[own], li[own]
    return vi, li


def _profile(c, r, a, b, omega, sigma, segments):
    """Points at the share `sigma` along the profiles: the circles around `c` (radius `r`) from the unit directions `a`
    to `b`, or with `segments` that many straight pieces between points of the circle."""
    if not segments:
        return _arc(c, r, a, b, omega, sigma)
    k = np.minimum(np.floor(sigma * segments), segments - 1)
    f = sigma * segments - k
    p0, p1 = _arc(c, r, a, b, omega, k / segments), _arc(c, r, a, b, omega, (k + 1) / segments)
    return p0 * (1.0 - f)[:, None] + p1 * f[:, None]


def _corner(p, rows, width):
    """The move of the place `p` where several edges meet (`rows`: one dict per edge, see _field): onto the ball that
    rolls along all of them - the sphere around the point nearest to their circles' centre lines, as far out as their
    circles. None where the edges do not meet like that (then the moves are joined by _combine): fewer than three
    faces, centre lines that miss each other, or a place outside the corner (not in the cone of its faces' normals)."""
    normals = []
    for r in rows:
        for n in (r["na"], r["nb"]):
            if all(n @ m < math.cos(math.radians(20.0)) for m in normals):
                normals.append(n)
    if len(normals) < 3:
        return None
    a, b = np.zeros((3, 3)), np.zeros(3)
    for r in rows:
        m = np.eye(3) - np.outer(r["along"], r["along"])
        a += m
        b += m @ r["centre"]
    c = np.linalg.lstsq(a, b, rcond=None)[0]
    for r in rows:
        off = c - r["centre"]
        if np.linalg.norm(off - r["along"] * (off @ r["along"])) > SHAPE_MEET * width:
            return None
    out = p - c
    n = np.array(normals).T
    lam = np.linalg.lstsq(n, out, rcond=None)[0]
    if np.linalg.norm(n @ lam - out) > SHAPE_MEET * max(np.linalg.norm(out), width):
        return None
    if not ((lam >= -1e-9).all() or (lam <= 1e-9).all()):
        return None
    radius = float(np.mean([r["radius"] for r in rows]))
    reach = min(r["facet"] for r in rows)           # the straight pieces: as far in as the edges' own profiles
    return c + out / max(np.linalg.norm(out), 1e-15) * radius * reach - p


def _field(pos, rid, li, frames, width, segments):
    """The moves onto the profile for the places `pos` (one row per pair of a place and an edge near it; `rid` names
    the place of a row, `li` the edge). `segments` 0: the circle itself, else that many straight pieces. Returns
    (the places moved, their moves).
    Where on the circle a place goes: where a ball of the circle's size, rolled along the edge, touches nearest to it
    (the place seen from the circle's centre) - so the circles of edges that meet join the corner's sphere."""
    la, lb, ln, lw = frames[:4]
    ab = lb[li] - la[li]
    t = np.clip(((pos - la[li]) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-18), 0.0, 1.0)
    q = la[li] + ab * t[:, None]
    v = pos - q
    d = np.linalg.norm(v, axis=1)
    wa = _unit(lw[li, 0, 0] * (1.0 - t)[:, None] + lw[li, 0, 1] * t[:, None])
    wb = _unit(lw[li, 1, 0] * (1.0 - t)[:, None] + lw[li, 1, 1] * t[:, None])
    on_a, on_b = (v * wa).sum(axis=1), (v * wb).sum(axis=1)
    side_b = on_b > on_a
    dd = np.maximum(np.where(side_b, on_b, on_a), 0.0)          # the distance from the edge along its face
    bend = np.minimum(math.pi - np.arccos(np.clip((wa * wb).sum(axis=1), -1.0, 1.0)), math.radians(SHAPE_SHARP))
    ok = dd < width
    ok &= (dd >= SHAPE_ON * d) | (d < 1e-6)
    ok &= bend > math.radians(SHAPE_FLAT)
    if not ok.any():
        return np.zeros(0, np.int64), np.zeros((0, 3))
    rid, pos, li, t, q, d, dd, wa, wb, side_b, bend = (x[ok] for x in (rid, pos, li, t, q, d, dd, wa, wb, side_b, bend))
    na = _unit(ln[li, 0, 0] * (1.0 - t)[:, None] + ln[li, 0, 1] * t[:, None])
    nb = _unit(ln[li, 1, 0] * (1.0 - t)[:, None] + ln[li, 1, 1] * t[:, None])
    along = _unit(lb[li] - la[li])
    # the circle that touches both faces `width` from the edge
    half = np.sin(bend / 2.0)
    centre = q + _unit(wa + wb) * (width / half)[:, None]
    radius = width * np.cos(bend / 2.0) / half
    ua = (q + wa * width - centre) / np.maximum(radius, 1e-12)[:, None]
    ub = (q + wb * width - centre) / np.maximum(radius, 1e-12)[:, None]
    from_side = np.arctan2(width - dd, radius) / bend        # 0 at the border of the band, 0.5 on the edge
    sigma = np.where(side_b, 1.0 - from_side, from_side)
    target = _profile(centre, radius, ua, ub, bend, sigma, segments)
    move = target - (q + np.where(side_b[:, None], wb, wa) * dd[:, None])
    # per place: the nearest edge of each direction (pieces of one run ask the same: once)
    feature = _unit(wa + wb)
    # (ties - a place on the point between two edges of a run is as near to both - go by the order of the edges, the
    # same in a batch of islands; the order the search found them in was not, run 287)
    rest = np.lexsort((li, np.round(d, 7), rid))
    same = math.cos(math.radians(SHAPE_SAME))
    picked = []
    for _pass in range(3):
        if not len(rest):
            break
        lead = np.r_[True, rid[rest][1:] != rid[rest][:-1]]
        picked.append(rest[lead])
        of = rest[lead][np.cumsum(lead) - 1]
        rest = rest[(feature[rest] * feature[of]).sum(axis=1) <= same]
    first = picked[0]
    ids, out = rid[first], move[first].copy()
    if len(picked) > 1:
        zero = np.zeros(len(rid))
        facet = np.linalg.norm(_profile(np.zeros((len(rid), 3)), zero + 1.0, ua, ub, bend, sigma, segments), axis=1)
        several = np.unique(rid[np.concatenate(picked[1:])])
        more = {}
        for group in picked:
            for c in group[np.isin(rid[group], several)]:
                more.setdefault(int(rid[c]), []).append(int(c))
        for p, rows in more.items():
            got = _corner(pos[rows[0]], [{"na": na[c], "nb": nb[c], "along": along[c], "centre": centre[c],
                                          "radius": radius[c], "facet": facet[c]} for c in rows], width)
            out[np.searchsorted(ids, p)] = got if got is not None else _combine([move[c] for c in rows])
    return ids, out


def shape_edges(me, frames, width, segments):
    """Move the points of `me` inside the band of every chosen edge (`frames`: edge_frames before the cuts) onto the
    edge's profile, `width` wide, of `segments` straight pieces. Returns (the points moved, points put back, the
    normals of the rounding at the corners of the points moved: loop indices and unit vectors). The normals are those
    of the round surface itself - the circle of each edge, joined where edges meet as the points are (_round_normals).
    Custom normals are left to the caller (they are relative to the
    faces: set them again after this)."""
    none = (np.zeros(0, np.int64), 0, np.zeros(0, np.int64), np.zeros((0, 3)))
    if not len(frames[0]) or width <= 0:
        return none
    segments = max(1, int(segments))
    nv = len(me.vertices)
    co = np.zeros(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    from . import meshparts
    island = meshparts.point_islands(me)
    vi, li = _candidates(co, frames, width, island)
    if not len(vi):
        return none
    ids, mv = _field(co[vi], vi, li, frames, width, segments)
    # a point on the border of the band (a support row at the width) moves by nothing worth the name: it stays, and
    # keeps the face's normal - counted as moved it took the mean of the bevel's faces alone, 15 degrees off (run 285)
    real = np.linalg.norm(mv, axis=1) > SHAPE_STILL * width
    ids, mv = ids[real], mv[real]
    if not len(ids):
        return none
    delta = np.zeros((nv, 3))
    delta[ids] = mv
    moved = np.unique(ids)
    # faces that would turn over are put back with their points
    nf = len(me.polygons)
    lv = np.zeros(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    ls = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_start", ls)
    lt = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    old = _face_normals(co, lv, ls, lt)
    old_len = np.linalg.norm(old, axis=1)
    face = np.repeat(np.arange(nf), lt)
    back = np.zeros(nv, bool)
    for round_ in range(SHAPE_BACK + 1):
        new = _face_normals(co + delta, lv, ls, lt)
        cos = (old * new).sum(axis=1) / np.maximum(old_len * np.linalg.norm(new, axis=1), 1e-30)
        bad = (cos < SHAPE_TURN) & (old_len > 1e-18)
        if not bad.any():
            break
        pts = np.unique(lv[bad[face]])
        pts = pts[np.linalg.norm(delta[pts], axis=1) > 0]
        if not len(pts):
            break
        back[pts] = True
        delta[pts] *= 0.0 if round_ >= SHAPE_BACK - 1 else 0.5
    moved = moved[~back[moved]]
    BACK_PLACES[:] = co[back].tolist()                # for the probes: where points were put back
    loops, normals = _round_normals(co, lv, ls, lt, face, moved, vi, li, frames, width, delta, island)
    me.vertices.foreach_set("co", (co + delta).astype(np.float32).ravel())
    me.update()
    return moved, int(back.sum()), loops, normals


def _round_normals(co, lv, ls, lt, face, moved, vi, li, frames, width, delta, island=None):
    """The normals of the round surface at the corners of the points `moved`: the points are put on the circle itself
    (not on its straight pieces) and each takes the mean of the faces around it, weighted by their angle there - on
    the circle that is the circle's normal, at the corner of a box the middle of the three. A point whose faces
    around it differ by more than SHAPE_APART from that mean (a sharp edge that is not rounded) is left out.
    Faces that reach beyond the net's reach (edgesupport.keep_plain) are left out too, with their corners.
    Tried first: following the two edges of each corner a little way through the move - at the corner of a box the
    move draws a whole patch together and those steps gave the three faces' own normals (run 285)."""
    on = np.zeros(len(co), bool)
    on[moved] = True
    if not on.any():
        return np.zeros(0, np.int64), np.zeros((0, 3))
    ids, mv = _field(co[vi], vi, li, frames, width, 0)
    at = co + delta
    keep = on[ids]
    at[ids[keep]] = co[ids[keep]] + mv[keep]
    nxt = np.arange(len(lv)) + 1
    nxt[(ls + lt) - 1] = ls
    prv = np.arange(len(lv)) - 1
    prv[ls] = ls + lt - 1
    fn = _unit(_face_normals(at, lv, ls, lt))[face]
    e1, e2 = _unit(at[lv[nxt]] - at[lv]), _unit(at[lv[prv]] - at[lv])
    angle = np.arccos(np.clip((e1 * e2).sum(axis=1), -1.0, 1.0))
    loops = np.nonzero(on[lv])[0]
    # a face that reaches further than the net's reach from every rounded edge keeps what the net gave it (plain):
    # its normals would run the rounding across all of it (run 285, 18747: streaks from the top corners)
    vi2, li2 = _candidates(co, frames, edgesupport.EDGE_REACH * width, island)
    la, lb = frames[0], frames[1]
    ab = lb[li2] - la[li2]
    t = np.clip(((co[vi2] - la[li2]) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-18), 0.0, 1.0)
    near = np.full(len(co), np.inf)
    np.minimum.at(near, vi2, np.linalg.norm(co[vi2] - (la[li2] + ab * t[:, None]), axis=1))
    far = near > edgesupport.EDGE_REACH * width
    long_face = np.zeros(len(ls), bool)
    np.logical_or.at(long_face, face, far[lv])
    loops = loops[~long_face[face[loops]]]
    mean = np.zeros((len(co), 3))
    np.add.at(mean, lv[loops], fn[loops] * angle[loops, None])
    mean = _unit(mean)
    off = (fn[loops] * mean[lv[loops]]).sum(axis=1) < math.cos(math.radians(SHAPE_APART))
    bad = np.zeros(len(co), bool)
    bad[lv[loops[off]]] = True
    loops = loops[~bad[lv[loops]]]
    return loops, mean[lv[loops]]


def plain_where_off(normals, me):
    """Corners of `me` whose normal stands more than SHAPE_OFF degrees off their face take the face's own normal: a
    face that a move tipped (a detail smaller than the bevel, a point put back beside moved ones) would show a dark
    fleck with the normal of the rounding. `normals`: corner normals (n x 3), changed in place. Returns the count."""
    nf = len(me.polygons)
    lt = np.zeros(nf, np.int32)
    me.polygons.foreach_get("loop_total", lt)
    area = np.zeros(nf, np.float32)
    me.polygons.foreach_get("area", area)
    fn = np.zeros(nf * 3, np.float32)
    me.polygons.foreach_get("normal", fn)
    fn = np.repeat(fn.reshape(-1, 3), lt, axis=0)
    off = ((normals * fn).sum(axis=1) < math.cos(math.radians(SHAPE_OFF))) & np.repeat(area > 1e-12, lt)
    normals[off] = fn[off]
    return int(off.sum())
