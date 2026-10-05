"""Texture-aware UVs of the subdivided copies (W14b, rules 3.5, runs 212-218).

Blender's Subdivision modifier treats a part's UVs one way for the whole object (uv_smooth), but Mecabricks textures
need two treatments:
- a texture is fixed to the part's surface: a print or a logo stays where it is although the subdivision moves the
  points within a flat face, a grain stays even next to a rounding (3044). So every corner of the copy takes the UV of
  the nearest point of the original surface ("surface-fixed"). A point that slid across a UV border during the
  subdivision is not clamped to the border (that smeared the texture there): the UV map of its own original face is
  continued past the border.
- a line drawn on a narrow curved strip belongs to that strip's faces (the mould line of 7052 in its height map), the
  curved rim of a part carries its normal-map details on its faces. So on the curved faces of UV islands whose
  texture holds sparse drawn features the copy keeps linear UVs (the subdivided face carries the texture of its
  original face), blended over two edge rings so no edge shows.
The copy is baked with linear UVs (uv_smooth NONE); texture_uvs() then writes the final UVs into it. A copy whose
faces do not follow the original's in blocks is left with the linear UVs' fallback decided by the caller.

Measures (run 218): 7052 like the import, 3044 without streaks (distorted child faces 4.3 % -> 0.9 %), window glass
86209 logo intact; 363 library parts without errors."""
import re
import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils import Vector
from mathutils.geometry import closest_point_on_tri

FLAT_DEG = 2.0              # an original face is curved when a neighbour in its island bends by more than this
SPARSE = (0.003, 0.25)      # share of conspicuous texels in an island's texture area: drawn features
REL = 0.15                  # conspicuous texel: deviation from the image's dominant value > REL x its 99.5 % value
RINGS = 2                   # edge rings over which linear and surface-fixed UVs are blended
SAMPLES = 4000              # random texture samples per island for the feature share
# a Mecabricks print: <part>d<n>[_bump|_metal|_data].png, also custom ones ("122231.3814d1221_(1).png")
PRINT = re.compile(r"[0-9a-z]d\d+(_[a-z]+|_\(\d+\))?\.(png|jpe?g)(\.\d+)?$", re.I)

_DEV = {}                   # image name and size -> deviation map (images are shared by many parts)


def _owner(orig, level):
    sizes = np.empty(len(orig.polygons), np.int64); orig.polygons.foreach_get("loop_total", sizes)
    return np.repeat(np.arange(len(orig.polygons)), sizes * 4 ** (level - 1))


def uv_islands(me, layer):
    """UV island per face: faces joined across an edge whose corners carry the same UVs on both sides."""
    uv = np.empty(len(me.loops) * 2); me.uv_layers[layer].data.foreach_get("uv", uv); uv = np.round(uv.reshape(-1, 2), 6)
    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
    parent = np.arange(len(me.polygons))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    seen = {}
    for f in range(len(me.polygons)):
        s, n = ls[f], lt[f]
        for i in range(n):
            la, lb = s + i, s + (i + 1) % n
            va, vb = lv[la], lv[lb]
            if va < vb:
                key, sig = (va, vb), (tuple(uv[la]), tuple(uv[lb]))
            else:
                key, sig = (vb, va), (tuple(uv[lb]), tuple(uv[la]))
            q = seen.get(key)
            if q is None:
                seen[key] = (f, sig)
            elif q[1] == sig:
                ra, rb = find(f), find(q[0])
                if ra != rb: parent[ra] = rb
    return np.array([find(i) for i in range(len(me.polygons))])


def _bary(P, A, B, C):
    """Barycentric weights of points P (n x 3) in triangles A, B, C (n x 3 each), projected into each plane."""
    v0, v1, v2 = B - A, C - A, P - A
    d00 = (v0 * v0).sum(1); d01 = (v0 * v1).sum(1); d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1); d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    v = (d11 * d20 - d01 * d21) / den; w = (d00 * d21 - d01 * d20) / den
    W = np.clip(np.stack([1 - v - w, v, w], 1), 0.0, 1.0)            # the point lies on the triangle: 0..1
    deg = np.abs(den) < 1e-20 * np.maximum(d00 * d11, 1e-300)          # degenerate triangle (3386, run 219)
    W[deg] = 1.0 / 3.0
    return W / np.maximum(W.sum(1), 1e-12)[:, None]


def _closest_on_tri(P, A, B, C):
    """Closest points on triangles A, B, C to points P (all n x 3), vectorised (Ericson, Real-Time Collision
    Detection 5.1.5)."""
    ab, ac, ap = B - A, C - A, P - A
    d1 = (ab * ap).sum(1); d2 = (ac * ap).sum(1)
    bp = P - B; d3 = (ab * bp).sum(1); d4 = (ac * bp).sum(1)
    cp = P - C; d5 = (ab * cp).sum(1); d6 = (ac * cp).sum(1)
    vc = d1 * d4 - d3 * d2; vb = d5 * d2 - d1 * d6; va = d3 * d6 - d5 * d4
    den = va + vb + vc; den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    v = vb / den; w = vc / den
    out = A + ab * v[:, None] + ac * w[:, None]                                  # inside the face
    def put(mask, val):
        out[mask] = val[mask]
    with np.errstate(divide="ignore", invalid="ignore"):
        e_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        t = np.clip((d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1, (d4 - d3) + (d5 - d6)), 0, 1)
        put(e_bc, B + (C - B) * t[:, None])
        e_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = np.clip(d2 / np.where(d2 - d6 == 0, 1, d2 - d6), 0, 1); put(e_ac, A + ac * t[:, None])
        e_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = np.clip(d1 / np.where(d1 - d3 == 0, 1, d1 - d3), 0, 1); put(e_ab, A + ab * t[:, None])
    put((d6 >= 0) & (d5 <= d6), C); put((d3 >= 0) & (d4 <= d3), B); put((d1 <= 0) & (d2 <= 0), A)
    return out


def surface_fixed(orig, cp, owner, layer, isl, T):
    """UV per corner of `cp` from the nearest point of the original surface (see the module notes). T: shared
    triangle data of the original (verts, loops, face, bvh, coordinates)."""
    tv, tl, tf, bvh, vco = T
    uv = np.empty(len(orig.loops) * 2); orig.uv_layers[layer].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    lv = np.empty(len(cp.loops), np.int64); cp.loops.foreach_get("vertex_index", lv)
    lt = np.empty(len(cp.polygons), np.int64); cp.polygons.foreach_get("loop_total", lt)
    fol = np.repeat(np.arange(len(cp.polygons)), lt)
    own_face = owner[fol]                                   # original face of each corner
    k = isl[own_face]
    key = lv * (int(isl.max()) + 1) + k                    # one node per (vertex, island)
    nodes, first, inv = np.unique(key, return_index=True, return_inverse=True)
    cco = np.empty(len(cp.vertices) * 3); cp.vertices.foreach_get("co", cco); cco = cco.reshape(-1, 3)
    P = cco[lv[first]]
    loc = np.empty((len(nodes), 3)); ti = np.empty(len(nodes), np.int64)
    for i, p in enumerate(P):                               # the only per-point Python work: the BVH query
        l_, n_, t_, d_ = bvh.find_nearest(p)
        loc[i] = l_; ti[i] = t_
    tri_isl = isl[tf]
    out = np.empty((len(nodes), 2))
    same = tri_isl[ti] == k[first]
    W = _bary(loc[same], vco[tv[ti[same], 0]], vco[tv[ti[same], 1]], vco[tv[ti[same], 2]])
    out[same] = (W[:, :, None] * uv[tl[ti[same]]]).sum(1)
    # slid across a UV border: nearest point on the own original face, its map continued past the border
    cr = np.where(~same)[0]
    if len(cr):
        fcr = own_face[first[cr]]
        tri_of_face = [[] for _ in range(len(orig.polygons))]
        for t, f in enumerate(tf):
            tri_of_face[f].append(t)
        width = max(len(tri_of_face[f]) for f in np.unique(fcr))
        cand = np.full((len(cr), width), -1, np.int64)
        for j, f in enumerate(fcr):
            ts = tri_of_face[f]; cand[j, :len(ts)] = ts
        Pc = P[cr]
        best_d = np.full(len(cr), np.inf); best_q = np.zeros((len(cr), 3)); best_t = np.zeros(len(cr), np.int64)
        for c in range(width):
            t = cand[:, c]; ok = t >= 0
            if not ok.any():
                continue
            tt = np.where(ok, t, 0)
            q = _closest_on_tri(Pc, vco[tv[tt, 0]], vco[tv[tt, 1]], vco[tv[tt, 2]])
            d = np.linalg.norm(q - Pc, axis=1); d[~ok] = np.inf
            better = d < best_d
            best_d[better] = d[better]; best_q[better] = q[better]; best_t[better] = tt[better]
        A, B, C = vco[tv[best_t, 0]], vco[tv[best_t, 1]], vco[tv[best_t, 2]]
        Ua, Ub, Uc = uv[tl[best_t, 0]], uv[tl[best_t, 1]], uv[tl[best_t, 2]]
        w = _bary(best_q, A, B, C)
        uq = w[:, :1] * Ua + w[:, 1:2] * Ub + w[:, 2:] * Uc
        e1, e2 = B - A, C - A; nrm = np.cross(e1, e2)
        l1 = np.linalg.norm(e1, axis=1); ln = np.linalg.norm(nrm, axis=1)
        good = (l1 > 1e-12) & (ln > 1e-14)
        x = e1 / np.maximum(l1, 1e-12)[:, None]; y = np.cross(nrm / np.maximum(ln, 1e-14)[:, None], x)
        G = np.zeros((len(cr), 2, 2)); G[:, 0, 0] = l1; G[:, 0, 1] = (e2 * x).sum(1); G[:, 1, 1] = (e2 * y).sum(1)
        good &= np.abs(np.linalg.det(G)) > 1e-14
        D = np.stack([Ub - Ua, Uc - Ua], 2)
        J = D @ np.linalg.inv(np.where(good[:, None, None], G, np.eye(2)))
        off = loc[cr] - best_q
        o2 = np.stack([(off * x).sum(1), (off * y).sum(1)], 1)
        ext = uq + (J @ o2[:, :, None])[:, :, 0]
        # never further than the triangle's own UV size: a near-degenerate triangle gives a huge map (3386)
        usize = np.maximum.reduce([np.linalg.norm(Ub - Ua, axis=1), np.linalg.norm(Uc - Ua, axis=1), np.linalg.norm(Uc - Ub, axis=1)])
        good &= np.linalg.norm(ext - uq, axis=1) <= 2.0 * usize + 1e-9
        out[cr] = np.where(good[:, None], ext, uq)
    return out[inv]


def layer_images(mesh, layer):
    """Images whose Vector input comes from a UV Map node reading `layer` (also inside node groups)."""
    out = {}
    def walk(nt, seen):
        if nt.name in seen:
            return
        seen.add(nt.name)
        for n in nt.nodes:
            if n.bl_idname == 'ShaderNodeTexImage' and n.image and n.inputs['Vector'].is_linked:
                src = n.inputs['Vector'].links[0].from_node
                if src.bl_idname == 'ShaderNodeUVMap' and src.uv_map == layer:
                    out.setdefault(n.image.name, n.image)
            if n.bl_idname == 'ShaderNodeGroup' and n.node_tree:
                walk(n.node_tree, seen)
    for m in mesh.materials:
        if m and m.node_tree:
            walk(m.node_tree, set())
    return list(out.values())


def _deviation(im):
    key = (im.name, tuple(im.size))
    if key not in _DEV:
        w, h = im.size
        if w * h == 0:
            _DEV[key] = None
        else:
            px = np.empty(w * h * im.channels, np.float32); im.pixels.foreach_get(px)
            px = px.reshape(h, w, im.channels)[..., :3]
            dev = np.abs(px - np.median(px.reshape(-1, 3), axis=0)).max(2)
            _DEV[key] = (dev, w, h, float(np.percentile(dev, 99.5)))
    return _DEV[key]


def feature_islands(orig, layer, isl, candidates, T):
    """Islands among `candidates` whose texture area holds sparse drawn features. Only the part's own textures
    count (Mecabricks `<part>_<n>.png`: mould lines, rings, details on the faces they were drawn for). A layer that
    carries a print stays surface-fixed as a whole: the print was laid onto the part's surface, and linear UVs
    shrank the face print of minifig head 3626 (run 219)."""
    ims = []
    layer_ims = layer_images(orig, layer)
    if any(PRINT.search(im.name) for im in layer_ims):
        return set()
    for im in layer_ims:
        try:
            d = _deviation(im)
        except Exception:
            d = None
        if d is not None and d[3] > 1e-4:
            ims.append(d)
    if not ims or not candidates:
        return set()
    tv, tl, tf, bvh, vco = T
    uv = np.empty(len(orig.loops) * 2); orig.uv_layers[layer].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    tri_isl = isl[tf]
    feat = set()
    rng = np.random.default_rng(1)
    U3 = uv[tl]                                                    # (tris, 3, 2)
    area = np.abs(np.cross(U3[:, 1] - U3[:, 0], U3[:, 2] - U3[:, 0])) / 2
    for kk in candidates:
        tris = np.where((tri_isl == kk) & (area > 1e-12))[0]
        best = 0.0
        if len(tris):
            # SAMPLES random points over the island's UV area (by area): the texture there, without rasterising
            pick = rng.choice(tris, size=SAMPLES, p=area[tris] / area[tris].sum())
            r1, r2 = rng.random(SAMPLES), rng.random(SAMPLES)
            sq = np.sqrt(r1)
            Q = (1 - sq)[:, None] * U3[pick, 0] + (sq * (1 - r2))[:, None] * U3[pick, 1] + (sq * r2)[:, None] * U3[pick, 2]
            for dev, w, h, amp in ims:
                x = np.clip((np.mod(Q[:, 0], 1.0) * w).astype(int), 0, w - 1)
                y = np.clip((np.mod(Q[:, 1], 1.0) * h).astype(int), 0, h - 1)
                best = max(best, float((dev[y, x] > REL * amp).mean()))
        if SPARSE[0] <= best <= SPARSE[1]:
            feat.add(kk)
    return feat


def texture_uvs(orig, cp, level):
    """Rewrite the UVs of `cp` (baked with linear UVs at `level`). Returns a report, or raises."""
    owner = _owner(orig, level)
    if len(owner) != len(cp.polygons) or not len(orig.uv_layers):
        return {"skipped": True}
    orig.calc_loop_triangles()
    nt = len(orig.loop_triangles)
    tv = np.empty(nt * 3, np.int64); orig.loop_triangles.foreach_get("vertices", tv); tv = tv.reshape(-1, 3)
    tl = np.empty(nt * 3, np.int64); orig.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    tf = np.empty(nt, np.int64); orig.loop_triangles.foreach_get("polygon_index", tf)
    vco = np.empty(len(orig.vertices) * 3); orig.vertices.foreach_get("co", vco); vco = vco.reshape(-1, 3)
    bvh = BVHTree.FromPolygons([tuple(c) for c in vco], tv.tolist())
    T = (tv, tl, tf, bvh, vco)
    nrm = np.empty(len(orig.polygons) * 3); orig.polygons.foreach_get("normal", nrm); nrm = nrm.reshape(-1, 3)
    ef = {}
    for p in orig.polygons:
        for ek in p.edge_keys:
            ef.setdefault(ek, []).append(p.index)
    pairs = np.array([fs for fs in ef.values() if len(fs) == 2], np.int64).reshape(-1, 2)
    bend = np.degrees(np.arccos(np.clip((nrm[pairs[:, 0]] * nrm[pairs[:, 1]]).sum(1), -1, 1))) if len(pairs) else np.zeros(0)
    lvx = np.empty(len(cp.loops), np.int64); cp.loops.foreach_get("vertex_index", lvx)
    ev = np.empty(len(cp.edges) * 2, np.int64); cp.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
    lt = np.empty(len(cp.polygons), np.int64); cp.polygons.foreach_get("loop_total", lt)
    fol = np.repeat(np.arange(len(cp.polygons)), lt)
    rep = {}
    for layer in [u.name for u in orig.uv_layers]:
        isl = uv_islands(orig, layer)
        lin = np.empty(len(cp.loops) * 2); cp.uv_layers[layer].data.foreach_get("uv", lin); lin = lin.reshape(-1, 2)
        sur = surface_fixed(orig, cp, owner, layer, isl, T)
        curved = np.zeros(len(orig.polygons), bool)
        if len(pairs):
            m = (isl[pairs[:, 0]] == isl[pairs[:, 1]]) & (bend > FLAT_DEG)
            curved[pairs[m].ravel()] = True
        feat = feature_islands(orig, layer, isl, set(np.unique(isl[curved]).tolist()), T)
        want = curved & np.isin(isl, list(feat)) if feat else np.zeros(len(orig.polygons), bool)
        w = np.zeros(len(cp.vertices)); np.maximum.at(w, lvx, want[owner[fol]].astype(float))
        for _ in range(RINGS):
            acc = w.copy(); c = np.ones(len(w))
            np.add.at(acc, ev[:, 0], w[ev[:, 1]]); np.add.at(c, ev[:, 0], 1)
            np.add.at(acc, ev[:, 1], w[ev[:, 0]]); np.add.at(c, ev[:, 1], 1)
            w = acc / c
        wc = w[lvx][:, None]
        res = lin * wc + sur * (1 - wc)
        bad = ~np.isfinite(res).all(1)
        res[bad] = lin[bad]                                            # last guard: the linear UV
        cp.uv_layers[layer].data.foreach_set("uv", res.ravel())
        rep[layer] = len(feat)
    return rep
