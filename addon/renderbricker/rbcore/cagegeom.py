"""The welded cage as arrays, its flat faces and the classes of its points - what the shrink compensation of rules 3.16
reads before it moves a point (UPDATES #67 / #61; designed in run 303, fitlib.arrays / flat_patches / classify).

    arrays      the cage's points, faces, corners and edges as numpy arrays, with its creases and its shading
                normals per corner
    flat_faces  which faces are flat: shaded flat by the modeller - every corner normal within FLAT_NORMAL_DEG of the
                face's own normal (a mesh without custom normals: its flat-shaded faces are flat, its smooth ones are
                not); with the faces joined across edges bending less than FLAT_DEG into one flat face
    classes     per point: held, a point of a surface or a point of a hard chain; the directions its residual counts
                in (across the surface or square to the chain - a slide along them is no shrink), and the directions
                it may move in - those, without the normals of the flat faces it lies on (maintainer 2026-10-14: a
                flat part must not get thicker)

Read only: nothing here changes the mesh.
"""
import math

import numpy as np

HARD = 0.99                 # an edge creased this much (or open, or with more than two faces) is hard
FLAT_NORMAL_DEG = 2.0       # a face whose shading normals all lie this close to its own normal is meant flat
FLAT_DEG = 1.0              # faces joined across edges bending less than this are one flat face; two flat planes at
                            # a point closer than this count once
KEEP = 0.5                  # a move direction that loses more than this share to the flat normals is dropped
ROUNDING_RATIO = 2.0        # the pieces of a round shape are about the same length: within this ratio (W17 in welding,
                            # W22's guard in shrink)


def arrays(wm):
    """The cage `wm` as arrays: n points, nf faces, co (n,3), fn (nf,3) face normals, per corner lv point, le edge,
    lf face, cn (corners,3) shading normal; per face ls first corner, lt corners; ev (ne,2) edge points, cr edge
    creases, vcr point creases, efaces faces per edge."""
    n, nf, ne, nl = len(wm.vertices), len(wm.polygons), len(wm.edges), len(wm.loops)
    co = np.zeros(n * 3); wm.vertices.foreach_get("co", co)
    fn = np.zeros(nf * 3); wm.polygons.foreach_get("normal", fn)
    lv = np.zeros(nl, np.int64); wm.loops.foreach_get("vertex_index", lv)
    le = np.zeros(nl, np.int64); wm.loops.foreach_get("edge_index", le)
    ls = np.zeros(nf, np.int64); wm.polygons.foreach_get("loop_start", ls)
    lt = np.zeros(nf, np.int64); wm.polygons.foreach_get("loop_total", lt)
    ev = np.zeros(ne * 2, np.int64); wm.edges.foreach_get("vertices", ev)
    cn = np.zeros(nl * 3); wm.corner_normals.foreach_get("vector", cn)
    cr = np.zeros(ne, np.float32)
    at = wm.attributes.get("crease_edge")
    if at is not None:
        at.data.foreach_get("value", cr)
    vcr = np.zeros(n, np.float32)
    at = wm.attributes.get("crease_vert")
    if at is not None:
        at.data.foreach_get("value", vcr)
    return {"n": n, "nf": nf, "co": co.reshape(-1, 3), "fn": fn.reshape(-1, 3), "lv": lv, "le": le, "ls": ls, "lt": lt,
            "ev": ev.reshape(-1, 2), "cr": cr, "vcr": vcr, "lf": np.repeat(np.arange(nf), lt),
            "efaces": np.bincount(le, minlength=ne), "cn": cn.reshape(-1, 3)}


def _face_pairs(T):
    """The two faces of every edge with exactly two faces: (edges, faces f, faces g)."""
    le, lf = T["le"], T["lf"]
    order = np.argsort(le, kind="stable")
    e_sorted, f_sorted = le[order], lf[order]
    same = np.nonzero(e_sorted[1:] == e_sorted[:-1])[0]
    same = same[T["efaces"][e_sorted[same]] == 2]
    return e_sorted[same], f_sorted[same], f_sorted[same + 1]


def _components(count, f, g):
    """Label of every item 0..count-1: the smallest item it is joined to through the pairs (f, g)."""
    lab = np.arange(count)
    if len(f) == 0:
        return lab
    while True:
        m = np.minimum(lab[f], lab[g])
        new = lab.copy()
        np.minimum.at(new, f, m)
        np.minimum.at(new, g, m)
        new = new[new]                  # a label is an item of the same group with a label not larger: jump
        if np.array_equal(new, lab):
            return lab
        lab = new


def flat_faces(T):
    """(root of every face - the flat face it belongs to, faces joined across edges bending less than FLAT_DEG -, and
    whether the face is flat: every shading normal of its corners within FLAT_NORMAL_DEG of its own normal)."""
    nf, fn, lf = T["nf"], T["fn"], T["lf"]
    _e, f, g = _face_pairs(T)
    join = (fn[f] * fn[g]).sum(axis=1) > math.cos(math.radians(FLAT_DEG))
    roots = _components(nf, f[join], g[join])
    dot = (T["cn"] * fn[lf]).sum(axis=1)
    worst = np.full(nf, 1.0)
    np.minimum.at(worst, lf, dot)
    return roots, worst >= math.cos(math.radians(FLAT_NORMAL_DEG))


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1), 1e-12)[..., None]


def _point_normals(T):
    """Normal of every point: the normals of its faces weighted by the corner angles."""
    n, co, fn, lv, lf, ls, lt = T["n"], T["co"], T["fn"], T["lv"], T["lf"], T["ls"], T["lt"]
    nxt = np.arange(len(lv)) + 1
    last = ls + lt - 1
    nxt[last] = ls
    prv = np.arange(len(lv)) - 1
    prv[ls] = last
    a = _unit(co[lv[nxt]] - co[lv])
    b = _unit(co[lv[prv]] - co[lv])
    ang = np.arccos(np.clip((a * b).sum(axis=1), -1.0, 1.0))
    vn = np.zeros((n, 3))
    np.add.at(vn, lv, fn[lf] * ang[:, None])
    return _unit(vn)


def _flat_planes(T, flat):
    """Per point the planes of the flat faces it lies on, the same plane (within FLAT_DEG) once, in corner order:
    (number of planes, at most 3; the first two planes (n,2,3))."""
    n, fn, lv, lf = T["n"], T["fn"], T["lv"], T["lf"]
    cos_flat = math.cos(math.radians(FLAT_DEG))
    order = np.argsort(lv, kind="stable")
    order = order[flat[lf[order]]]                       # the corners of flat faces, by point, in corner order
    pv = lv[order]
    pn = fn[lf[order]]
    first = np.searchsorted(pv, pv, side="left")
    rank = np.arange(len(pv)) - first
    planes = np.zeros((n, 3, 3))
    count = np.zeros(n, np.int64)
    for r in range(int(rank.max()) + 1 if len(rank) else 0):
        pick = np.nonzero(rank == r)[0]
        v, c = pv[pick], pn[pick]
        v_ok = count[v] < 3
        v, c = v[v_ok], c[v_ok]
        if not len(v):
            continue
        dots = np.abs(np.einsum("kj,kpj->kp", c, planes[v]))     # against every plane slot
        slot = np.arange(3)[None, :] < count[v][:, None]
        ok = ~((dots >= cos_flat) & slot).any(axis=1)
        v, c = v[ok], c[ok]
        planes[v, count[v]] = c
        count[v] += 1
    return count, planes[:, :2]


def classes(T, free, flat):
    """Per cage point: kind (0 held, 1 surface, 2 chain), nd (n,2,3) the directions its residual counts in (a surface
    point: its normal; a chain point: the two directions square to the chain), ku the number of directions it may move
    in and u (n,2,3) those directions (nd without the normals of the flat faces it lies on), vn the point normals,
    nb (n,2) its neighbours along hard edges (-1 where it has fewer; chain points have two), short its shortest edge,
    hard (ne) the hard edges. Held: a point without faces, a point left free (W17), a creased point, a point where more
    than two hard edges meet. For the points left free also, from the same call (W22a takes them as coarse corners):
    free (n) bool, ku_free (n) the number of directions a free point would move in as a chain point (0 for every
    other point) and u_free (n,2,3) those directions. planes: _flat_planes of the call (W24b, W24e read them)."""
    n, co, ev, cr = T["n"], T["co"], T["ev"], T["cr"]
    hard = (cr >= HARD) | (T["efaces"] != 2)
    # neighbours along hard edges, in edge order
    he = ev[hard]
    a_end = he.ravel()
    b_end = he[:, ::-1].ravel()
    order = np.argsort(a_end, kind="stable")
    a_end, b_end = a_end[order], b_end[order]
    nh = np.bincount(a_end, minlength=n)
    start = np.concatenate(([0], np.cumsum(nh)[:-1]))
    nb = np.full((n, 2), -1, np.int64)
    one = np.nonzero((nh >= 1) & (nh <= 2))[0]
    nb[one, 0] = b_end[start[one]]
    two = np.nonzero(nh == 2)[0]
    nb[two, 1] = b_end[start[two] + 1]

    vn = _point_normals(T)
    has_face = np.bincount(T["lv"], minlength=n) > 0
    held = ~has_face | (T["vcr"] >= HARD) | (nh > 2)
    is_free = np.zeros(n, bool)
    free = np.asarray(list(free), np.int64)
    if len(free):
        is_free[free] = True
    # the classes as if no point were free; every row below is computed per point, so the free points' rows are
    # what they would be as chain points, and every other row is the same as with the free points held
    kind = np.where(held, 0, np.where(nh == 2, 2, 1)).astype(np.int8)

    nd = np.zeros((n, 2, 3))
    surf = kind == 1
    nd[surf, 0] = vn[surf]
    ch = np.nonzero(kind == 2)[0]
    if len(ch):
        t = _unit(co[nb[ch, 1]] - co[nb[ch, 0]])
        v = vn[ch]
        ref = v - t * (v * t).sum(axis=1)[:, None]
        thin = np.linalg.norm(ref, axis=1) < 1e-6
        if thin.any():
            axis = np.where((np.abs(t[thin, 0]) < 0.9)[:, None], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
            ref[thin] = np.cross(t[thin], axis)
        ref = _unit(ref)
        nd[ch, 0] = ref
        nd[ch, 1] = np.cross(t, ref)
    km = np.where(kind == 2, 2, np.where(kind == 1, 1, 0))

    # the move directions: nd without the flat faces' normals
    u = nd.copy()
    ku = km.copy()
    count, planes = _flat_planes(T, flat)
    p = np.nonzero((count > 0) & (km > 0))[0]
    if len(p):
        q1 = planes[p, 0]
        q2 = planes[p, 1] - q1 * (planes[p, 1] * q1).sum(axis=1)[:, None]
        q2 = np.where((count[p] >= 2)[:, None], _unit(q2), 0.0)
        U = nd[p]                                                   # (k,2,3), directions as rows
        U = U - (U @ q1[:, :, None]) * q1[:, None, :] - (U @ q2[:, :, None]) * q2[:, None, :]
        U[count[p] >= 3] = 0.0                                     # three planes leave no direction
        U[km[p] == 1, 1] = 0.0
        uu, ss, _vt = np.linalg.svd(np.transpose(U, (0, 2, 1)), full_matrices=False)    # (k,3,2), (k,2)
        keep = ss > KEEP
        u[p] = np.transpose(uu, (0, 2, 1)) * keep[:, :, None]
        ku[p] = keep.sum(axis=1)

    elen = np.linalg.norm(co[ev[:, 1]] - co[ev[:, 0]], axis=1)
    short = np.full(n, np.inf)
    np.minimum.at(short, ev[:, 0], elen)
    np.minimum.at(short, ev[:, 1], elen)
    short[~np.isfinite(short)] = 0.0
    # the free points: held (kind 0, no directions), their chain directions kept apart
    ku_free = np.where(is_free & (kind == 2), ku, 0).astype(np.int8)
    u_free = np.where((ku_free > 0)[:, None, None], u, 0.0)
    if is_free.any():
        kind[is_free] = 0
        nd[is_free] = 0.0
        u[is_free] = 0.0
        ku[is_free] = 0
    return {"kind": kind, "ku": ku.astype(np.int8), "u": u, "nd": nd, "vn": vn, "nb": nb, "short": short,
            "hard": hard, "free": is_free, "ku_free": ku_free, "u_free": u_free, "planes": (count, planes)}
