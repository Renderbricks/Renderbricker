"""Verify a processed part against its import (vectorised in run 35; the loop version is legacy/verify_part_v1.py).

Usage:
  blender -b <processed.blend> --python verify_part.py -- <original.blend>
Checks: original mesh unchanged, imported normals unchanged (subdiv off), flipped
sub-faces, how far the subdivided open edges leave the original outline, seam gaps
(at vertices and along edges), shading data of the result.
"""
import bpy, math, sys
import numpy as np
from collections import defaultdict
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d

orig_path = sys.argv[sys.argv.index("--") + 1]
import importlib.util as _ilu
_sp = _ilu.spec_from_file_location("rbcore", __file__.replace("verify_part.py", "mecabricks_subdiv.py"))
CORE = _ilu.module_from_spec(_sp); _sp.loader.exec_module(CORE)
LEVELS_GUESS = 2

with bpy.data.libraries.load(orig_path) as (src, dst):
    names = list(src.meshes)
    dst.meshes = list(names)      # a copy: Blender fills the list it is given with the loaded meshes
# loaded meshes are renamed where a name is taken (X -> X.003), so pair them by the order of the request
originals = dict(zip(names, dst.meshes))


def self_intersecting(cos):
    """K11 as in mecabricks_subdiv.py: polygon whose edges cross (bowtie quad of the import)."""
    n = len(cos)
    if n < 4:
        return False
    nrm = max(((cos[(i + 1) % n] - cos[i]).cross(cos[(i + 2) % n] - cos[(i + 1) % n]) for i in range(n)),
              key=lambda v: v.length)
    if nrm.length < 1e-12:
        return False
    ax = nrm.normalized().orthogonal().normalized(); ay = nrm.normalized().cross(ax)
    P = [Vector((c.dot(ax), c.dot(ay))) for c in cos]
    return any(intersect_line_line_2d(P[i], P[(i + 1) % n], P[j], P[(j + 1) % n])
               for i in range(n) for j in range(i + 2, n) if not (i == 0 and j == n - 1))


def arr(coll, attr, n, width=3, dtype=np.float64):
    a = np.empty(n * width, dtype); coll.foreach_get(attr, a)
    return a.reshape(-1, width) if width > 1 else a


def boundary_edges(m):
    """Indices and vertex pairs of the open edges (edges with exactly one face)."""
    cnt = np.bincount(arr(m.loops, "edge_index", len(m.loops), 1, np.int64), minlength=len(m.edges))
    ids = np.nonzero(cnt == 1)[0]
    return ids, arr(m.edges, "vertices", len(m.edges), 2, np.int64)[ids]


def seg_dist(P, A, B):
    """Row-wise distance of point P[i] to segment A[i]-B[i] (P may also broadcast against A, B)."""
    D = B - A
    t = np.clip(((P - A) * D).sum(-1) / np.maximum((D * D).sum(-1), 1e-12), 0, 1)
    return np.sqrt((((A + D * t[..., None]) - P) ** 2).sum(-1))


def seg_dist_min(P, A, B, parent, step=0.25):
    """For every point P[i] the distance to the nearest segment A[j]-B[j], exact.
    The distance to its own parent segment is an upper bound r; any segment closer than
    r has a sample point (spacing <= step) within r + step/2, so a KD-tree over the
    samples yields every candidate (run 35: all pairs took 300 s on the Porsche)."""
    from mathutils.kdtree import KDTree
    r = seg_dist(P, A[parent], B[parent])
    out = r.copy()
    todo = np.nonzero(r > 1e-9)[0]
    if not len(todo):
        return out
    L = np.linalg.norm(B - A, axis=1)
    k = np.maximum(1, np.ceil(L / step).astype(np.int64))       # sub-steps per segment
    seg = np.repeat(np.arange(len(A)), k + 1)
    t = np.concatenate([np.linspace(0, 1, n + 1) for n in k.tolist()])
    S = A[seg] + (B - A)[seg] * t[:, None]
    kd = KDTree(len(S))
    for i, c in enumerate(S.tolist()):
        kd.insert(c, i)
    kd.balance()
    for i in todo.tolist():
        cand = np.unique(seg[[j for _, j, _ in kd.find_range(P[i].tolist(), r[i] + step / 2)]])
        if len(cand):
            out[i] = min(out[i], float(seg_dist(P[i], A[cand], B[cand]).min()))
    return out


def corners_slow(m):
    """Match faces by vertex positions: only needed when the topology differs (P1 forbids that)."""
    cn, out = m.corner_normals, {}
    for p in m.polygons:
        key = frozenset(tuple(round(c, 4) for c in m.vertices[v].co) for v in p.vertices)
        out[key] = (p, {tuple(round(c, 4) for c in m.vertices[m.loops[l].vertex_index].co): cn[l].vector.copy()
                        for l in p.loop_indices})
    return out


sys.stdout.reconfigure(line_buffering=True)      # progress line of the batch scripts counts VERIFY lines
# since run 38 the links of a mesh use a subdivided copy of it (copy["rb_original"] names
# the imported mesh, original["rb_view"] / ["rb_render"] name the copies); the original
# stays in the file. Checked: the original against the import, the render copy as the
# subdivided result, and that every object uses the viewport copy without modifiers.
def original_of(m):
    n = m.get("rb_original")
    return bpy.data.meshes.get(n, m) if n else m

_objs = [o for o in bpy.data.objects if o.type == 'MESH' and not o.name.startswith("RB ")]
groups = {}
for o in _objs:
    groups.setdefault(original_of(o.data), []).append(o)
print(f"MESHES {len(groups)}")
on_view = other = with_mods = 0
for me_, obs_ in groups.items():
    view = bpy.data.meshes.get(me_.get("rb_view", "")) or me_
    for o in obs_:
        on_view += o.data == view
        other += o.data != view
        with_mods += bool(o.modifiers)
print(f"VERIFY links: meshes {len(groups)}, objects on the viewport copy {on_view}, on another mesh {other}, "
      f"with modifiers {with_mods}, copies {sum(1 for m in bpy.data.meshes if m.get('rb_original'))}")
for me, obs_ in groups.items():
    ob = obs_[0]
    orig = originals.get(me.name)
    if orig is None:
        print(f"VERIFY {ob.name}: original mesh untouched: False (mesh {me.name!r} not in the import)")
        continue
    nv, nf = len(me.vertices), len(me.polygons)
    co_me = arr(me.vertices, "co", nv)
    same_topo = (len(orig.vertices), len(orig.edges), nf) == (nv, len(me.edges), len(orig.polygons)) and \
        np.array_equal(arr(orig.edges, "vertices", len(orig.edges), 2, np.int64),
                       arr(me.edges, "vertices", len(me.edges), 2, np.int64))
    moved = None
    if same_topo:
        moved = float(np.sqrt(((arr(orig.vertices, "co", nv) - co_me) ** 2).sum(1)).max()) if nv else 0.0
    print(f"VERIFY {ob.name}: original mesh untouched: {same_topo and moved == 0.0} "
          f"(verts {len(orig.vertices)}/{nv}, faces {len(orig.polygons)}/{nf}, max move {moved})")

    # corner normals: with subdivision off the part must look like the import
    if same_topo and len(orig.loops) == len(me.loops):
        a = arr(orig.corner_normals, "vector", len(orig.loops)); b = arr(me.corner_normals, "vector", len(me.loops))
        nn = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
        # a zero normal (degenerate face) counts as 0 deg, like Vector.angle(..., 0.0) in the loop version
        c = np.where(nn > 1e-12, np.clip((a * b).sum(1) / np.maximum(nn, 1e-30), -1, 1), 1.0)
        nd = float(np.degrees(np.arccos(c)).max()) if len(c) else 0.0
        print(f"VERIFY {ob.name}: mesh normals vs import max diff = {round(nd, 4)} deg over {nf} unchanged faces; "
              f"0 repaired faces")
    else:
        co, cm = corners_slow(orig), corners_slow(me)
        nd, matched = 0.0, 0
        for key, (p, d) in cm.items():
            if key in co:
                matched += 1
                od = co[key][1]
                nd = max(nd, max(math.degrees(d[k].angle(od[k], 0.0)) for k in d))
        print(f"VERIFY {ob.name}: mesh normals vs import max diff = {round(nd, 4)} deg over {matched} unchanged faces; "
              f"{sum(1 for k in cm if k not in co)} changed faces (topology differs)")

    # the subdivided result: the render copy (baked, no evaluation needed)
    ev = bpy.data.meshes.get(me.get("rb_render", "")) or bpy.data.meshes.get(me.get("rb_view", ""))
    if ev is None:
        print(f"VERIFY   no subdivided copy of {me.name}")
        continue

    def count(att):
        if att is None:
            return 0
        v = np.empty(len(att.data), bool); att.data.foreach_get("value", v)
        return int(v.sum())
    print(f"VERIFY   copy {ev.name!r} level {ev.get('rb_level')} variant {ev.get('rb_variant')} faces {nf} -> {len(ev.polygons)}, "
          f"flat-flagged={count(ev.attributes.get('sharp_face'))}, sharp_edges={count(ev.attributes.get('sharp_edge'))}, "
          f"custom_normals={ev.has_custom_normals}")

    # flipped: a child face pointing more than 90 deg away from its original face
    level = int(ev.get("rb_level", LEVELS_GUESS))
    starts = np.concatenate(([0], np.cumsum(arr(me.polygons, "loop_total", nf, 1, np.int64) * 4 ** (level - 1))))
    mapped = bool(starts[-1] == len(ev.polygons))
    flips = degenerate = 0
    if mapped and nf:
        m_ = len(ev.polygons)
        owner = np.repeat(np.arange(nf), np.diff(starts))
        on = arr(me.polygons, "normal", nf); oa = arr(me.polygons, "area", nf, 1)
        en = arr(ev.polygons, "normal", m_); ea = arr(ev.polygons, "area", m_, 1)
        bad = np.zeros(nf, bool)
        np.logical_or.at(bad, owner, (ea > 1e-12) & ((en * on[owner]).sum(1) < 0.0))
        for fi in np.nonzero(bad)[0].tolist():   # broken faces of the import (K11) do not count
            if oa[fi] > 1e-8 and not self_intersecting([Vector(co_me[i]) for i in me.polygons[fi].vertices]):
                flips += 1
            else:
                degenerate += 1
    print(f"VERIFY   level={level} mapped={mapped} faces with flipped children={flips} "
          f"(broken faces of the import skipped: {degenerate})")

    if ev.get("rb_method") == "weld":
        # rules 3.0: welding renumbers vertices and edges, the index mapping below does not
        # apply; seams are welded, the only possible gaps are the pinned T points (exact)
        g = CORE.weld_gap(me, ev)
        print("VERIFY   outline deviation: weld copy (see verify_generic for the deviation)")
        print(f"VERIFY   seam gaps: pairs={len(ev.get('rb_tv', [])) // 2} max={g:.4f} p99={g:.4f} >0.01: {int(g > 0.01)} >0.05: {int(g > 0.05)}")
        print(f"VERIFY   seam gaps along edges: pairs=0 max={g:.4f} at None  >0.01: {int(g > 0.01)}")
        print(f"VERIFY   off: original {me.name!r} faces={nf} custom_normals={me.has_custom_normals}")
        continue

    # outline: distance of subdivided open-edge midpoints to the original open edges
    ev_co = arr(ev.vertices, "co", len(ev.vertices))
    b_ids, b_vs = boundary_edges(me)
    if not len(b_ids):
        print("VERIFY   outline deviation: closed mesh, no open edges")
    else:
        _, s_vs = boundary_edges(ev)
        # parent of a subdivided open edge: the original edge of its edge point (the
        # subdivided mesh stores 2^L-1 points per original edge after the original vertices)
        inner_ = 2 ** level - 1; ne = len(me.edges)
        is_ep = lambda v: (v >= nv) & (v < nv + inner_ * ne)
        ep = np.where(is_ep(s_vs[:, 0]), s_vs[:, 0], s_vs[:, 1])
        pos = np.full(ne, -1); pos[b_ids] = np.arange(len(b_ids))
        parent = np.where(is_ep(ep), pos[np.clip((ep - nv) // max(inner_, 1), 0, ne - 1)], -1)
        mids = (ev_co[s_vs[:, 0]] + ev_co[s_vs[:, 1]]) / 2
        A_, B_ = co_me[b_vs[:, 0]], co_me[b_vs[:, 1]]
        ok = parent >= 0
        ds = np.empty(len(mids))
        ds[ok] = seg_dist_min(mids[ok], A_, B_, parent[ok])
        for i in np.nonzero(~ok)[0].tolist():         # no parent found: all segments
            ds[i] = float(seg_dist(mids[i], A_, B_).min())
        size = max(ob.dimensions) or 1
        print(f"VERIFY   outline deviation: max={ds.max():.4f} p99={np.percentile(ds, 99):.4f} median={np.median(ds):.5f} "
              f"(part size {size:.2f}; >0.1: {(ds > 0.1).sum()} edges)")

    # seams: coincident original boundary vertices on different islands must stay together
    bverts = np.unique(b_vs) if len(b_ids) else np.array([], np.int64)
    buckets = defaultdict(list)
    for vi, key in zip(bverts.tolist(), map(tuple, np.round(co_me[bverts], 4).tolist())):
        buckets[key].append(vi)
    gaps = []
    for ids in buckets.values():
        if len(ids) > 1:
            pts = ev_co[ids]
            gaps.append(float(np.sqrt(((pts[:, None] - pts[None]) ** 2).sum(2)).max()))
    if gaps:
        g = np.array(gaps)
        print(f"VERIFY   seam gaps: pairs={len(g)} max={g.max():.4f} p99={np.percentile(g, 99):.4f} "
              f">0.01: {(g > 0.01).sum()} >0.05: {(g > 0.05).sum()}")

    # seams along the edges (exact): open edges of the original that share both end
    # positions are partners; the subdivided mesh stores 2^L-1 points per original
    # edge right after the original vertices (edge order), compare them
    inner = 2 ** level - 1
    partners = defaultdict(list)
    if len(b_ids):
        ra = map(tuple, np.round(co_me[b_vs[:, 0]], 4).tolist())
        rb = map(tuple, np.round(co_me[b_vs[:, 1]], 4).tolist())
        for ei, a, b in zip(b_ids.tolist(), ra, rb):
            partners[frozenset((a, b))].append((ei, a))
    worst, n_bad, where, pairs = 0.0, 0, None, 0
    for es in partners.values():
        if len(es) < 2:
            continue
        pairs += 1
        ref_i, ref_a = es[0]
        ref = ev_co[nv + inner * ref_i: nv + inner * ref_i + inner]
        for ei, ea in es[1:]:
            pts = ev_co[nv + inner * ei: nv + inner * ei + inner]
            if ea != ref_a:
                pts = pts[::-1]
            d = float(np.sqrt(((ref - pts) ** 2).sum(1)).max())
            if d > worst:
                worst, where = d, tuple(round(float(c), 2) for c in ref[inner // 2])
            n_bad += d > 0.01
    print(f"VERIFY   seam gaps along edges: pairs={pairs} max={worst:.4f} at {where}  >0.01: {n_bad}")
    # subdivision off = the original itself (the links point back to it)
    print(f"VERIFY   off: original {me.name!r} faces={nf} custom_normals={me.has_custom_normals}")
