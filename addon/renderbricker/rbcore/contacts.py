"""W24 - touching pieces (rules 3.16, UPDATES #67; designed in run 303, fit.py stage 3 and cage_rest).

A part whose pieces only touch in the import (89678: the bead round the mantle, the ribs under it; the crab's stud
on its body) opens slits there in the smooth copy: the piece touched rounds away between its own points, and the
shrink compensation alone does not close them (run 303, finding 7: 0.2176 mm left on 89678). Maintainer 2026-11-12:
at level 2 no gaps may appear.

    find   the shells of the cage (connected pieces) and its contacts: every point that lies on another shell in the
           import - within CONTACT, a point of an open rim within CONTACT_RIM (the import's own rims lie up to
           0.063 mm off the shell they rest on: 89678, the mantle's rim under the bead) - with every shell it
           touches, its nearest face there and, where that is flat, its plane (for batches.unit_plan; close does not
           use them)
           - not a joint (W24e) and at a pole one row per place touched (W24d) - and the open edges both of whose
           ends touch one shell and that lie on it in between too (edge_rows, for snap)
    close  rounds on the smooth surface at level 2: a contact point with a slit to a shell it touched moves
           CONTACT_STEP x the way to the nearest point of that shell's smooth surface (of several shells towards
           the widest slit), never further than MAX_MOVE from the import in all, never a point that stays apart
           (W24a) and never off the flat faces it lies on (W24b); ends when no slit is wider than SLIT_MIN
    snap   W26: the seams closed on the baked copy itself - its contact points and the points of the open edges
           between them put on the copy of the shell they touch
    gaps   the gap measure of a copy (resting rims, points that share a place, contact slits) - the measure of the
           test shrink_fit

Slit: the distance to the nearest point of the shell touched, unless the point lies behind that shell - more than
BESIDE x its distance behind every face that shares the nearest point (a nearest point on an edge or a corner: all
faces at it). A nearest point on the shell's open rim is beside it, a slit. 89678's rib corner at 2.3 / 0.5 / 0.8:
its nearest point lies on an edge between two faces of the body, and with the normal of the one face the tree gave
the prototype took it for behind and left 0.044 mm, its mirror twin closed.

Read only except close, which moves the points of the cage it is given, and snap, which moves points of the copy.

Rework of run 306 (13.11.2026; the diagnosis found every hole of rules 3.16 in W24 or in the baked copy, where no
rule looked): W24a - W24e restrain close as W22 / W23 are restrained, W26 measures the copy that is rendered.
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
JOINT_COS = 0.996           # W24e: two flat faces within 5 degrees lie in one plane ...
JOINT_OFF = 0.01            # mm: ... when the point is no further than this off the other's plane
MANY = 8                    # W24d: a point touching more shells than this - they count once per place touched
SNAP_MAX = 0.3              # mm: W26 - a slit of the copy wider than this is left (= MAX_MOVE)
SNAP_TURN = 0.5             # W26: a quad of the copy turns by no more than this cosine (60 degrees) when a point moves
SNAP_HALVES = 3             # W26: ... the point then goes half the way, this often; then it stays
CHORD_ADD = 1.25            # W26b: the ends of an open copy edge go this x the way its middle lacks


def _faces(T):
    """The faces of the cage as lists of point numbers."""
    return [f.tolist() for f in np.split(T["lv"], T["ls"][1:])] if T["nf"] else []


def find(wm, T, flat, planes=None, edges=True):
    """The contacts of the cage `wm` at its places in `T` (cagegeom.arrays, before any move); `flat` (nf) bool the
    flat faces (cagegeom.flat_faces); `planes` the flat planes of every point (cagegeom._flat_planes; None: made
    here). Returns a dict: lab (n) the shell of every point (its smallest point number), contacts (m,2) int (point,
    shell touched) - one row per shell a point touches, face (m) the nearest face of the shell touched, plane (m,4)
    that face's plane (normal, normal . point on it) where it is flat, else nan, resting the shells whose open rim
    rests on another shell (every rim point within REST), edge_rows (k,3) int (open edge, place 0..2, shell) - with
    `edges`: the open edges both of whose ends touch one shell and whose level-2 places 1/4, 1/2, 3/4 lie within
    CONTACT_RIM of it in the import (W26 reads them). Empty at once when the cage has one shell.
      W24e  a row that only the wide reach makes (a rim point further than CONTACT off the shell) is no contact when
            that shell has, within the point's reach, a flat face in the plane of one of the point's own flat faces
            (normals within JOINT_COS, the point within JOINT_OFF of its plane): the two lie side by side with a
            joint between them (con1: an insert in a hole 0.05 mm larger; W24 dragged the hole's outline 0.27 mm
            over it). A rim resting on a surface or standing before it is not in that plane (89678's mantle rim
            0.063 mm under the bead) - no single reach separates the two (0.05 below 0.063)
      W24d  a point touching more than MANY shells (a pole: 20398, 432 shells, 379,260 rows) touches each place once:
            the shells by distance, one dropped whose nearest point lies within CONTACT of one kept"""
    n, co, ev = T["n"], T["co"], T["ev"]
    lab = cagegeom._components(n, ev[:, 0], ev[:, 1]) if len(ev) else np.arange(n)
    out = {"lab": lab, "contacts": np.zeros((0, 2), np.int64), "face": np.zeros(0, np.int64), "plane": np.zeros((0, 4)),
           "resting": [], "edge_rows": np.zeros((0, 3), np.int64)}
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
    n_planes, own_planes = cagegeom._flat_planes(T, flat) if planes is None else planes
    first_of = T["lv"][T["ls"]]                     # a point of every face
    fshell = lab[first_of]
    rows, row_planes, nearest = [], [], []
    rests = {}
    fshell_l, lab_l, reach_l = fshell.tolist(), lab.tolist(), reach.tolist()     # Python numbers in the loop (Task 7)
    for v in np.nonzero(cand)[0].tolist():
        best = {}                                   # shell touched -> (distance, nearest face, nearest place)
        near_faces = []                             # the faces of other shells within the reach: (face, normal)
        own, rv = lab_l[v], reach_l[v]
        for loc, n_f, f, dist in [h for h in tree.find_nearest_range(co[v].tolist(), ASK) if h[3] <= rv]:
            s = fshell_l[f]
            if s != own:
                near_faces.append((f, n_f))
                if s not in best or dist < best[s][0]:
                    best[s] = (dist, f, loc)
        if rim[v]:
            rests[v] = any(b[0] <= REST for b in best.values())
            if n_planes[v]:                         # W24e: a joint is no contact
                for f, n_f in near_faces:
                    s = fshell_l[f]
                    if s in best and best[s][0] > CONTACT and flat[f]:
                        n_f = np.array(n_f)
                        in_plane = any(abs(float(n_f @ own_planes[v, k])) > JOINT_COS
                                       for k in range(min(int(n_planes[v]), 2)))
                        if abs(float((co[v] - co[first_of[f]]) @ n_f)) < JOINT_OFF and in_plane:
                            del best[s]
        if len(best) > MANY:                        # W24d: many shells at one place (a pole) count once per place
            kept = []
            for s in sorted(best, key=lambda s: (best[s][0], s)):
                if all((best[s][2] - best[k][2]).length > CONTACT for k in kept):
                    kept.append(s)
            best = {s: best[s] for s in kept}
        for s in sorted(best):
            f = best[s][1]
            rows.append((v, s))
            nearest.append(f)
            if flat[f]:
                nrm = T["fn"][f]
                row_planes.append((nrm[0], nrm[1], nrm[2], float(nrm @ co[T["lv"][T["ls"][f]]])))
            else:
                row_planes.append((np.nan, np.nan, np.nan, np.nan))
    rim_pts = np.nonzero(rim)[0]
    ok = np.array([rests.get(int(v), False) for v in rim_pts], bool)
    if len(rim_pts):
        bad = np.unique(lab[rim_pts[~ok]])
        out["resting"] = sorted(int(s) for s in np.unique(lab[rim_pts]) if s not in set(bad.tolist()))
    if rows:
        out["contacts"] = np.array(rows, np.int64)
        out["face"] = np.array(nearest, np.int64)
        out["plane"] = np.array(row_planes, np.float64)
        if edges:
            out["edge_rows"] = _edge_rows(T, tree, fshell_l, rows)
    return out


def _edge_rows(T, tree, fshell_l, rows):
    """For W26: the open edges of the cage both of whose ends touch the same shell (`rows` of find) and that lie on
    it in the import between their ends too - at the level-2 places 1/4, 1/2, 3/4, within CONTACT_RIM: rows (edge,
    place 0..2, shell). Without them the seam between two contact points is a chord the copy does not close (61487:
    0.121 mm between two points that had closed)."""
    co, ev = T["co"], T["ev"]
    touch = {}
    for v, s in rows:
        touch.setdefault(v, set()).add(s)
    out = []
    for e in np.nonzero(T["efaces"] == 1)[0].tolist():
        a, b = int(ev[e, 0]), int(ev[e, 1])
        for s in sorted(touch.get(a, set()) & touch.get(b, set())):
            for k in range(3):
                p = co[a] + (co[b] - co[a]) * ((k + 1) / 4.0)
                if any(fshell_l[h[2]] == s for h in tree.find_nearest_range(p.tolist(), CONTACT_RIM)):
                    out.append((e, k, s))
    return np.array(out, np.int64).reshape(-1, 3)


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


def _tol(loc):
    """RIM_TOL at the place `loc`: relative to its largest coordinate from 1 mm on."""
    return RIM_TOL * max(1.0, float(np.abs(loc).max()))


def _behind_cone(tree, p, loc, dist):
    """The normal cone for a point `p` already behind the face the tree gave (nearest point `loc`, distance `dist`):
    behind every face whose closure holds the nearest point - on an edge or a corner all faces that share it (with
    the one face the tree gave its choice decided, 89678's rib corner at 2.3 / 0.5 / 0.8 was behind and its mirror
    twin beside), more than BESIDE x its distance."""
    for _l, n_f, _f, d_f in tree.find_nearest_range(loc.tolist(), ASK_EDGE):
        if d_f <= _tol(loc) and float((p - loc) @ np.array(n_f)) > -BESIDE * dist:
            return False
    return True


def _to_segments(p, a, b, chunk=2_000_000):
    """The distance of each point p (k,3) to the nearest of the segments a-b."""
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


def close(work, wm, K, free, q, d, quality=None, hold=(), planes=None):
    """W24 on the cage `wm` of `work`, which stands at q + d (q the import's places, d the moves so far). `K`: find's
    dict; `free`: points left as they are (W17). Rounds: the smooth surface at LEVEL; every contact point with a slit
    wider than SLIT_MIN moves CONTACT_STEP x the way to the nearest point of the shell touched, of several shells
    towards the widest slit; no point further than MAX_MOVE from q in all. Every contact is measured on the smooth
    surface (ruling 13.11.2026: no plane targets in a direct run - near the edge of a flat face its smooth surface
    rounds away from the plane, 89678's rib feet kept 0.027 mm; find's planes are for batches).
      W24a  `hold`: the points that stay apart (welding, stage 9: T points, the ends of their host edges, unwelded
            twins) do not move - their rows are measured, their slit reported. Moved, one side of the pair moved and
            the other stayed: the copy tore open (92092: T gap 0.405 mm; 3.15 had 0.0001)
      W24b  `planes` (cagegeom._flat_planes: the count and the first two planes per point): a move keeps to the flat
            faces the point lies on, as W22 and W23 do - one plane: in it, two: along their line, three: none (con1:
            the slots' corners moved 0.063 mm off their walls). A flat piece whose corner would have to sink into a
            curved face keeps its slit there - W26 closes it on the copy
    Leaves the cage at q + the moves. Returns (the moves (n,3), points moved by the contacts, largest slit left)."""
    HISTORY.clear()
    d = np.asarray(d, np.float64).copy()
    rows = np.asarray(K["contacts"], np.int64).reshape(-1, 2)
    freeset = np.asarray(sorted(int(v) for v in free), np.int64)
    rows = rows[~np.isin(rows[:, 0], freeset)]
    if not len(rows) or work.modifiers.get("Subdivision") is None:
        return d, 0, 0.0
    n = len(q)
    still = np.zeros(n, bool)                   # W24a
    if len(hold):
        still[np.asarray(sorted(int(v) for v in hold), np.int64)] = True
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
            # the rows of the shell at once (Task 7: per row in Python it cost as much as the subdivisions)
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
        step[still] = 0.0                       # W24a: the points that stay apart
        if planes is not None:                  # W24b: a point keeps to the flat faces it lies on
            step = _in_planes(step, planes)
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


def _in_planes(step, planes):
    """`step` (n,3) without what leaves the flat faces a point lies on: `planes` = (count (n), the first two planes
    (n,2,3)) of cagegeom._flat_planes - one plane: the step in it; two: along their line; three or more: none."""
    count, pl = planes
    out = step.copy()
    one = count >= 1
    n1 = pl[:, 0]
    out[one] -= n1[one] * (out[one] * n1[one]).sum(axis=1)[:, None]
    two = count == 2
    if two.any():
        line = np.cross(pl[two, 0], pl[two, 1])
        line /= np.maximum(np.linalg.norm(line, axis=1), 1e-12)[:, None]
        out[two] = line * (step[two] * line).sum(axis=1)[:, None]
    out[count >= 3] = 0.0
    return out


HISTORY = []                # (largest slit, slits over 0.005) per round of the last close call - read by the tests
SNAPPED = [0, 0.0]          # W26 on the last copy: the points moved, the widest slit closed - read by the tests


def snap(cp, K, level, ev, hold=(), on=None):
    """W26: the seams of the baked copy `cp` (of `level`) closed on the copy itself. W24 closes its contacts on the
    smooth surface as the modifier makes it - the copy is another surface: W14c slides its points along it (43712:
    the top under a stud's foot lies 0.024 mm lower in the copy, the foot 0.018 mm above it), an open edge between
    two contact points bridges a hollow surface (61487: 0.121 mm between two points that had closed), a point at
    MAX_MOVE (89678, 11214) or held (W24a, W24b) keeps a rest. So what is seen is measured where it is seen: every
    contact point of `K` (find's dict) and, on the open edges between two contact points of one shell
    (K["edge_rows"]), the points the level gives them - the copy keeps the cage's numbers: cage point v is copy
    point v, the places on edge e are n + 3 e + k at level 2, n + e (the middle one) at level 1 - against the copy of
    the shell touched, as close measures (in front of it or beside it: a slit; behind it: none). A point with a slit
    from SLIT_MIN to SNAP_MAX goes onto the nearest point of that shell (of several shells the widest slit's). Then
    no quad of the copy may turn by more than SNAP_TURN: such a point goes half the way, up to SNAP_HALVES times,
    then it stays (as W14c's slide, reparam.FOLD_STEPS; 92092 folded 4 quads without it) - nor turn a quad that faced
    the way of its original face against it (`on`: per face of the copy the normal of its import face; the fold
    check's measure, more than 90 degrees: a quad already turned 80 degrees went past it by a turn under SNAP_TURN,
    review of the run 306 rework). Only points of the copy
    move; the cage and the copy's corner normals stay. `ev`: the cage's edges; `hold`: the points that stay apart
    (W24a) - they and the edges that end in one are left: their twin would not follow (92092: the T gap came back
    with 0.027 mm). Returns the number of points moved (SNAPPED: and the widest slit closed)."""
    SNAPPED[0], SNAPPED[1] = 0, 0.0
    if K is None:
        return 0
    rows = np.asarray(K["contacts"], np.int64).reshape(-1, 2)
    n = len(K["lab"])
    if not len(rows) or len(cp.vertices) < n + len(ev) * (2 ** level - 1):
        return 0
    still = np.zeros(n, bool)
    if len(hold):
        still[np.asarray(sorted(int(v) for v in hold), np.int64)] = True
    rows = rows[~still[rows[:, 0]]]
    at, touched = rows[:, 0], rows[:, 1]
    erows = np.asarray(K.get("edge_rows", np.zeros((0, 3))), np.int64).reshape(-1, 3)
    if len(erows):
        ends = np.asarray(ev, np.int64)[erows[:, 0]]
        erows = erows[~(still[ends[:, 0]] | still[ends[:, 1]])]
    if len(erows) and level in (1, 2):         # (other levels: the contact points only)
        if level == 1:
            erows = erows[erows[:, 1] == 1]
            e_at = n + erows[:, 0]
        else:
            e_at = n + erows[:, 0] * 3 + erows[:, 1]
        at, touched = np.r_[at, e_at], np.r_[touched, erows[:, 2]]
    co = np.zeros(len(cp.vertices) * 3); cp.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lv = np.zeros(len(cp.loops), np.int64); cp.loops.foreach_get("vertex_index", lv)
    le = np.zeros(len(cp.loops), np.int64); cp.loops.foreach_get("edge_index", le)
    e2 = np.zeros(len(cp.edges) * 2, np.int64); cp.edges.foreach_get("vertices", e2)
    if len(lv) % 4:
        return 0
    shells = sorted(set(touched.tolist()))
    parts = _shell_parts(co, (lv.reshape(-1, 4), e2.reshape(-1, 2), np.bincount(le, minlength=len(cp.edges))), shells)
    order = np.argsort(touched, kind="stable")
    slit = np.zeros(len(at))
    target = co[at].copy()
    trees = {}                                  # shell touched -> the tree of its copy (W26b reads them again)
    for s, todo in zip(*_groups(touched[order], order), strict=True):
        pts, faces, seg = parts[s]
        if not len(pts):
            continue
        tree = BVHTree.FromPolygons(co[pts].tolist(), faces)
        trees[s] = tree
        pp = co[at[todo]]
        hits = [tree.find_nearest(x, SNAP_MAX) for x in pp.tolist()]
        got = [k for k, h in enumerate(hits) if h[0] is not None]
        if not got:
            continue
        rows_s = todo[got]
        pp = pp[got]
        loc = np.array([hits[k][0] for k in got], np.float64)
        nrm = np.array([hits[k][1] for k in got], np.float64)
        dist = np.array([hits[k][3] for k in got], np.float64)
        behind = np.einsum("ij,ij->i", pp - loc, nrm) <= -BESIDE * dist
        if CONE:
            for k in np.nonzero(behind)[0].tolist():
                behind[k] = _behind_cone(tree, pp[k], loc[k], dist[k])
        if len(seg) and behind.any():           # the nearest point on the shell's open rim: beside it, a slit
            k = np.nonzero(behind)[0]
            behind[k[_to_segments(loc[k], co[seg[:, 0]], co[seg[:, 1]]) <= _tols(loc[k])]] = False
        slit[rows_s] = np.where(behind, 0.0, dist)
        target[rows_s] = loc
    new = co.copy()
    widest = np.zeros(len(co))
    for i in np.nonzero((slit > SLIT_MIN) & (slit <= SNAP_MAX))[0].tolist():
        v = at[i]
        if slit[i] > widest[v]:                 # of several shells touched: onto the widest slit's
            new[v], widest[v] = target[i], slit[i]
    _chords(new, widest, at, touched, trees, e2, le, len(cp.edges), still)
    quads = lv.reshape(-1, 4)
    k_near = np.nonzero((widest[quads] > 0).any(axis=1))[0]
    near = quads[k_near]
    if len(near):                               # the fold guard
        def normal(x):
            nn = np.cross(x[near[:, 2]] - x[near[:, 0]], x[near[:, 3]] - x[near[:, 1]])
            return nn / np.maximum(np.linalg.norm(nn, axis=1), 1e-30)[:, None]

        before = normal(co)
        own = None                              # the quads that face their import face's way before the snap
        if on is not None and len(on) == len(quads):
            own = np.asarray(on, np.float64)[k_near]
            faced = np.einsum("ij,ij->i", before, own) >= 0.0
        for step in range(SNAP_HALVES + 1):
            now = normal(new)
            bad = np.einsum("ij,ij->i", before, now) < SNAP_TURN
            if own is not None:
                bad |= faced & (np.einsum("ij,ij->i", now, own) < 0.0)
            if not bad.any():
                break
            vs = np.unique(near[bad])
            vs = vs[widest[vs] > 0]
            if step < SNAP_HALVES:
                new[vs] = co[vs] + 0.5 * (new[vs] - co[vs])
            else:
                new[vs], widest[vs] = co[vs], 0.0
    moved = int((widest > 0).sum())
    if moved:
        custom = cp.has_custom_normals
        normals = np.zeros(len(cp.loops) * 3, np.float32)
        if custom:
            cp.corner_normals.foreach_get("vector", normals)
        cp.vertices.foreach_set("co", new.astype(np.float32).ravel())
        cp.update()
        if custom:
            cp.normals_split_custom_set(normals.reshape(-1, 3))
        SNAPPED[0], SNAPPED[1] = moved, float(widest.max())
    return moved


def _chords(new, widest, at, touched, trees, e2, le, n_edges, still):
    """W26b (rework 2, run 306): the copy's own open edge between two points snap looks at is a chord - where the
    surface under it is hollow (the fillet at the foot of a wall) its middle stands before the surface though both
    ends lie on it (89678: 0.006 mm under the rib's edge, a dark wedge 0.3 mm long). Measured at 1/8, 1/4, 1/2, 3/4,
    7/8 against the copy of the shell both ends touch (`trees`); a place more than SLIT_MIN before a face (its way
    to it along the face's normal at least 0.7 of the distance - not beside the shell's open rim): both ends go on by
    the way that place lacks, CHORD_ADD times - of several the longest. Neither end may be held (`still`). Moves
    `new` and raises `widest` in place."""
    shell_of = {}
    for i in range(len(at)):
        shell_of.setdefault(int(at[i]), set()).add(int(touched[i]))
    e_open = e2.reshape(-1, 2)[np.bincount(le, minlength=n_edges) == 1]
    push = np.zeros((len(new), 3))
    for a, b in e_open.tolist():
        if a not in shell_of or b not in shell_of or (len(still) > max(a, b) and (still[a] or still[b])):
            continue
        for s in sorted(shell_of[a] & shell_of[b]):
            tree = trees.get(s)
            if tree is None:
                continue
            for w in (0.125, 0.25, 0.5, 0.75, 0.875):
                mid = new[a] + (new[b] - new[a]) * w
                loc, nrm, _f, dist = tree.find_nearest(mid.tolist(), SNAP_MAX)
                if loc is None or dist <= SLIT_MIN:
                    continue
                depth = float((mid - np.array(loc)) @ np.array(nrm))
                if depth < 0.7 * dist:          # behind the face, or beside the shell's rim
                    continue
                step = (np.array(loc) - mid) * CHORD_ADD
                for v in (a, b):
                    if np.linalg.norm(step) > np.linalg.norm(push[v]):
                        push[v] = step
    hit = np.linalg.norm(push, axis=1) > 0
    if hit.any():
        new[hit] += push[hit]
        widest[hit] = np.maximum(widest[hit], np.linalg.norm(push[hit], axis=1))


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
