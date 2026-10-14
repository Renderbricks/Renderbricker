"""Textures at their import place: the reparametrised copy (W14c, rules 3.6, runs 212-221).

Catmull-Clark smoothing does two things at once: it rounds the part (wanted) and it slides the points along the
surface (unwanted for textures). A face ring is pulled towards its larger neighbours, so everything a texture draws on
it moves with it - 7052's mould line sits on a ring only a fraction of a millimetre wide, the smoothing moved it by
more than its width (line lower, corner reshaped). Changing the UVs cannot fix that: at the line's import place there
are now faces of another UV island (runs 216-221).

So the copy keeps the linear UVs of the subdivision (a child face carries the texture of its original face) and its
points slide back along the smooth surface to where they belong: every vertex goes to the point of the smooth surface
nearest to its *parametric* point on the import - the point on its import face that its linear UVs point to (carried
through the subdivision as a corner attribute, mark / param_positions). The shape stays (points only slide on the surface), the faces sit where their import
faces were, so every texture - mould lines, grain, prints, logos - lies at its import place.

Kept in place: boundary vertices (seams between shells must keep coinciding) and vertices whose nearest point lies
across a sharp edge (face normal turned by more than SHARP_DEG). Normals per corner: the smooth copy's corner normals
at the new point, from the same side of a sharp edge.

Measures (run 221): 7052 L2/L3 line and corner like the import in Cycles and EEVEE, the EEVEE dent of 1.2.4 gone;
3044 grain, head 3626, torso 3814, curved slope 93273 like the import."""
import bpy
import numpy as np
from mathutils.bvhtree import BVHTree
from . import checks, config

SHARP_DEG = 30.0      # a nearest point on a face turned further than this lies across a sharp edge: stay
MIN_SLIDE = float(config.opt("--reparam-min", "2e-3"))   # relative to the part size: smaller slides stay - about one texel of the part's own texture
                      # (1024 px over the part; run 222: 1e-3 queried 1.7x, 1e-5 12x as many points)


def _arr(coll, attr, n, width, dtype=np.float64):
    a = np.empty(n * width, dtype); coll.foreach_get(attr, a)
    return a.reshape(-1, width) if width > 1 else a


def _bary(P, A, B, C):
    v0, v1, v2 = B - A, C - A, P - A
    d00 = (v0 * v0).sum(1); d01 = (v0 * v1).sum(1); d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1); d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    v = (d11 * d20 - d01 * d21) / den; w = (d00 * d21 - d01 * d20) / den
    W = np.clip(np.stack([1 - v - w, v, w], 1), 0.0, 1.0)
    return W / np.maximum(W.sum(1), 1e-12)[:, None]


PARAM = "rb_param"    # corner attribute: the import position of each corner's vertex
PROJECT_ITER = 2      # fixed-point steps of the normal-field projection (0: nearest point)
JUMP = 1.5            # a slide may be at most this times the distance to the parametric point
FOLD_STEPS = 4        # halvings of the slide of a vertex whose quad would turn (then it stays)
FOLD_COS = 0.2        # a slid quad turned more than 78 deg against the surface under it counts as folding
PHONG = float(config.opt("--reparam-phong", "0"))   # Phong lift of slid points - off: spikes at sharp edges (run 224)
CURVE_DEG = float(config.opt("--reparam-curve", "8"))   # no slide onto a facet whose vertex normals spread more (run 224)
FREE_NORMALS = False  # see slide: compact fan-space normals by default
SHELL = "rb_shell"    # point attribute: the connected shell of each vertex (a stud on a plate is its own shell)
SIZE_PIN = [None]     # the part size of the whole mesh while it is converted in batches (batches.py, UPDATES #54)
TIE = 1e-5           # mm: nearest points this close count as the same distance (canonical, run 287)
TIE_COS = 1e-4       # facing and flatness of tied triangles this close count as equal (canonical, run 287)
EDGE = "rb_rim"       # point attribute: 1 on the import's boundary vertices (open rims, seams between shells)


def part_size(me):
    """The largest side of the bounding box of `me` - the scale of MIN_SLIDE."""
    co = _arr(me.vertices, "co", len(me.vertices), 3)
    return float(np.ptp(co, 0).max()) or 1.0


def mark(work):
    """Give the work mesh its import positions as a corner attribute. The subdivision interpolates it like the linear
    UVs (uv_smooth NONE), so in the copy it holds each vertex's parametric point - exactly where the vertex's linear UVs
    point to on the import. Run 222: the same as a Simple subdivision except inside triangles and n-gons, where it
    follows the UVs and Simple does not; and it needs no second subdivision pass (that cost +45 % on Banana Mech)."""
    me = work.data
    if me.attributes.get(PARAM) is not None:
        return
    lv = _arr(me.loops, "vertex_index", len(me.loops), 1, np.int64)
    co = _arr(me.vertices, "co", len(me.vertices), 3)
    me.attributes.new(PARAM, 'FLOAT_VECTOR', 'CORNER').data.foreach_set("vector", co[lv].ravel())
    # boundary vertices, once per import instead of per copy (run 222): the subdivision keeps 1 along boundary edges
    lt = _arr(me.polygons, "loop_total", len(me.polygons), 1, np.int64)
    ls = np.cumsum(lt) - lt
    nxt = np.arange(len(lv)) + 1; nxt[ls + lt - 1] = ls
    a_, b_ = lv, lv[nxt]; n = len(me.vertices)
    lone = ~np.isin(a_ * n + b_, b_ * n + a_)
    rim = np.zeros(n, np.float32); rim[a_[lone]] = 1.0; rim[b_[lone]] = 1.0
    me.attributes.new(EDGE, 'FLOAT', 'POINT').data.foreach_set("value", rim)
    # connected shells (run 224: a point of a stud's fillet slid onto the plate surface 0.01 mm below - another shell)
    ev = _arr(me.edges, "vertices", len(me.edges), 2, np.int64)
    lab = np.arange(n)
    while len(ev):
        m = np.minimum(lab[ev[:, 0]], lab[ev[:, 1]])
        new = lab.copy(); np.minimum.at(new, ev[:, 0], m); np.minimum.at(new, ev[:, 1], m)
        new = new[new]
        if np.array_equal(new, lab):
            break
        lab = new
    me.attributes.new(SHELL, 'FLOAT', 'POINT').data.foreach_set("value", lab.astype(np.float32))


def param_positions(cp):
    """The parametric points of the copy's vertices (from mark) and the copy's corner -> vertex map; the attribute is
    removed from the copy. None if the copy has no marks."""
    a = cp.attributes.get(PARAM)
    if a is None:
        return None
    v = _arr(a.data, "vector", len(cp.loops), 3)
    lv = _arr(cp.loops, "vertex_index", len(cp.loops), 1, np.int64)
    P = np.empty((len(cp.vertices), 3)); P[lv] = v
    cp.attributes.remove(cp.attributes[PARAM])
    return P, lv



_ISLANDS = {}         # (mesh name, layer, faces) -> UV island per face of the import, shared by the levels


def uv_islands(me, layer):
    """UV island per face of `me` (faces joined across an edge whose corners carry the same UVs on both sides) -
    vectorised: matching corner edges by sorting, labels by repeated minimum propagation."""
    key = (me.name, layer, len(me.polygons))
    if key in _ISLANDS:
        return _ISLANDS[key]
    nl, nf = len(me.loops), len(me.polygons)
    lv = _arr(me.loops, "vertex_index", nl, 1, np.int64)
    lt = _arr(me.polygons, "loop_total", nf, 1, np.int64)
    ls = np.cumsum(lt) - lt
    face = np.repeat(np.arange(nf), lt)
    nxt = np.arange(nl) + 1; nxt[ls + lt - 1] = ls
    uv = np.round(_arr(me.uv_layers[layer].data, "uv", nl, 2) * 1e6).astype(np.int64)
    a, b = lv, lv[nxt]; ua, ub = uv, uv[nxt]
    swap = a > b
    lo, hi = np.where(swap, b, a), np.where(swap, a, b)
    ulo = np.where(swap[:, None], ub, ua); uhi = np.where(swap[:, None], ua, ub)
    sig = np.column_stack([lo, hi, ulo, uhi])
    order = np.lexsort(sig.T[::-1]); sig, f = sig[order], face[order]
    same = np.all(sig[1:] == sig[:-1], axis=1)
    e1, e2 = f[:-1][same], f[1:][same]
    lab = np.arange(nf)
    while True:
        m = np.minimum(lab[e1], lab[e2])
        new = lab.copy(); np.minimum.at(new, e1, m); np.minimum.at(new, e2, m)
        new = new[new]
        if np.array_equal(new, lab):
            break
        lab = new
    _ISLANDS[key] = lab
    return lab


def fixed_uvs(orig, cp, level, verts, P):
    """Surface-fixed UVs for the corners of `verts` (a vertex that could not slide to its import place, wholly or
    partly): the UV the import carries at the point nearest to the vertex's position P, within the UV island of the
    corner's original face - the texture stays at its import place there although the face did not get back."""
    lt0, own_face = checks.cage_faces(orig, cp)
    owner = np.repeat(own_face, lt0 * 4 ** (level - 1))
    lv = _arr(cp.loops, "vertex_index", len(cp.loops), 1, np.int64)
    L = np.where(verts[lv])[0]
    if not len(L) or len(owner) * 4 != len(cp.loops):
        return 0
    orig.calc_loop_triangles()
    nt = len(orig.loop_triangles)
    tv = _arr(orig.loop_triangles, "vertices", nt, 3, np.int64)
    tl = _arr(orig.loop_triangles, "loops", nt, 3, np.int64)
    tf = _arr(orig.loop_triangles, "polygon_index", nt, 1, np.int64)
    vco = _arr(orig.vertices, "co", len(orig.vertices), 3)
    cf = owner[L // 4]
    X = P[lv[L]]
    for layer in [u.name for u in orig.uv_layers]:
        if layer not in cp.uv_layers:
            continue
        isl = uv_islands(orig, layer)
        uv0 = _arr(orig.uv_layers[layer].data, "uv", len(orig.loops), 2)
        uvc = _arr(cp.uv_layers[layer].data, "uv", len(cp.loops), 2)
        k = isl[cf]
        for kk in np.unique(k):
            tris = np.where(isl[tf] == kk)[0]
            bvh = BVHTree.FromPolygons(vco.tolist(), tv[tris].tolist())
            j = np.where(k == kk)[0]
            cen = np.round(vco[tv[tris]].mean(1), 6)

            def nearest(x, face):
                """Of triangles at the same distance (within TIE): the one of the corner's own face, then the first
                by position - whatever the tree (UPDATES #54, run 287: 3484 in batches took another triangle)."""
                r = bvh.find_nearest(x)
                if r[2] is None:
                    return r
                near = bvh.find_nearest_range(x, r[3] + TIE)
                if len(near) < 2:
                    return r
                return min(near, key=lambda q: (tf[tris[q[2]]] != face, tuple(cen[q[2]])))
            res = [nearest(x, f) for x, f in zip(X[j].tolist(), cf[j].tolist())]
            got = np.array([r[2] is not None for r in res])
            if not got.any():
                continue
            j = j[got]; res = [r for r in res if r[2] is not None]
            loc = np.array([r[0] for r in res], np.float64).reshape(-1, 3)
            T = tris[np.array([r[2] for r in res], np.int64)]
            W = _bary(loc, vco[tv[T, 0]], vco[tv[T, 1]], vco[tv[T, 2]])
            uvc[L[j]] = (W[:, :, None] * uv0[tl[T]]).sum(1)
        cp.uv_layers[layer].data.foreach_set("uv", uvc.ravel())
    return len(L)


def slide(cp, Pl, lv, orig=None, level=None):
    """Move the vertices of `cp` (the smooth copy) along its surface to the points nearest to Pl (the parametric
    points, same vertex order; lv: corner -> vertex). A vertex that cannot get there without a fold (or stays: a
    boundary, a sharp edge) gets surface-fixed UVs instead (fixed_uvs; needs orig and level). Returns a report."""
    n = len(cp.vertices)
    if len(Pl) != n:
        return {"skipped": "topology"}
    Ps = _arr(cp.vertices, "co", n, 3)
    nl, nf = len(cp.loops), len(cp.polygons)
    vn = _arr(cp.vertex_normals, "vector", n, 3)

    # boundary vertices stay (seams between shells must keep coinciding): marked on the import (mark), carried along
    a = cp.attributes.get(EDGE)
    fixed = np.zeros(n, bool)
    if a is not None:
        fixed = _arr(a.data, "value", n, 1, np.float32) > 0.999
        cp.attributes.remove(cp.attributes[EDGE])
    a = cp.attributes.get(SHELL)
    shell = None
    if a is not None:
        shell = np.round(_arr(a.data, "value", n, 1, np.float32)).astype(np.int64)
        cp.attributes.remove(cp.attributes[SHELL])
    # the slide is the part of the way to the parametric point along the surface (vertex normal; the face-normal
    # average counted the inward pull at edges as a slide and queried 6.8x as many points, run 222)
    d = Pl - Ps
    dt = d - (d * vn).sum(1)[:, None] * vn
    # the part size: the import's (UPDATES #54 - the copy's own box before; in batches the whole mesh's)
    if SIZE_PIN[0]:
        size = SIZE_PIN[0]
    elif orig is not None and len(orig.vertices):
        size = part_size(orig)
    else:
        size = float(np.ptp(Ps, 0).max()) or 1.0
    todo = np.where(~fixed & (np.linalg.norm(dt, axis=1) > MIN_SLIDE * size))[0]
    if not len(todo):
        # nothing slides - the vertices that stay (boundary) still get surface-fixed UVs where they should have slid
        # (run 287: this return skipped them, so a part whose only far vertices are boundary ones kept smoothed UVs
        # there - in a batch of 3484 while the whole copy, with something to slide elsewhere, fixed them)
        need = np.linalg.norm(dt, axis=1) > MIN_SLIDE * size
        nfix = fixed_uvs(orig, cp, level, need, Ps) if (orig is not None and level and need.any()) else 0
        return {"moved": 0, "kept": int(fixed.sum()), "uv_fixed_corners": int(nfix), "max_slide": 0.0}

    if nl == 4 * nf:
        # a subdivided copy is all quads: its triangles straight from the corners, no triangulation and no reads
        # (run 222: loop triangles and their three reads were a fifth of the slide)
        lface = np.arange(nl) // 4
        base = 4 * np.arange(nf)[:, None]
        trl = np.vstack([base + [0, 1, 2], base + [0, 2, 3]])
        tri = lv[trl]
        tf = np.concatenate([np.arange(nf), np.arange(nf)])
    else:
        return {"skipped": "not all quads"}           # a subdivided copy always is; nothing else is slid
    fn = _arr(cp.polygons, "normal", nf, 3)
    cn = _arr(cp.corner_normals, "vector", nl, 3)
    tri_shell = shell[tri[:, 0]] if shell is not None else None
    # one tree per shell (UPDATES #54): a vertex looks for its nearest point on its own shell only - the tree of the
    # whole copy also held the other shells, and what it answered at their edges depended on which shells were in
    # it (a batch has fewer); without shells (no rb_shell) the one tree of the copy
    bvh = BVHTree.FromPolygons(Ps.tolist(), tri.tolist()) if tri_shell is None else None
    if tri_shell is not None:
        by_shell = np.argsort(tri_shell, kind="stable")
        keys, first = np.unique(tri_shell[by_shell], return_index=True)
        shell_tris = dict(zip(keys.tolist(), np.split(by_shell, first[1:])))
    tri_n = fn[tf]
    tri_c = np.round(Ps[tri].mean(1), 6)
    tv_ = vn[tri]                                                   # how curved each triangle is (as `spread` below)
    tri_flat = np.minimum(np.minimum((tv_[:, 0] * tv_[:, 1]).sum(1), (tv_[:, 1] * tv_[:, 2]).sum(1)), (tv_[:, 0] * tv_[:, 2]).sum(1))
    del tv_
    own_trees = {}

    def canonical(tree, ids, p, v):
        """The nearest point of `tree` to `p` - of several triangles at the same distance (a point on an edge) the one
        whose face turns most to the vertex's normal, then the least curved, then the first by position: the same
        answer whatever the tree (UPDATES #54 - the tree of a batch broke such ties otherwise than the tree of the
        whole copy; run 287, 3815: a point on the edge of two coplanar quads). `ids`: the triangle numbers of the
        tree's triangles (None: the same). Same distance: within TIE mm - the float noise of the copy's points."""
        r = tree.find_nearest(p)
        if r[2] is None:
            return r
        near = tree.find_nearest_range(p, r[3] + TIE)                  # mathutils_bvhtree.cc 476
        if len(near) > 1:
            cand = [(q, int(ids[q[2]]) if ids is not None else q[2]) for q in near]
            # within TIE_COS counts as equal: the normals of a copy carry float noise of their own summation
            # order (run 287, 32013: 0.998338 / 0.998337 in the whole copy, 0.998336 / 0.998336 in its batch)
            facing = np.array([float(tri_n[c[1]] @ vn[v]) for c in cand])
            cand = [c for c, f in zip(cand, facing) if f >= facing.max() - TIE_COS]
            flat = np.array([float(tri_flat[c[1]]) for c in cand])
            cand = [c for c, f in zip(cand, flat) if f >= flat.max() - TIE_COS]
            best = min(cand, key=lambda c: tuple(tri_c[c[1]]))
            return best[0][0], best[0][1], best[1], best[0][3]
        return r[0], r[1], int(ids[r[2]]) if ids is not None else r[2], r[3]

    def find_own(points, who):
        """Nearest points on the vertices' own shells (UPDATES #54: the nearest of the whole copy could lie on another
        shell - the vertex then stayed - and the answer depended on the shells in the tree)."""
        if tri_shell is None:
            return [canonical(bvh, None, p, who[j]) for j, p in enumerate(points)]
        out = []
        for j, p in enumerate(points):
            s = int(shell[who[j]])
            if s not in own_trees:
                sel = shell_tris.get(s)
                if sel is None or not len(sel):
                    own_trees[s] = None
                else:
                    vs, local = np.unique(tri[sel], return_inverse=True)
                    own_trees[s] = (BVHTree.FromPolygons(Ps[vs].tolist(), local.reshape(-1, 3).tolist()), sel)
            t = own_trees[s]
            out.append(canonical(t[0], t[1], p, who[j]) if t is not None else (None, None, None, None))
        return out
    res = find_own(Pl[todo].tolist(), todo)                         # the only per-point Python work
    found = np.array([r[2] is not None for r in res])              # no hit (4856, catalog 1.2.5): the point stays
    loc = np.array([r[0] if r[2] is not None else (0.0, 0.0, 0.0) for r in res], np.float64).reshape(-1, 3)
    hit = np.array([r[2] if r[2] is not None else 0 for r in res], np.int64)
    # along the smooth normal field instead of to the nearest point of the faceted copy (run 222): near a facet edge
    # many points share one nearest point and swap order there (folds at level 3); the foot of the interpolated normal
    # through the point moves on continuously. A few fixed-point steps: foot -> its normal -> drop the point onto it.
    for _ in range(PROJECT_ITER):
        Wq = _bary(loc, Ps[tri[hit, 0]], Ps[tri[hit, 1]], Ps[tri[hit, 2]])
        nq = (Wq[:, :, None] * vn[tri[hit]]).sum(1)
        nq /= np.maximum(np.linalg.norm(nq, axis=1), 1e-12)[:, None]
        tgt = Pl[todo] - ((Pl[todo] - loc) * nq).sum(1)[:, None] * nq
        res = find_own(tgt.tolist(), todo)
        got = np.array([r[2] is not None for r in res])
        loc = np.where(got[:, None], np.array([r[0] if r[2] is not None else (0.0, 0.0, 0.0) for r in res], np.float64).reshape(-1, 3), loc)
        hit = np.where(got, np.array([r[2] if r[2] is not None else 0 for r in res], np.int64), hit)
    ok = found & ((fn[tf[hit]] * vn[todo]).sum(1) >= np.cos(np.radians(SHARP_DEG)))   # same side of a sharp edge
    # no slide onto a strongly curved facet (run 224, stud rims at level 1): the flat facet lies below the rounding and
    # the slid point dents the shading - such a point stays exact on the surface and gets surface-fixed UVs
    Nt = vn[tri[hit]]
    spread = np.minimum(np.minimum((Nt[:, 0] * Nt[:, 1]).sum(1), (Nt[:, 1] * Nt[:, 2]).sum(1)), (Nt[:, 0] * Nt[:, 2]).sum(1))
    ok &= spread >= np.cos(np.radians(CURVE_DEG))
    if shell is not None:                                          # only on its own shell (run 224)
        ok &= shell[tri[hit, 0]] == shell[todo]
    # no jumps (catalog 1.2.5, 15462: 6.3 mm): the nearest point may lie across a thin wall or in a hole - a vertex
    # only goes about as far as its parametric point is away
    ok &= np.linalg.norm(loc - Ps[todo], axis=1) <= JUMP * np.linalg.norm(Pl[todo] - Ps[todo], axis=1) + 1e-9
    todo, loc, hit = todo[ok], loc[ok], hit[ok]
    new = Ps.copy(); new[todo] = loc

    # no folds (run 222): at a convex rounding the points of both neighbouring faces land on the same narrow strip and
    # can swap their order - a quad that turns against the smooth copy's face pulls its slid points back halfway,
    # FOLD_STEPS times, then the rest of them stays where the smoothing put it
    quads = lv.reshape(-1, 4)
    moving = np.zeros(n, bool); moving[todo] = True
    # the surface normal where each vertex lands (a quad that slides onto a rounding turns with it - only a quad
    # turned against the surface under it folds)
    Wl = _bary(loc, Ps[tri[hit, 0]], Ps[tri[hit, 1]], Ps[tri[hit, 2]])
    sn = vn.copy(); sn[todo] = (Wl[:, :, None] * vn[tri[hit]]).sum(1)
    on = None
    if orig is not None and level:
        lt0, own_face = checks.cage_faces(orig, cp)
        ofn = _arr(orig.polygons, "normal", len(orig.polygons), 3)
        if int((lt0 * 4 ** (level - 1)).sum()) == nf:
            on = ofn[np.repeat(own_face, lt0 * 4 ** (level - 1))]
    for step in range(FOLD_STEPS + 1):
        q = new[quads]
        qn = np.cross(q[:, 2] - q[:, 0], q[:, 3] - q[:, 1])
        qn /= np.maximum(np.linalg.norm(qn, axis=1), 1e-30)[:, None]
        ref = sn[quads].sum(1); ref /= np.maximum(np.linalg.norm(ref, axis=1), 1e-30)[:, None]
        bad = (qn * ref).sum(1) < FOLD_COS
        if on is not None:                               # nor turned against its original face (the fold check, W10b)
            bad |= (qn * on).sum(1) < 0.0
        vb = np.zeros(n, bool); vb[quads[bad].ravel()] = True
        vb &= moving
        if not vb.any():
            break
        new[vb] = Ps[vb] if step == FOLD_STEPS else Ps[vb] + 0.5 * (new[vb] - Ps[vb])
        if step == FOLD_STEPS:
            moving[vb] = False
    keep_ = moving[todo]
    todo, hit = todo[keep_], hit[keep_]
    pulled = np.abs(new[todo] - loc[keep_]).max(1) > 0
    if pulled.any():                                     # back on the surface, and its triangle for the normals
        res = find_own(new[todo[pulled]].tolist(), todo[pulled])
        idx = todo[pulled]
        for j, r in enumerate(res):
            if r[2] is not None:
                new[idx[j]] = r[0]; hit[np.where(pulled)[0][j]] = r[2]
    # final check, also after the snap back onto the surface: putting a vertex back can fold a quad whose other
    # vertices slid far (2552: 10 mm) - repeat until no quad with a slid vertex folds (each round puts at least one
    # vertex back, so it ends)
    while True:
        q = new[quads]
        qn = np.cross(q[:, 2] - q[:, 0], q[:, 3] - q[:, 1])
        qn /= np.maximum(np.linalg.norm(qn, axis=1), 1e-30)[:, None]
        ref = sn[quads].sum(1); ref /= np.maximum(np.linalg.norm(ref, axis=1), 1e-30)[:, None]
        bad = (qn * ref).sum(1) < FOLD_COS
        if on is not None:
            bad |= (qn * on).sum(1) < 0.0
        vb = np.zeros(n, bool); vb[quads[bad].ravel()] = True
        vb &= moving
        if not vb.any():
            break
        new[vb] = Ps[vb]; moving[vb] = False
    stay = ~moving[todo]
    pulled |= stay
    todo, hit, pulled = todo[~stay], hit[~stay], pulled[~stay]
    loc = new[todo]
    W = _bary(loc, Ps[tri[hit, 0]], Ps[tri[hit, 1]], Ps[tri[hit, 2]])
    if PHONG and len(todo):
        # on the curved surface, not the flat facet (run 224): a point slid onto a facet of a coarse copy lies below the
        # rounding (dents in the shading, studs at level 1) - Phong tessellation lifts it along the vertex normals
        A, Nn = Ps[tri[hit]], vn[tri[hit]]                         # (k, 3, 3)
        proj = loc[:, None, :] - (((loc[:, None, :] - A) * Nn).sum(2))[:, :, None] * Nn
        new[todo] = (1 - PHONG) * loc + PHONG * (W[:, :, None] * proj).sum(1)
        loc = new[todo]
    # every vertex that should have slid visibly but did not get all the way: surface-fixed UVs at its position
    need = (np.linalg.norm(dt, axis=1) > MIN_SLIDE * size)
    full = np.zeros(n, bool); full[todo[~pulled]] = True
    need &= ~full
    nfix = fixed_uvs(orig, cp, level, need, new) if (orig is not None and level and need.any()) else 0

    # normals per corner, from the found triangle when it faces the corner's own face's way - only the corners of
    # moved vertices are touched (whole-loop arrays cost memory traffic with 12 processes, run 222)
    vt = np.full(n, -1, np.int64); vt[todo] = np.arange(len(todo))
    L = np.where(vt[lv] >= 0)[0]
    k = vt[lv[L]]; t = hit[k]
    same = (fn[tf[t]] * fn[lface[L]]).sum(1) >= np.cos(np.radians(SHARP_DEG))
    L, k, t = L[same], k[same], t[same]
    nn = (W[k][:, :, None] * cn[trl[t]]).sum(1)
    nn /= np.maximum(np.linalg.norm(nn, axis=1), 1e-12)[:, None]
    ln = cn
    ln[L] = nn

    cp.vertices.foreach_set("co", new.ravel())
    if FREE_NORMALS:
        # free custom normals (a float vector per corner): 8x faster to set, but 12 instead of 4 bytes per corner -
        # Optimus 328 -> 508 MB and slower saving (run 222)
        a = cp.attributes.get("custom_normal")
        if a is not None:
            cp.attributes.remove(a)
        cp.attributes.new("custom_normal", 'FLOAT_VECTOR', 'CORNER').data.foreach_set("vector", ln.ravel())
        cp.update()
    else:
        cp.update()
        cp.normals_split_custom_set(ln)
    mv = np.linalg.norm(new - Ps, axis=1)
    return {"moved": int(len(todo)), "kept": int((~ok).sum() + fixed.sum()), "uv_fixed_corners": int(nfix),
            "max_slide": float(mv.max()) if n else 0.0}
