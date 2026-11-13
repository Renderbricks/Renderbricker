"""W24 - touching pieces (rules 3.16, UPDATES #67; designed in run 303, fit.py stage 3 and cage_rest).

A part whose pieces only touch in the import (89678: the bead round the mantle, the ribs under it; the crab's stud
on its body) opens slits there in the smooth copy: the piece touched rounds away between its own points, and the
shrink compensation alone does not close them (run 303, finding 7: 0.2176 mm left on 89678). Maintainer 2026-11-12:
at level 2 no gaps may appear.

    find   the shells of the cage (connected pieces) and its contacts: every point that lies on another shell in the
           import - within CONTACT, a point of an open rim within CONTACT_RIM (the import's own rims lie up to
           0.063 mm off the shell they rest on: 89678, the mantle's rim under the bead) - with every shell it
           touches; where the face touched is flat, its plane (for batches; a direct run does not use it)
    close  rounds on the smooth surface at level 2: a contact point with a slit to a shell it touched moves
           CONTACT_STEP x the way to the nearest point of that shell's smooth surface (of several shells towards
           the widest slit), never further than MAX_MOVE from the import in all; ends when no slit is wider than
           SLIT_MIN
    gaps   the gap measure of a copy (resting rims, points that share a place, contact slits) - the measure of the
           test shrink_fit

Slit: the distance to the nearest point of the shell touched, unless the point lies behind that shell - more than
BESIDE x its distance behind every face that shares the nearest point (a nearest point on an edge or a corner: all
faces at it). A nearest point on the shell's open rim is beside it, a slit. 89678's rib corner at 2.3 / 0.5 / 0.8:
its nearest point lies on an edge between two faces of the body, and with the normal of the one face the tree gave
the prototype took it for behind and left 0.044 mm, its mirror twin closed.

Read only except close, which moves the points of the cage it is given.
"""
import numpy as np
from mathutils.bvhtree import BVHTree

from . import cagegeom, config, workscene

CONTACT = 1e-3              # mm: a point this close to another shell in the import touches it
CONTACT_RIM = 0.08          # mm: a point of an open rim touches from this far
ASK = 0.5                   # mm: the tree is asked this wide and cut by the distance (asked with the reach itself it
                            # missed one of the two mirrored corners of 89678's rib)
REST = 1e-4                 # mm: a shell rests when every point of its open rim lies this close to another shell
BESIDE = 0.3                # a point is behind the shell touched only when it lies this share of its distance behind it
RIM_TOL = 1e-6              # a nearest point this close to an edge lies on it - mm x max(1, its largest coordinate):
                            # the BVH works in float32, about 1e-6 mm at 8 mm already (review of Task 6)
CONTACT_ROUNDS = 6          # subdivide at level 2, measure, move - at most
CONTACT_STEP = 1.3          # share of the way to the nearest point moved per round
SLIT_MIN = 1e-4             # mm: a slit this narrow is closed
LEVEL = 2                   # the smooth surface the slits are measured on (maintainer 2026-11-12: level 2 is the reference)
MAX_MOVE = 0.3              # mm: no point further than this from the import in all (= shrink.SHRINK_MAX)
MOVED = 1e-5                # mm: a point moved this far counts as moved
CONE = True                 # behind only behind every face that shares the nearest point (the normal cone)
ASK_EDGE = 1e-3             # mm: the faces at the nearest point - asked this wide, cut at _tol


def _faces(T):
    """The faces of the cage as lists of point numbers."""
    return [f.tolist() for f in np.split(T["lv"], T["ls"][1:])] if T["nf"] else []


def find(wm, T, flat):
    """The contacts of the cage `wm` at its places in `T` (cagegeom.arrays, before any move); `flat` (nf) bool the
    flat faces (cagegeom.flat_faces). Returns a dict: lab (n) the shell of every point (its smallest point number),
    contacts (m,2) int (point, shell touched) - one row per shell a point touches, plane (m,4) the touched face's
    plane (normal, normal . point on it) where that face is flat, else nan, resting the shells whose open rim rests
    on another shell (every rim point within REST). Empty at once when the cage has one shell."""
    n, co, ev = T["n"], T["co"], T["ev"]
    lab = cagegeom._components(n, ev[:, 0], ev[:, 1]) if len(ev) else np.arange(n)
    out = {"lab": lab, "contacts": np.zeros((0, 2), np.int64), "plane": np.zeros((0, 4)), "resting": []}
    shells, sid = np.unique(lab, return_inverse=True)
    if len(shells) < 2 or not T["nf"]:
        return out
    rim = np.zeros(n, bool)
    rim[ev[T["efaces"] == 1].ravel()] = True
    reach = np.where(rim, CONTACT_RIM, CONTACT)
    # a point can only touch a shell whose box (grown by its reach) holds it - the boxes sort out the rest
    lo = np.full((len(shells), 3), np.inf)
    hi = np.full((len(shells), 3), -np.inf)
    np.minimum.at(lo, sid, co)
    np.maximum.at(hi, sid, co)
    cand = np.zeros(n, bool)
    # per shell only the points in its slab along x (Task 7: every point against every box cost 1.5 s on a mesh of
    # 35,218 faces) - the same test on them
    by_x = np.argsort(co[:, 0], kind="stable")
    xs = co[by_x, 0]
    wide = float(reach.max())
    for s in range(len(shells)):
        v = by_x[np.searchsorted(xs, lo[s, 0] - wide, "left"):np.searchsorted(xs, hi[s, 0] + wide, "right")]
        r = reach[v][:, None]
        inside = np.all((co[v] >= lo[s] - r) & (co[v] <= hi[s] + r), axis=1)
        cand[v[inside & (sid[v] != s)]] = True
    if not cand.any():
        return out
    tree = BVHTree.FromPolygons(co.tolist(), _faces(T))
    fshell = lab[T["lv"][T["ls"]]]
    rows, planes = [], []
    rests = {}
    fshell_l, lab_l, reach_l = fshell.tolist(), lab.tolist(), reach.tolist()     # Python numbers in the loop (Task 7)
    for v in np.nonzero(cand)[0].tolist():
        best = {}                                   # shell touched -> (distance, nearest face)
        own, rv = lab_l[v], reach_l[v]
        for f, dist in [(h[2], h[3]) for h in tree.find_nearest_range(co[v].tolist(), ASK) if h[3] <= rv]:
            s = fshell_l[f]
            if s != own and (s not in best or dist < best[s][0]):
                best[s] = (dist, f)
        if rim[v]:
            rests[v] = any(dd <= REST for dd, _f in best.values())
        for s in sorted(best):
            f = best[s][1]
            rows.append((v, s))
            if flat[f]:
                nrm = T["fn"][f]
                planes.append((nrm[0], nrm[1], nrm[2], float(nrm @ co[T["lv"][T["ls"][f]]])))
            else:
                planes.append((np.nan, np.nan, np.nan, np.nan))
    rim_pts = np.nonzero(rim)[0]
    ok = np.array([rests.get(int(v), False) for v in rim_pts], bool)
    if len(rim_pts):
        bad = np.unique(lab[rim_pts[~ok]])
        out["resting"] = sorted(int(s) for s in np.unique(lab[rim_pts]) if s not in set(bad.tolist()))
    if rows:
        out["contacts"] = np.array(rows, np.int64)
        out["plane"] = np.array(planes, np.float64)
    return out


def _evaluate(work, level, topology, quality=None):
    """The points of the smooth surface of `work` at `level` (limit surface on); with `topology` also its quads, its
    edges and the number of faces per edge."""
    mod = work.modifiers["Subdivision"]
    keep, keep_q, keep_uv = mod.levels, mod.quality, mod.uv_smooth
    mod.levels = level
    if quality is not None:
        mod.quality = quality
    if config.REPARAM:
        # as copies.bake_copy (W14c: linear UVs) - the bake that follows finds the subdivision built here (Task 7:
        # with smoothed UVs it was built twice); the points agree with those of smoothed UVs to float rounding
        # (2e-6 mm at most on run 303's 16 parts), and they are the ones the bake makes
        mod.uv_smooth = 'NONE'
    try:
        dg = workscene.depsgraph_of(work)
        dg.update()
        ev = work.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            co = np.zeros(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            topo = None
            if topology:
                lv = np.zeros(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
                le = np.zeros(len(me.loops), np.int64); me.loops.foreach_get("edge_index", le)
                e2 = np.zeros(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", e2)
                topo = (lv.reshape(-1, 4), e2.reshape(-1, 2), np.bincount(le, minlength=len(me.edges)))
        finally:
            ev.to_mesh_clear()
    finally:
        mod.levels, mod.quality, mod.uv_smooth = keep, keep_q, keep_uv
    return co.reshape(-1, 3), topo


def _on_segments(p, a, b):
    """Distance of the point p to the nearest of the segments a-b (k,3)."""
    ab = b - a
    t = np.clip(((p - a) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-30), 0.0, 1.0)
    return float(np.linalg.norm(a + ab * t[:, None] - p, axis=1).min()) if len(a) else np.inf


def _tol(loc):
    """RIM_TOL at the place `loc`: relative to its largest coordinate from 1 mm on."""
    return RIM_TOL * max(1.0, float(np.abs(loc).max()))


def _behind(tree, p, loc, nrm, dist):
    """Whether the point `p` lies behind the shell of `tree` whose nearest point to it is `loc` (normal `nrm` of the
    face the tree gave, distance `dist`): behind every face whose closure holds the nearest point - on an edge or a
    corner all faces that share it (the normal cone; with one face of them the tree's choice decided, 89678's rib
    corner at 2.3 / 0.5 / 0.8 was behind and its mirror twin beside). More than BESIDE x its distance behind."""
    if float((p - loc) @ nrm) > -BESIDE * dist:
        return False
    if not CONE:
        return True
    for _l, n_f, _f, d_f in tree.find_nearest_range(loc.tolist(), ASK_EDGE):
        if d_f <= _tol(loc) and float((p - loc) @ np.array(n_f)) > -BESIDE * dist:
            return False
    return True


def _behind_cone(tree, p, loc, dist):
    """_behind's normal cone for a point already behind the face the tree gave: behind every face that shares the
    nearest point `loc`."""
    for _l, n_f, _f, d_f in tree.find_nearest_range(loc.tolist(), ASK_EDGE):
        if d_f <= _tol(loc) and float((p - loc) @ np.array(n_f)) > -BESIDE * dist:
            return False
    return True


def _to_segments(p, a, b, chunk=2_000_000):
    """_on_segments for many points p (k,3) at once: the distance of each to the nearest of the segments a-b."""
    ab = b - a
    ab2 = np.maximum((ab * ab).sum(axis=1), 1e-30)
    out = np.empty(len(p))
    step = max(1, chunk // max(1, len(a)))
    for s in range(0, len(p), step):
        q = p[s:s + step, None, :]
        t = np.clip(((q - a) * ab).sum(axis=2) / ab2, 0.0, 1.0)
        out[s:s + step] = np.linalg.norm(a + ab * t[:, :, None] - q, axis=2).min(axis=1)
    return out


def _tols(loc):
    """_tol for many places (k,3)."""
    return RIM_TOL * np.maximum(1.0, np.abs(loc).max(axis=1))


def _groups(keys, items):
    """`items` grouped by their sorted `keys`: (the keys, a list of the items of each)."""
    if not len(keys):
        return [], []
    cut = np.nonzero(np.diff(keys))[0] + 1
    return keys[np.r_[0, cut]].tolist(), np.split(items, cut)


def _shell_parts(co2, topo, shells):
    """Per shell of `shells` in the smooth copy (points `co2`, `topo` of _evaluate): its points, its quads in the
    numbers of those points (in the copy's order) and its open rim edges (in the copy's numbers)."""
    quads, e2, efaces = topo
    lab2 = cagegeom._components(len(co2), e2[:, 0], e2[:, 1])
    qshell = lab2[quads[:, 0]]
    open_e = e2[efaces == 1]
    order = np.argsort(qshell, kind="stable")
    qs = qshell[order]
    eorder = np.argsort(lab2[open_e[:, 0]], kind="stable")
    es = lab2[open_e[:, 0]][eorder]
    vorder = np.argsort(lab2, kind="stable")    # the points by shell, in their order
    vl = lab2[vorder]
    rank = np.empty(len(lab2), np.int64)        # every point's number within its shell
    rank[vorder] = np.arange(len(vl)) - np.searchsorted(vl, vl, "left")
    out = {}
    for s in shells:
        sel = quads[order[np.searchsorted(qs, s):np.searchsorted(qs, s, "right")]]
        out[s] = (vorder[np.searchsorted(vl, s):np.searchsorted(vl, s, "right")], rank[sel].tolist(),
                  open_e[eorder[np.searchsorted(es, s):np.searchsorted(es, s, "right")]])
    return out


def close(work, wm, K, free, q, d, quality=None):
    """W24 on the cage `wm` of `work`, which stands at q + d (q the import's places, d the moves so far). `K`: find's
    dict; `free`: points left as they are (W17). Rounds: the smooth surface at LEVEL; every contact point with a slit
    wider than SLIT_MIN moves CONTACT_STEP x the way to the nearest point of the shell touched, of several shells
    towards the widest slit; no point further than MAX_MOVE from q in all. Every contact is measured on the smooth
    surface (ruling 13.11.2026: no plane targets in a direct run - near the edge of a flat face its smooth surface
    rounds away from the plane, 89678's rib feet kept 0.027 mm; find's planes are for batches). Leaves the cage at
    q + the moves. Returns (the moves (n,3), points moved by the contacts, largest slit left)."""
    HISTORY.clear()
    d = np.asarray(d, np.float64).copy()
    rows = np.asarray(K["contacts"], np.int64).reshape(-1, 2)
    freeset = np.asarray(sorted(int(v) for v in free), np.int64)
    rows = rows[~np.isin(rows[:, 0], freeset)]
    if not len(rows) or work.modifiers.get("Subdivision") is None:
        return d, 0, 0.0
    n = len(q)
    shells = sorted(set(rows[:, 1].tolist()))
    dc = np.zeros((n, 3))
    left = 0.0
    by_shell = {}                               # shell touched -> its rows (in row order)
    order = np.argsort(rows[:, 1], kind="stable")
    for s, part in zip(*_groups(rows[:, 1][order], order), strict=True):
        by_shell[s] = part.tolist()
    own = np.asarray(K["lab"])[rows[:, 0]]       # the shell of every row's point
    per = None
    slit = np.zeros(len(rows))
    target = np.zeros((len(rows), 3))
    dirty = None                                # the shells whose points moved in the last round (None: all)
    was = (q + d).astype(np.float32)            # the cage as it stands
    for round_ in range(CONTACT_ROUNDS + 1):
        co2, topo = _evaluate(work, LEVEL, topology=per is None, quality=quality)
        if topo is not None:                    # the copy's shells: its first points are the cage's
            per = _shell_parts(co2, topo, shells)
        p = co2[rows[:, 0]]
        # a row neither of whose two shells moved keeps its measure: the smooth surface of a shell depends on its own
        # points only (Task 7: the same numbers, a second measure of every row cost a second on a plate 6 x 16)
        again = np.ones(len(rows), bool) if dirty is None else np.isin(own, dirty) | np.isin(rows[:, 1], dirty)
        slit[again] = 0.0
        target[again] = p[again]
        for s in shells:
            pts, faces, seg = per[s]
            todo = [i for i in by_shell[s] if again[i]]
            if not len(pts) or not todo:
                continue
            # the shell's own points only (Task 7: the whole copy per shell and round cost 13 s on a mesh of 35,218
            # faces with 97 shells touched) - the same faces in the same order, the same tree
            tree = BVHTree.FromPolygons(co2[pts].tolist(), faces)
            a, b = co2[seg[:, 0]], co2[seg[:, 1]]
            # the rows of the shell at once (Task 7: per row in Python it cost as much as the subdivisions) - the
            # measure of _behind and _on_segments, the same numbers
            pp = p[todo]
            hits = [tree.find_nearest(x) for x in pp.tolist()]
            got = [k for k, h in enumerate(hits) if h[0] is not None]
            if not got:
                continue
            rows_s = np.asarray(todo, np.int64)[got]
            pp = pp[got]
            loc = np.array([hits[k][0] for k in got], np.float64)
            nrm = np.array([hits[k][1] for k in got], np.float64)
            dist = np.array([hits[k][3] for k in got], np.float64)
            behind = np.einsum("ij,ij->i", pp - loc, nrm) <= -BESIDE * dist
            if CONE:
                for k in np.nonzero(behind)[0].tolist():
                    behind[k] = _behind_cone(tree, pp[k], loc[k], dist[k])
            if len(seg) and behind.any():       # the nearest point on the shell's open rim: beside it, a slit
                k = np.nonzero(behind)[0]
                behind[k[_to_segments(loc[k], a, b) <= _tols(loc[k])]] = False
            slit[rows_s] = np.where(behind, 0.0, dist)
            target[rows_s] = loc
        left = float(slit.max())
        HISTORY.append((round(left, 5), int((slit > 0.005).sum())))
        if round_ == CONTACT_ROUNDS or not (slit > SLIT_MIN).any():
            break
        step, widest = np.zeros((n, 3)), np.zeros(n)
        for i in np.nonzero(slit > SLIT_MIN)[0].tolist():
            v = rows[i, 0]
            if slit[i] > widest[v]:             # of several shells touched: towards the widest slit
                step[v], widest[v] = target[i] - p[i], slit[i]
        x = d + dc + CONTACT_STEP * step
        far = np.linalg.norm(x, axis=1)
        x *= np.minimum(1.0, MAX_MOVE / np.maximum(far, 1e-12))[:, None]
        new = x - d
        now = (q + d + new).astype(np.float32)
        changed = np.any(now != was, axis=1)    # the cage points that changed
        if not changed.any():
            break                               # every point with a slit stands at MAX_MOVE: the next measure is this
        dc = new
        dirty = np.unique(np.asarray(K["lab"])[changed])
        was = now
        wm.vertices.foreach_set("co", now.ravel())
        wm.update()
    return d + dc, int((np.linalg.norm(dc, axis=1) > MOVED).sum()), round(left, 5)


HISTORY = []                # (largest slit, slits over 0.005) per round of the last close call - read by the tests


def _copy_shells(cage_lab, cp):
    """The points of a copy and their shells: its first points are the cage's (the subdivision keeps their numbers)."""
    n = len(cage_lab)
    co = np.array([v.co[:] for v in cp.vertices])
    e2 = np.array([e.vertices[:] for e in cp.edges], np.int64).reshape(-1, 2)
    lab = np.arange(len(co))
    lab[:n] = cage_lab
    lab[n:] = len(co) + np.arange(len(co) - n)
    while True:
        m = np.minimum(lab[e2[:, 0]], lab[e2[:, 1]])
        new = lab.copy(); np.minimum.at(new, e2[:, 0], m); np.minimum.at(new, e2[:, 1], m)
        if np.array_equal(new, lab):
            break
        lab = new
    return co, lab


def gaps(cage, cp):
    """Gaps of a copy `cp` (maintainer 2026-11-12: at level 2 no gaps may appear) against `cage` (lab, resting,
    contacts, pairs - the points of different shells at one place in the import): the open rims of the resting
    shells against the shells they rest on (> 0: the rim floats above), how far the pairs lie apart, and the contact
    points against the copy of the shell they touched (in front of it or beside it: a slit of that width; behind it:
    none - the measure of run 303, without the open-rim rule of close)."""
    co, lab = _copy_shells(cage["lab"], cp)
    cnt = {}
    for p in cp.polygons:
        for k in p.edge_keys:
            cnt[k] = cnt.get(k, 0) + 1
    rim = np.array(sorted({v for k, c in cnt.items() if c == 1 for v in k}), np.int64)
    fshell = np.array([lab[p.vertices[0]] for p in cp.polygons])
    out = {"resting_shells": len(cage["resting"]), "rim_points": 0, "rim_gap_max": 0.0, "rim_points_above_0.005": 0}
    dd = []
    for s in cage["resting"]:
        faces = [p.vertices[:] for p, fs in zip(cp.polygons, fshell, strict=True) if fs != s]
        if not faces:
            continue
        tree = BVHTree.FromPolygons(co.tolist(), faces)
        for v in rim[lab[rim] == s]:
            loc, nrm, _i, dist = tree.find_nearest(co[v].tolist())
            if loc is not None and dist < 0.5:
                dd.append(float((co[v] - np.array(loc)) @ np.array(nrm)))
    if dd:
        a = np.array(dd)
        out.update({"rim_points": len(a), "rim_gap_max": round(float(a.max()), 4),
                    "rim_points_above_0.005": int((a > 0.005).sum())})
    out["touching_apart_max"] = 0.0
    pairs = cage.get("pairs", [])
    if len(pairs):
        pr = np.array(pairs)
        out["touching_apart_max"] = round(float(np.linalg.norm(co[pr[:, 0]] - co[pr[:, 1]], axis=1).max()), 5)
    contacts = [(int(v), int(s)) for v, s in cage["contacts"]]
    out["contact_points"] = len(contacts)
    out.update({"slit_max": 0.0, "slit_over_0.005": 0})
    if contacts:
        trees, slit, where = {}, [], []
        for v, s in contacts:
            if s not in trees:
                faces = [p.vertices[:] for p, fs in zip(cp.polygons, fshell, strict=True) if fs == s]
                trees[s] = BVHTree.FromPolygons(co.tolist(), faces) if faces else None
            if trees[s] is None:
                continue
            loc, nrm, _i, dist = trees[s].find_nearest(co[v].tolist())
            if loc is None:
                continue
            side = float((co[v] - np.array(loc)) @ np.array(nrm))
            g = dist if side > -BESIDE * dist else 0.0
            slit.append(g); where.append((round(g, 4), [round(float(x), 2) for x in co[v]]))
        if slit:
            a = np.array(slit)
            where.sort(reverse=True)
            out.update({"slit_max": round(float(a.max()), 4), "slit_over_0.005": int((a > 0.005).sum()),
                        "slit_worst": where[:3]})
    return out
