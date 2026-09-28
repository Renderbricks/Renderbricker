"""Verification that works for every variant (rules 2.x and the weld prototype, run 48c).

blender -b <build.blend> --factory-startup --python verify_generic.py -- <import.blend> [--no-gaps]

Per original mesh (objects grouped by the original behind their mesh):
  untouched   original equal to the import (vertex positions, face count)
  links       objects on the copy, objects with modifiers
  folds       sub-faces of the render copy flipped against their original face (face order
              of the copy follows the original - also after welding, which keeps all faces)
  gaps        open edges of the copy: distance of each open vertex to the nearest open edge
              of ANOTHER open loop, counted when 0.0005 < d < GAP_NEAR and the nearest open
              vertex of the original there has a coincident partner and the other open edge
              runs parallel to v's loop (a seam that opened; open edges close together by
              design, e.g. relief walls, and side edges leaving a seam corner are ignored)
  deviation   distance of every copy vertex to the original surface: max, p99, and the
              share of the part size
Prints: VG '<original>' {...}  and at the end VGTOTAL {...}
"""
import bpy, sys, math, importlib.util
import numpy as np
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

A = sys.argv[sys.argv.index("--") + 1:]
IMPORT = A[0]
NO_GAPS = "--no-gaps" in A
DEBUG = "--debug" in A
GAP_NEAR = 1.0
sp = importlib.util.spec_from_file_location(
    "rbcore", __file__.replace("verify_generic.py", "mecabricks_subdiv.py"))
c = importlib.util.module_from_spec(sp); sp.loader.exec_module(c)

users = {}
for o in bpy.data.objects:
    if o.type == 'MESH' and o.data.polygons:
        users.setdefault(c.original_of(o.data), []).append(o)
names = [m.name for m in users]
with bpy.data.libraries.load(IMPORT) as (src, dst):
    avail = set(src.meshes)
    dst.meshes = [n for n in names if n in avail]
imported = {n: m for n, m in zip([n for n in names if n in avail], dst.meshes)}
print(f"MESHES {len(users)}", flush=True)


def arr(coll, attr, n, width):
    a = np.empty(n * width, np.float64 if attr in ("co", "normal") else np.int64)
    coll.foreach_get(attr, a)
    return a.reshape(-1, width) if width > 1 else a


def open_gaps(orig, cp):
    nv, ne = len(cp.vertices), len(cp.edges)
    if not ne:
        return 0, 0.0
    ev = arr(cp.edges, "vertices", ne, 2)
    le = arr(cp.loops, "edge_index", len(cp.loops), 1)
    cnt = np.bincount(le, minlength=ne)
    be = ev[cnt == 1]
    if not len(be):
        return 0, 0.0
    parent = {}
    def find(x):
        r = x
        while parent.get(r, r) != r:
            r = parent[r]
        while parent.get(x, x) != r:
            parent[x], x = r, parent[x]
        return r
    for a, b in be.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    co = arr(cp.vertices, "co", nv, 3)
    bverts = np.unique(be)
    loop_of = {v: find(v) for v in bverts.tolist()}
    kd = kdtree.KDTree(len(bverts))
    for i, v in enumerate(bverts.tolist()):
        kd.insert(co[v], v)
    kd.balance()
    inc = {}
    for k, (a, b) in enumerate(be.tolist()):
        inc.setdefault(a, []).append(k); inc.setdefault(b, []).append(k)
    # seam points of the original: open vertices with a coincident open partner
    oc = arr(orig.vertices, "co", len(orig.vertices), 3)
    oev = arr(orig.edges, "vertices", len(orig.edges), 2)
    ole = arr(orig.loops, "edge_index", len(orig.loops), 1)
    ob = np.unique(oev[np.bincount(ole, minlength=len(orig.edges)) == 1])
    keys = [tuple(np.round(oc[v], 4)) for v in ob.tolist()]
    from collections import Counter
    kc = Counter(keys)
    okd = kdtree.KDTree(len(ob))
    for v, k in zip(ob.tolist(), keys):
        okd.insert(oc[v], 1 if kc[k] > 1 else 0)
    okd.balance()
    n, worst = 0, 0.0
    for v in bverts.tolist():
        if not len(ob) or okd.find(co[v])[1] != 1:      # not on a seam of the original
            continue
        lv = loop_of[v]
        # tangent of v's own open loop (its two open edges)
        own = [be[k] for k in inc[v]]
        tv_ = sum((co[e[1]] - co[e[0]]) * (1 if e[0] == v else -1 if e[1] == v else 0) for e in own[:1])
        if len(own) > 1:
            e = own[1]; tv_ = tv_ - (co[e[1]] - co[e[0]]) * (1 if e[0] == v else -1)
        nt = float(np.linalg.norm(tv_))
        best = None
        for _, w, d in kd.find_range(co[v], GAP_NEAR):
            if loop_of[w] == lv:
                continue
            for k in inc[w]:
                a, b = co[be[k, 0]], co[be[k, 1]]
                ab = b - a
                la = float(np.linalg.norm(ab))
                # a seam runs along: the other edge parallel to v's loop (not a side edge
                # leaving the seam at a corner, nostril slits of 10509a4)
                if nt < 1e-12 or la < 1e-12 or abs(float(np.dot(tv_, ab))) / (nt * la) < 0.9:
                    continue
                t = min(1.0, max(0.0, float(np.dot(co[v] - a, ab) / max(np.dot(ab, ab), 1e-18))))
                dd = float(np.linalg.norm(a + ab * t - co[v]))
                best = dd if best is None else min(best, dd)
        if best is not None and 0.0005 < best < GAP_NEAR:
            n += 1; worst = max(worst, best)
            if best == worst and DEBUG: print("GAPAT", orig.name, tuple(round(x, 3) for x in co[v]), round(best, 4))
    return n, worst


def deviation(orig, cp):
    oc = arr(orig.vertices, "co", len(orig.vertices), 3)
    polys = [tuple(p.vertices) for p in orig.polygons]
    bvh = BVHTree.FromPolygons([Vector(x) for x in oc], polys, all_triangles=False, epsilon=0.0)
    cc = arr(cp.vertices, "co", len(cp.vertices), 3)
    # only vertices of faces: loose vertices of the import (6587, 61780: pivot/bbox points without
    # a face) are copied as they are and measured against no surface (run 57: false 0.76 / 1.10)
    used = np.unique(arr(cp.polygons, "vertices", len(cp.loops), 1).ravel()) if len(cp.loops) else np.zeros(0, int)
    cc = cc[used.astype(int)] if len(used) else cc
    d = np.array([bvh.find_nearest(Vector(x))[3] or 0.0 for x in cc])
    size = float(np.linalg.norm(oc.max(0) - oc.min(0))) if len(oc) else 1.0
    return float(d.max()) if len(d) else 0.0, float(np.percentile(d, 99)) if len(d) else 0.0, size


tot = dict(meshes=0, changed=0, folds=0, gap_meshes=0, gap_max=0.0, dev_max=0.0, bad_links=0)
for orig, obs in users.items():
    rep = {}
    im = imported.get(orig.name)
    if im is None:
        rep["untouched"] = None
    else:
        same = len(im.vertices) == len(orig.vertices) and len(im.polygons) == len(orig.polygons)
        if same:
            a = arr(im.vertices, "co", len(im.vertices), 3); b = arr(orig.vertices, "co", len(orig.vertices), 3)
            same = float(np.abs(a - b).max()) < 1e-6 if len(a) else True
        rep["untouched"] = same
    name = orig.get("rb_render") or orig.get("rb_view") or ""
    cp = bpy.data.meshes.get(name)
    rep["on_copy"] = sum(1 for o in obs if o.data.get("rb_original") == orig.name)
    rep["objects"] = len(obs)
    rep["with_modifiers"] = sum(1 for o in obs if len(o.modifiers))
    if cp is None:
        rep["copy"] = None
    else:
        c.LEVELS = int(cp.get("rb_level", 2))
        try:
            rep["folds"] = len(c.flipped_faces(None, ev=cp, me=orig))
        except AssertionError:
            rep["folds"] = -1                     # face mapping does not fit
        if not NO_GAPS:
            rep["gaps"], g = open_gaps(orig, cp)
            rep["gap_max"] = round(g, 4)
        dm, dp, size = deviation(orig, cp)
        rep["dev_max"], rep["dev_p99"], rep["size"] = round(dm, 4), round(dp, 4), round(size, 2)
    print(f"VG {orig.name!r} {rep}", flush=True)
    tot["meshes"] += 1
    tot["changed"] += rep["untouched"] is False
    tot["folds"] += max(0, rep.get("folds", 0))
    tot["gap_meshes"] += rep.get("gaps", 0) > 0
    tot["gap_max"] = max(tot["gap_max"], rep.get("gap_max", 0.0))
    tot["dev_max"] = max(tot["dev_max"], rep.get("dev_max", 0.0))
    tot["bad_links"] += (rep["on_copy"] != rep["objects"]) + rep["with_modifiers"]
print(f"VGTOTAL {tot}", flush=True)
