"""Prepare imported Mecabricks parts for Subdivision Surface (general version).

The rule set with IDs, origins and checks is _CLAUDE_/RULES.md.

Usage:
  blender -b <import.blend> --python mecabricks_subdiv.py -- <target.blend>
          [--shading mecabricks|geometric]  (default mecabricks, chosen 2026-09-24) [--levels 2]

Works on every mesh in the file (shared meshes once). No axis or size
assumptions: islands are classified by shape.

Background (developed on 3001 and 3648, 2026-09-24, see _CLAUDE_/JOURNAL_260924.md):
  Mecabricks splits faces into loose islands along hard edges and stores the
  look in custom normals on flat-flagged faces. Rules per island:
    logo       embossed letters: two height levels ~0.12 apart along the top
               normal. Inner-corner slits (coincident vertices) are pinned,
               never merged: the original mesh stays untouched (user, run 16),
               edges bending > 50 deg are creased, and at joints (vertex with
               3+ creased edges) the flat top edges are creased too.
    flat       planar, no round boundary: every edge creased (exact shape,
               no in-plane folding; flat faces gain nothing from smoothing).
    flat-round planar with a polygonised circle in its boundary: stays smooth
               so it meets the smoothed curved neighbours; sharp boundary
               corners get vertex crease.
    curved     smooth; sharp boundary corners get vertex crease (Keep Corners
               only holds corners with exactly two edges).
  Seams: coincident boundary vertices of neighbouring islands are treated
  alike (one pinned -> all pinned), otherwise the two sides drift apart
  (10509a4 up to 1.1, turntable 0.4 before this rule).
  Self-check: the subdivided result is evaluated; islands with flipped
  sub-faces are escalated step by step: crease the folding faces' interior
  edges, then their neighbours' interior edges, then all their edges, and a
  flat-round island is finally creased completely. Interior edges first
  keeps circle arcs free (48168 pin block: a V touches the counterbore arc
  in a T; creasing the arc's edges had pinned the circle into a polygon).
  Copies (run 38): models are meshes plus their instances (links). Only the original
  mesh is processed; the subdivision is written once into a copy of it (viewport and
  render level, one copy if equal) that every link uses. No modifiers on the links; the
  original stays in the file unchanged.
  Shading: imported flags and custom normals are never changed.
    mecabricks  modifier interpolates the custom normals (soft logo)
    geometric   creased edges are added to sharp_edge; one node modifier
                "Mecabricks Subdiv" subdivides (same settings, creases from
                the attributes, level on the node) and shades the result smooth. One toggle;
                no driver (a driver on the object's own modifier toggle
                forms a dependency cycle).
"""
import bpy, bmesh, math, sys
import numpy as np
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d
from collections import Counter, defaultdict

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
TARGET = args[0] if args and not args[0].startswith("--") else None
def opt(name, default):
    return args[args.index(name) + 1] if name in args else default
SHADING = opt("--shading", "mecabricks")
METHOD = opt("--method", "weld")      # weld (rules 3.0) | rules24 (the island rules up to 2.4)
LEVELS = int(opt("--levels", "2"))
RULES_VERSION = "3.2"          # = RULES.md; shown in the add-on panel header
ARC_END = opt("--arc-end", "0") == "1"      # pin arc ends (run 19 test: did not remove the axle-hole crossing, off)
ESCALATE = opt("--escalate", "all")      # all | curved (flat folds tolerated) | none
REPAIR_T = opt("--repair-t", "0") == "1"   # T-fan topology repair (run 15 experiment, off: the band folds anyway)
assert SHADING in ("geometric", "mecabricks"), SHADING

FLAT_MAX_ANGLE = 1.0          # planar island: all normals within this
ROUND_TURN = (5.0, 40.0)      # boundary turn of a polygonised circle (12-gon: 30)
ROUND_REGULAR = 3.0           # ... repeated by both boundary neighbours within this
SHARP_TURN = 30.0             # boundary corner, unless part of a circle
LOGO_HEIGHT = (0.05, 0.30)    # emboss height range
LOGO_MAX_SIZE = 4.0           # bbox diagonal of one letter
LOGO_CREASE_ANGLE = 50.0
MERGE_DIST = 1e-4
DEGENERATE_AREA = 1e-8       # sliver faces of the import (run 21: 54200, 3386, 4973)
MAX_PASSES = 7
REPAIR_CREASE = 0.5         # first fold-repair step: semi-sharp, keeps arcs nearly free
FAN_CREASE = 0.4            # T fan: only the diagonals (run 17: lowest value without folds AND without sub-edges crossing the corner outline; point 0.051 instead of 0.079)
PARTIAL = {}                # edge index -> crease < 1 (fold repair)

def islands(bm):
    seen = set()
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            c = stack.pop(); comp.append(c)
            for e in c.edges:
                for lf in e.link_faces:
                    if lf.index not in seen:
                        seen.add(lf.index); stack.append(lf)
        yield comp

def dihedral(e):
    if len(e.link_faces) != 2:
        return None
    return math.degrees(e.link_faces[0].normal.angle(e.link_faces[1].normal, 0.0))

# turn and is_round depend on the geometry only, which never changes (P1). While
# process() runs they are cached by vertex index (run 33: turn ran 3.5 M times on
# the Porsche); outside process() (tools on several meshes) there is no cache.
GEOM_CACHE = None

def turn(v):
    if GEOM_CACHE is not None:
        k = ("t", v.index)
        if k not in GEOM_CACHE:
            GEOM_CACHE[k] = _turn(v)
        return GEOM_CACHE[k]
    return _turn(v)

def _turn(v):
    be = [e for e in v.link_edges if e.is_boundary]
    if len(be) != 2:
        return None
    a = be[0].other_vert(v).co - v.co
    b = be[1].other_vert(v).co - v.co
    if a.length < 1e-9 or b.length < 1e-9:
        return None
    return 180.0 - math.degrees(a.angle(b))

def boundary_neighbours(v):
    return [e.other_vert(v) for e in v.link_edges if e.is_boundary]

def is_round(v):
    if GEOM_CACHE is not None:
        k = ("r", v.index)
        if k not in GEOM_CACHE:
            GEOM_CACHE[k] = _is_round(v)
        return GEOM_CACHE[k]
    return _is_round(v)

def _is_round(v):
    # K3 regular circles, or K3b an arc run; the run test must also get the first and
    # last vertex of an arc, whose outer neighbour is straight (run 41)
    return _regular_round(v) or in_arc_run(v)

def _regular_round(v):
    """Boundary vertex on a polygonised circle: a gentle turn (5-40 deg) that
    repeats regularly - either every neighbour turns alike (period 1) or the
    turns alternate and every second vertex turns alike (period 2, e.g. 13.9 /
    8.6 deg on the 42610 rim in Banana_Mech, run 26)."""
    t = turn(v)
    if t is None or not (ROUND_TURN[0] < t < ROUND_TURN[1]):
        return False
    nb = boundary_neighbours(v)
    if len(nb) != 2:
        return False
    t1 = [turn(w) for w in nb]
    if all(x is not None and abs(x - t) <= ROUND_REGULAR for x in t1):
        return True                                  # period 1 (unchanged test)
    if any(x is None or not (ROUND_TURN[0] < x < ROUND_TURN[1]) for x in t1):
        return False
    # period 2: the vertices two steps away turn like this one
    t2 = []
    for w in nb:
        nxt = [u for u in boundary_neighbours(w) if u is not v]
        if len(nxt) != 1:
            return False
        t2.append(turn(nxt[0]))
    return all(x is not None and abs(x - t) <= ROUND_REGULAR for x in t2)

# K3b (run 41): unevenly divided arcs. part.380 (54200.002, Banana_Mech): a quarter circle
# as "9 14 11 17 22 16" and a fillet easing into a straight edge as "32 27 13 6 7 4" -
# neither regular nor alternating. A vertex is on an arc if it lies in a run of at least
# ARC_MIN_LEN consecutive gentle turns (ARC_MIN_TURN..ROUND_TURN max) that bends at least
# ARC_MIN_TOTAL in all, neighbouring turns differing by at most ARC_STEP_RATIO. A designed
# polygon corner (45 deg chamfer, 90 deg corners) never forms such a run.
ARC_MIN_TURN = 3.0
ARC_MIN_LEN = 3
ARC_MIN_TOTAL = 45.0
ARC_STEP_RATIO = 2.5

def in_arc_run(v):
    arc = lambda x: x is not None and ARC_MIN_TURN < x < ROUND_TURN[1]
    t = turn(v)
    if not arc(t):
        return False
    run, seen = [t], {v}
    for first in boundary_neighbours(v):
        prev, cur, last = v, first, t
        while cur not in seen:
            tc = turn(cur)
            if not arc(tc) or max(tc, last) / min(tc, last) > ARC_STEP_RATIO:
                break
            run.append(tc); seen.add(cur); last = tc
            nxt = [u for u in boundary_neighbours(cur) if u is not prev]
            if len(nxt) != 1:
                break
            prev, cur = cur, nxt[0]
    return len(run) >= ARC_MIN_LEN and sum(run) >= ARC_MIN_TOTAL

def is_sharp(v):
    t = turn(v)
    return t is not None and t > SHARP_TURN and not is_round(v)

def is_arc_end(v):
    """Last point of a circle arc where a straight edge begins: turns like an
    arc point, but only one boundary neighbour is on the arc. Left free, the
    straight edge bows (3648 cross-axle hole: 0.081). Pinned when ARC_END."""
    t = turn(v)
    if t is None or is_round(v) or is_sharp(v) or not (ROUND_TURN[0] < t < ROUND_TURN[1]):
        return False
    return sum(1 for w in boundary_neighbours(v) if is_round(w)) == 1

def logo_normal(comp):
    """Top normal if the island is an embossed letter, else None."""
    if len(comp) < 3:
        return None
    verts = {v for f in comp for v in f.verts}
    lo = [v.co.copy() for v in verts]
    diag = (max(c.x for c in lo) - min(c.x for c in lo), max(c.y for c in lo) - min(c.y for c in lo),
            max(c.z for c in lo) - min(c.z for c in lo))
    if math.sqrt(sum(d * d for d in diag)) > LOGO_MAX_SIZE:
        return None
    # candidate top normals, largest area first (flanks may outweigh narrow tops)
    area, rep = Counter(), {}
    for f in comp:
        k = tuple(round(c, 2) for c in f.normal)
        area[k] += f.calc_area()
        rep.setdefault(k, f.normal.copy())
    for k, _ in area.most_common(6):
        n = rep[k]
        h = [v.co.dot(n) for v in verts]
        hmin, hmax = min(h), max(h)
        if not (LOGO_HEIGHT[0] < hmax - hmin < LOGO_HEIGHT[1]):
            continue
        if any(min(abs(x - hmin), abs(x - hmax)) > 0.01 for x in h):
            continue
        top = [f for f in comp if math.degrees(f.normal.angle(n, 0.0)) < 2.0]
        flank = [f for f in comp if 40.0 < math.degrees(f.normal.angle(n, 0.0)) < 85.0]
        if top and flank and all(abs(f.calc_center_median().dot(n) - hmax) < 0.02 for f in top):
            return n
    return None

def classify(bm):
    out = []
    for comp in islands(bm):
        n = logo_normal(comp)
        if n is not None:
            out.append(("logo", comp, n)); continue
        real = [f for f in comp if f.calc_area() > DEGENERATE_AREA] or comp
        n0 = max(real, key=lambda f: f.calc_area()).normal
        flat = all(math.degrees(n0.angle(f.normal, 0.0)) <= FLAT_MAX_ANGLE for f in real)
        verts = {v for f in comp for v in f.verts}
        roundb = any(is_round(v) for v in verts if v.is_boundary)
        out.append(("flat-round" if flat and roundb else "flat" if flat else "curved", comp, None))
    return out

def merge_logo_slits(me):
    bm = bmesh.new(); bm.from_mesh(me)
    logo_verts = {v for kind, comp, _ in classify(bm) if kind == "logo" for f in comp for v in f.verts}
    n = len(bm.verts)
    if logo_verts:
        bmesh.ops.remove_doubles(bm, verts=list(logo_verts), dist=MERGE_DIST)
    merged = n - len(bm.verts)
    if merged:
        bm.to_mesh(me)
    bm.free()
    return merged

def repair_t_fans(me, folding):
    """Topology repair for T fans in flat islands (48168 pin block).

    A boundary vertex t on a circle arc with three interior edges: the middle
    one continues a strip (e.g. a rib), the outer two run diagonally to the
    strip's corners u. The wedge faces between arc and diagonals fold under
    Catmull-Clark. Repair per side: insert a vertex A on the arc edge where the
    strip side (through u, parallel to the middle edge) meets it, split the
    wedge face along A-u, and join the left-over triangle A-t-u with the strip
    face. Afterwards t has one interior edge (a regular arc vertex). Flat faces
    only, so the look with subdiv off does not change. Only fans next to a
    folding face are touched, and the arc edge of the neighbouring island that
    shares the seam is split at the same point (no new T across the seam).
    """
    from mathutils.geometry import intersect_line_line
    snap = normals_snapshot(me)
    bm = bmesh.new(); bm.from_mesh(me)
    flat_faces = set()
    for kind, comp, _ in classify(bm):
        if kind in ("flat", "flat-round"):
            flat_faces |= {f.index for f in comp}
    candidates = []
    for t in bm.verts:
        if not (t.is_boundary and is_round(t)):
            continue
        inner = [e for e in t.link_edges if not e.is_boundary]
        arcs = [e for e in t.link_edges if e.is_boundary]
        if len(inner) != 3 or len(arcs) != 2:
            continue
        if any(f.index not in flat_faces for f in t.link_faces):
            continue
        if not any(f.index in folding for f in t.link_faces):
            continue
        candidates.append(t.index)
    repaired = 0
    for ti in candidates:
        bm.verts.ensure_lookup_table()
        t = bm.verts[ti]
        inner = [e for e in t.link_edges if not e.is_boundary]
        arcs = [e for e in t.link_edges if e.is_boundary]
        sides = []                       # (arc edge, wedge face, diagonal edge)
        for ae in arcs:
            wedge = ae.link_faces[0]
            diag = next((e for e in wedge.edges if e in inner), None)
            if diag is None:
                break
            sides.append((ae, wedge, diag))
        if len(sides) != 2:
            continue
        mid = next(e for e in inner if e not in (sides[0][2], sides[1][2]))
        d = (t.co - mid.other_vert(t).co).normalized()
        plan = []
        for ae, wedge, diag in sides:
            u, a = diag.other_vert(t), ae.other_vert(t)
            hit = intersect_line_line(u.co, u.co + d, t.co, a.co)
            if not hit:
                break
            fac = (hit[1] - t.co).length / max((a.co - t.co).length, 1e-9)
            if not (0.05 < fac < 0.95) or (hit[0] - hit[1]).length > 1e-3:
                break
            plan.append((ae, diag, u, fac))
        if len(plan) != 2:
            continue
        for ae, diag, u, fac in plan:
            strip = next(f for f in diag.link_faces if ae not in f.edges)
            a = ae.other_vert(t)
            # seam partner: boundary edge of another island between the same points
            key = lambda v: tuple(round(c, 4) for c in v.co)
            kt, ka = key(t), key(a)
            partners = [e for e in bm.edges if e.is_boundary and e is not ae
                        and {key(e.verts[0]), key(e.verts[1])} == {kt, ka}]
            for pe in partners:
                pt = next(v for v in pe.verts if key(v) == kt)
                _, A2 = bmesh.utils.edge_split(pe, pt, fac)
                # a vertex with only two edges counts as a corner under Keep
                # Corners and would be pinned: connect it into its face
                pf = A2.link_faces[0]
                if len(pf.verts) >= 5:
                    ring = list(pf.verts); i = ring.index(pt)
                    far = ring[(i - 1) % len(ring)] if ring[(i + 1) % len(ring)] is A2 else ring[(i + 1) % len(ring)]
                    bmesh.utils.face_split(pf, A2, far)
            e_new, A = bmesh.utils.edge_split(ae, t, fac)
            wedge = next(f for f in A.link_faces)
            res = bmesh.utils.face_split(wedge, A, u)
            tri = next(f for f in (wedge, res[0]) if t in f.verts)
            bmesh.utils.face_join([tri, strip])
        repaired += 1
    if repaired:
        bm.to_mesh(me)
        restore_normals(me, snap)
    bm.free()
    return repaired

def _pos(co):
    return tuple(round(c, 4) for c in co)

def normals_snapshot(me):
    """Per original face: vertex-position set, face normal, corner normals by position."""
    cn = me.corner_normals
    faces = []
    for p in me.polygons:
        d = {_pos(me.vertices[me.loops[l].vertex_index].co): cn[l].vector.copy() for l in p.loop_indices}
        faces.append((frozenset(d), p.normal.copy(), d))
    return faces

def restore_normals(me, snap):
    """After a topology repair: unchanged faces keep their corner normals,
    changed faces take the original normal at each position (from an original
    face on the same surface side), inserted vertices the interpolation of the
    two neighbouring corners along the face. Written back as custom normals."""
    by_key = {k: d for k, n, d in snap}
    by_pos = {}
    for k, n, d in snap:
        for pos, cnrm in d.items():
            by_pos.setdefault(pos, []).append((n, cnrm))
    out = [None] * len(me.loops)
    for p in me.polygons:
        pos = [_pos(me.vertices[me.loops[l].vertex_index].co) for l in p.loop_indices]
        d = by_key.get(frozenset(pos))
        vals = []
        for q in pos:
            if d is not None:
                vals.append(d[q]); continue
            cands = [c for n, c in by_pos.get(q, []) if n.angle(p.normal, 0.0) < math.radians(30)]
            vals.append(min(cands, key=lambda c: c.angle(p.normal, 0.0)) if cands else None)
        for i, v in enumerate(vals):
            if v is None:            # inserted vertex: interpolate along the face
                a, b = vals[i - 1], vals[(i + 1) % len(vals)]
                pa, pb, pq = (Vector(pos[i - 1]), Vector(pos[(i + 1) % len(pos)]), Vector(pos[i]))
                t = (pq - pa).length / max((pb - pa).length, 1e-9)
                if a is None or b is None:
                    vals[i] = p.normal.copy()
                else:
                    vals[i] = (a * (1 - t) + b * t).normalized()
        for l, v in zip(p.loop_indices, vals):
            out[l] = v
    me.normals_split_custom_set([tuple(v) for v in out])

def rule_creases(bm, escalate):
    """escalate: {island key (min face index): level} from the self-check."""
    E, V = set(), set()
    stats = Counter()
    for kind, comp, n in classify(bm):
        key = min(f.index for f in comp)
        level = escalate.get(key, 0)
        stats[kind] += 1
        edges = {e for f in comp for e in f.edges}
        verts = {v for f in comp for v in f.verts}
        if kind == "logo":
            le = {e for e in edges if (a := dihedral(e)) is not None and a > LOGO_CREASE_ANGLE}
            # slits (inner corners left open by Mecabricks, not merged): their
            # open edges act like a creased corner edge for the joint rule
            pos = Counter(tuple(round(c, 4) for c in v.co) for v in verts if v.is_boundary)
            slit_v = {v for v in verts if v.is_boundary and pos[tuple(round(c, 4) for c in v.co)] > 1}
            slit_e = {e for e in edges if e.is_boundary and (e.verts[0] in slit_v or e.verts[1] in slit_v)}
            for v in verts:
                if sum(1 for e in v.link_edges if e in le or e in slit_e) >= 3:
                    for e in v.link_edges:
                        if e in le or len(e.link_faces) != 2:
                            continue
                        if all(math.degrees(f.normal.angle(n, 0.0)) < 2.0 for f in e.link_faces):
                            le.add(e)
            E |= {e.index for e in edges} if level else {e.index for e in le}
        elif kind == "flat" or (kind == "flat-round" and level >= 4):
            E |= {e.index for e in edges}
            if kind == "flat-round":
                stats["flat-round fully creased"] += 1
        else:
            for v in verts:
                if v.is_boundary and (is_sharp(v) or (ARC_END and is_arc_end(v))):
                    V.add(v.index)
            if level:
                # fold repair, gentlest first (48168 experiment: pinning vertices
                # never helps; creasing the folding face's interior edges does)
                #   1 T fan: crease only the diagonal from the T vertex at 0.2,
                #     mirrored onto the seam partner, T stays free (run 17);
                #     other folds: interior edges of the folding faces at 0.5
                #   2 + full crease, widened to the neighbours' interior edges
                #   3 all edges of folding faces and neighbours
                #   5 flat-round: whole island creased
                bad = set(escalate_faces.get(key, set()))
                if level >= 2:
                    bad |= {g.index for f in comp if f.index in bad for e in f.edges for g in e.link_faces}
                sel = {e.index for f in comp if f.index in bad for e in f.edges
                       if level >= 3 or not e.is_boundary}
                if level == 1:
                    for f in comp:
                        if f.index not in bad:
                            continue
                        ts = [v for v in f.verts if v.is_boundary and is_round(v) and len(v.link_edges) > 3]
                        if ts:
                            # T fan (R10/F1): crease only the diagonal from the T vertex;
                            # the seam rule mirrors it onto the partner, T stays free
                            for e in f.edges:
                                if not e.is_boundary and any(t in e.verts for t in ts):
                                    PARTIAL[e.index] = max(PARTIAL.get(e.index, 0.0), FAN_CREASE)
                        else:
                            for e in f.edges:
                                if not e.is_boundary:
                                    PARTIAL[e.index] = max(PARTIAL.get(e.index, 0.0), REPAIR_CREASE)
                else:
                    E |= sel
                stats[f"{kind} escalated"] += 1
    # M1b (run 42): boundary smoothing "All" instead of "Keep Corners"; the corners Keep
    # Corners held (boundary vertices with exactly two edges) are pinned explicitly -
    # except vertices on an arc: on few large faces (plate corners of 36840, part.375 in
    # Banana_Mech) the arc vertices have two edges each and Keep Corners froze the arc.
    V |= {v.index for v in bm.verts if v.is_boundary and len(v.link_edges) == 2 and not is_round(v)}
    return E, V, stats

def is_pinned(v, E, V):
    """Boundary vertex that subdivision keeps in place: vertex crease, a creased
    interior edge (corner rule), or Keep Corners (exactly two edges)."""
    if v.index in V or (len(v.link_edges) == 2 and not is_round(v)):
        return True
    return any(e.index in E for e in v.link_edges if not e.is_boundary)

def unify_seams(bm, E, V):
    added_slit = []
    added = 0
    """Coincident boundary vertices of neighbouring islands must move alike:
    if one of them is pinned, pin all of them; a partial repair crease is
    mirrored onto the partner's interior edge (or all are pinned when the
    structures differ). Repeat until stable."""
    from collections import defaultdict
    groups = defaultdict(list)
    for v in bm.verts:
        if v.is_boundary:
            groups[tuple(round(c, 4) for c in v.co)].append(v)
    groups = [g for g in groups.values() if len(g) > 1]
    inner = lambda v: [e for e in v.link_edges if not e.is_boundary]
    # slits: coincident boundary vertices of the same island (e.g. inside
    # corners of logo letters). Pinned, so both sides stay together; the
    # original mesh is not merged.
    iid = {}
    for n, comp in enumerate(islands(bm)):
        for f in comp:
            iid[f.index] = n
    # S2 (run 47): only where the sides diverge - an open seam through one island whose
    # sides share the same outline (tail of the horse 10509a4: 53 pairs) moves alike
    # without a pin; pinning it froze the silhouette
    for g in groups:
        ids = [iid[v.link_faces[0].index] for v in g if v.link_faces]
        same_path = len({frozenset(tuple(round(c, 4) for c in w.co) for w in boundary_neighbours(v))
                         for v in g}) == 1
        if len(ids) != len(set(ids)) and not same_path:
            for v in g:
                if not is_pinned(v, E, V):
                    V.add(v.index); added_slit.append(v.index)
    # branching seams: if the members' boundary neighbours are not at the same
    # positions, their boundary curves diverge here and would smooth apart
    # (3713 in Banana_Mech: gap 0.060) -> pin the whole group
    P = lambda v: tuple(round(c, 4) for c in v.co)
    for g in groups:
        paths = {frozenset(P(w) for w in boundary_neighbours(v)) for v in g}
        if len(paths) > 1 and not any(is_pinned(v, E, V) for v in g):
            for v in g:
                V.add(v.index); added += 1
    # phase 1: pins, to a fixed point (a pinned group never gets a mirrored
    # partial crease: it would run on through the next edge as a chain of
    # points, 48168 pin hole, run 20)
    changed = True
    while changed:
        changed = False
        for g in groups:
            if any(is_pinned(v, E, V) for v in g):
                for v in g:
                    if not is_pinned(v, E, V):
                        V.add(v.index); added += 1; changed = True
    # phase 2: mirror partial creases between free vertices only
    changed = True
    while changed:
        changed = False
        for g in groups:
            if any(is_pinned(v, E, V) for v in g):
                continue
            w = max((PARTIAL.get(e.index, 0.0) for v in g for e in inner(v)), default=0.0)
            if w <= 0.0:
                continue
            carriers = [v for v in g if any(PARTIAL.get(e.index, 0.0) > 0 for e in inner(v))]
            multi = [v for v in g if len(inner(v)) != 1]
            if len(multi) <= 1 and all(v in carriers for v in multi):
                for v in g:
                    if len(inner(v)) == 1:
                        e = inner(v)[0]
                        if PARTIAL.get(e.index, 0.0) != w and e.index not in E:
                            PARTIAL[e.index] = w; changed = True
            else:
                for v in g:
                    V.add(v.index); added += 1
                changed = True
    return added + len(added_slit)

def write_creases(me, E, V):
    ea = me.attributes.get("crease_edge") or me.attributes.new("crease_edge", 'FLOAT', 'EDGE')
    ea.data.foreach_set("value", [1.0 if i in E else PARTIAL.get(i, 0.0) for i in range(len(me.edges))])
    va = me.attributes.get("crease_vert") or me.attributes.new("crease_vert", 'FLOAT', 'POINT')
    va.data.foreach_set("value", [1.0 if i in V else 0.0 for i in range(len(me.vertices))])

def add_subsurf(ob):
    mod = ob.modifiers.get("Subdivision") or ob.modifiers.new("Subdivision", 'SUBSURF')
    mod.subdivision_type = 'CATMULL_CLARK'
    mod.levels = LEVELS
    mod.render_levels = LEVELS
    mod.use_creases = True
    mod.boundary_smooth = 'ALL'            # corners pinned by vertex crease instead (M1b, run 42)
    mod.use_limit_surface = True
    mod.use_custom_normals = SHADING == "mecabricks"
    # W14 (run 58): UVs smoothed with the island boundaries kept (Blender's default). The
    # subdivision also moves vertices within a plane; smoothed UVs move along, so prints keep
    # their shape. Linear UVs ('NONE') or UVs projected from the original distorted the
    # lettering of 86209. The wavy print lines of 86209 came from the spreading bevel (W13).
    mod.uv_smooth = UV_SMOOTH
    return mod

# ---------------------------------------------------------------- subdivided mesh copies
# Mecabricks and LDraw models are meshes plus their instances (objects linking one mesh;
# the material sits on the mesh). Modifiers belong to objects, not to meshes: a
# Subdivision modifier on every link made Blender subdivide every instance separately -
# the Porsche (2,710 objects) ran out of 95 GB and crashed (run 36). So only the original
# mesh is processed (creases), and the subdivision is written once into a copy of it that
# every link then uses (run 38): same objects, same links, no modifiers on the links. The
# original stays unchanged in the file (fake user) - "off" points the links back to it.
# Viewport and render level may differ: then there are two copies, and the add-on switches
# the links to the render copy for the duration of a render.
#   original["rb_view"] / ["rb_render"]  names of the copies ("" = original, level 0)
#   copy["rb_original"], copy["rb_level"], copy["rb_variant"]
VIEW_LEVEL = int(opt("--view-level", "1"))       # set by the add-on or the command line; 1: a quarter of
# the faces of level 2 to draw - NINJAGO_City opened slowly with level 2 on 4,964 objects (run 52)
RENDER_LEVEL = int(opt("--render-level", str(LEVELS)))
WORK_NAME = "RB work"


def original_of(me):
    """The imported mesh behind a (possibly subdivided) mesh."""
    name = me.get("rb_original")
    return bpy.data.meshes.get((name, None), me) if name else me     # the local one (run 65)


def copy_of(orig, which="view"):
    """The subdivided copy used in the viewport or the render (None: the original itself)."""
    name = orig.get(f"rb_{which}", "")
    return bpy.data.meshes.get((name, None)) if name else None      # local: the override, not its reference


# While a batch over many meshes runs (level switch, run 72) the copies are looked up in an
# index built once: searching all 13,845 meshes of Dungeon for each of its 2,769 originals
# took 23 s before the progress bar could even appear.
_COPY_INDEX = [None]


def copy_index_begin():
    idx = {}
    for m in bpy.data.meshes:
        if m.library is None:
            n = m.get("rb_original")
            if n:
                idx.setdefault(n, []).append(m)
    _COPY_INDEX[0] = idx
    return idx


def copy_index_end():
    _COPY_INDEX[0] = None


def all_copies(orig):
    """The copies of a mesh in this file (linked meshes of a cache are only the references of
    their overrides, run 65)."""
    idx = _COPY_INDEX[0]
    if idx is not None:
        out = []
        for m in idx.get(orig.name, ()):
            try:
                if m.get("rb_original") == orig.name:
                    out.append(m)
            except ReferenceError:              # removed meanwhile
                pass
        return out
    return [m for m in bpy.data.meshes if m.library is None and m.get("rb_original") == orig.name]


WORK_SCENE = "RB work scene"


def work_scene():
    """A scene of its own for the temporary work object (run 52): evaluating it in the user's
    scene re-evaluated the whole dependency graph each time - 96 ms per evaluation with the
    4,966 objects of NINJAGO_City, 1 ms in a scene of its own."""
    sc = bpy.data.scenes.get(WORK_SCENE)
    if sc is None:
        sc = bpy.data.scenes.new(WORK_SCENE)
    return sc


def drop_work_scene():
    sc = bpy.data.scenes.get(WORK_SCENE)
    if sc is not None and not sc.collection.all_objects:
        bpy.data.scenes.remove(sc)


def link_work(ob):
    work_scene().collection.objects.link(ob)
    return ob


def depsgraph_of(ob):
    """Evaluated dependency graph of the scene the object lives in."""
    sc = ob.users_scene[0] if ob.users_scene else bpy.context.scene
    if sc == bpy.context.scene:
        return bpy.context.evaluated_depsgraph_get()
    with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
        return bpy.context.evaluated_depsgraph_get()


def work_object(me):
    """Temporary object in a scene of its own: the only thing that ever carries a modifier."""
    return link_work(bpy.data.objects.new(WORK_NAME, me))


def bake_copy(orig, work, level):
    """Evaluate `work` (the original with the finished creases) at `level` and store the
    result as a mesh of its own - positions and custom normals identical to the modifier
    (run 38: max. difference 0.0 on all 254 Porsche meshes)."""
    global LEVELS
    keep = LEVELS
    LEVELS = level
    try:
        mod = work.modifiers.get("Subdivision")
        if mod:
            add_subsurf(work)                   # level and custom normals for this copy
            # the limit surface near free two-edge boundary vertices is only approximated at
            # the default quality 3: seams opened by up to 0.018 (run 42). Quality 10 is exact
            # there (0.0); used only for the copies, the checks keep the fast default.
            mod.quality = bake_quality(orig)
        dg = depsgraph_of(work)
        oe = work.evaluated_get(dg)
        cp = bpy.data.meshes.new_from_object(oe, preserve_all_data_layers=True, depsgraph=dg)
    finally:
        LEVELS = keep
    cp.name = f"{orig.name} L{level}"
    cp["rb_original"], cp["rb_level"], cp["rb_variant"] = orig.name, level, SHADING
    cp["rb_rules"] = RULES_VERSION          # Apply skips meshes whose copies are up to date (user, 2026-09-28)
    if _COPY_INDEX[0] is not None:
        _COPY_INDEX[0].setdefault(orig.name, []).append(cp)
    cp.use_fake_user = True      # a copy no link uses right now (L1, the render copy) is saved too (run 40)
    if UV_PROJECT:
        project_uvs(orig, cp, level)
    strip_copy(cp)
    return cp


# Data of the welded work mesh that the finished copies do not need (run 61: 11 % of an L2
# copy of Ratatouille): creases (already in the geometry), island and face numbers of the
# rules, the selection flags of the import (a copy is never edited).
COPY_DROP = ("crease_edge", "crease_vert", "rb_island", "rb_fi")
COPY_DROP_PREFIX = (".select_", ".uv_select_", ".vs.", ".es.", ".pn.")


def strip_copy(cp):
    for a in [a.name for a in cp.attributes]:
        if a in COPY_DROP or a.startswith(COPY_DROP_PREFIX):
            try:
                cp.attributes.remove(cp.attributes[a])
            except (RuntimeError, KeyError):
                pass


def project_uvs(orig, cp, level):
    """Optional (UV_PROJECT, off - run 58): UVs of the copy taken from the original. Every
    corner of a child face is placed on the triangles of its own original face and gets the
    UVs interpolated there. Exact for points on the original face, but the subdivision also
    moves vertices within a plane, across face borders - clamped to their own face, the
    lettering of 86209 was distorted. Kept for tests; the copies use smoothed UVs (W14).
    Welding keeps the face order, so child faces follow their original face in blocks."""
    if not orig.uv_layers or not cp.uv_layers or not len(orig.polygons):
        return
    orig.calc_loop_triangles()
    nt = len(orig.loop_triangles)
    tl = np.empty(nt * 3, np.int64); orig.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    tp = np.empty(nt, np.int64); orig.loop_triangles.foreach_get("polygon_index", tp)
    order = np.argsort(tp, kind="stable"); tl, tp = tl[order], tp[order]
    npoly = len(orig.polygons)
    tcount = np.bincount(tp, minlength=npoly); tstart = np.concatenate(([0], np.cumsum(tcount)[:-1]))
    lv = np.empty(len(orig.loops), np.int64); orig.loops.foreach_get("vertex_index", lv)
    oc = np.empty(len(orig.vertices) * 3); orig.vertices.foreach_get("co", oc); oc = oc.reshape(-1, 3)
    A, B, C = oc[lv[tl[:, 0]]], oc[lv[tl[:, 1]]], oc[lv[tl[:, 2]]]
    # child faces -> original face (blocks of loop_total * 4^(level-1) faces)
    sizes = np.empty(npoly, np.int64); orig.polygons.foreach_get("loop_total", sizes)
    per = sizes * 4 ** (level - 1)
    if per.sum() != len(cp.polygons):
        return                                  # not a plain subdivision of this original
    owner_f = np.repeat(np.arange(npoly), per)
    ctot = np.empty(len(cp.polygons), np.int64); cp.polygons.foreach_get("loop_total", ctot)
    owner = np.repeat(owner_f, ctot)            # per loop of the copy
    cl = np.empty(len(cp.loops), np.int64); cp.loops.foreach_get("vertex_index", cl)
    cc = np.empty(len(cp.vertices) * 3); cp.vertices.foreach_get("co", cc); cc = cc.reshape(-1, 3)
    n = len(cl)
    best = np.full(n, np.inf); btri = np.full(n, -1, np.int64); bw = np.zeros((n, 3))
    kmax = int(tcount.max()) if nt else 0
    for k in range(kmax):
        for c0 in range(0, n, UV_CHUNK):          # chunks: a 4.5 M-face copy has 18 M corners
            idx = np.nonzero(tcount[owner[c0:c0 + UV_CHUNK]] > k)[0] + c0
            if not len(idx):
                continue
            t = tstart[owner[idx]] + k
            a, b, c, x = A[t], B[t], C[t], cc[cl[idx]]
            v0, v1, v2 = b - a, c - a, x - a
            d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
            d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
            den = d00 * d11 - d01 * d01
            ok = den > 1e-18
            den = np.where(ok, den, 1.0)
            wv = (d11 * d20 - d01 * d21) / den
            ww = (d00 * d21 - d01 * d20) / den
            w = np.stack((1.0 - wv - ww, wv, ww), 1)
            out = np.clip(-w, 0, None).sum(1)       # how far outside the triangle (0: inside)
            w = np.clip(w, 0, None)
            w /= np.maximum(w.sum(1, keepdims=True), 1e-12)
            p = a * w[:, :1] + b * w[:, 1:2] + c * w[:, 2:]
            score = np.where(ok, out * 1e3 + np.linalg.norm(x - p, axis=1), np.inf)
            better = score < best[idx]
            j = idx[better]
            best[j], btri[j], bw[j] = score[better], t[better], w[better]
    hit = btri >= 0
    if not hit.any():
        return
    for lay in orig.uv_layers:
        dst = cp.uv_layers.get(lay.name)
        if dst is None:
            continue
        ou = np.empty(len(orig.loops) * 2); lay.data.foreach_get("uv", ou); ou = ou.reshape(-1, 2)
        cu = np.empty(n * 2); dst.data.foreach_get("uv", cu); cu = cu.reshape(-1, 2)
        tt = tl[btri[hit]]
        cu[hit] = (ou[tt[:, 0]] * bw[hit, :1] + ou[tt[:, 1]] * bw[hit, 1:2] + ou[tt[:, 2]] * bw[hit, 2:])
        dst.data.foreach_set("uv", cu.ravel())


def real_users(m):
    return m.users - (1 if m.use_fake_user else 0)


def point_links(obs, orig, which="view"):
    """Let the objects use the viewport (or render) copy of their original."""
    target = copy_of(orig, which) or orig
    for ob in obs:
        if ob.data != target:
            ob.data = target


def drop_copies(orig, keep=()):
    """Remove the copies of a mesh that nothing uses any more (keep: the copies to keep)."""
    for m in all_copies(orig):
        if m not in keep and real_users(m) == 0:
            bpy.data.meshes.remove(m)


# Only the chosen viewport and render levels are baked (run 61; up to 1.8.0 levels 1 and 2
# always were): with viewport 0 (the originals in the viewport) no L1 copy is stored - 19 %
# of Dungeon's 12 GB of copies. A level chosen later is baked then (progress bar).
PRE_LEVELS = ()
BAKE_QUALITY = 10
# Quality 10 needs about 0.2 MB per original face; the 32x32 baseplate 3811 of NINJAGO_City
# (286k faces) crashed at 33 GB (run 45), quality 6 baked it with 24 GB. Above
# QUALITY_FACE_LIMIT faces the copies are baked at BAKE_QUALITY_LARGE (seam gaps <= 0.0003
# in run 42, below the check threshold 0.001 - the check stays the control).
BAKE_QUALITY_LARGE = 6
QUALITY_FACE_LIMIT = 50000

# Memory guard (add-on 1.5.8, run 49): the quality bake of one large mesh needs about
# 0.2 MB (quality 10) or 0.085 MB (quality 6) per original face - the 286k-face baseplate
# of NINJAGO_City ~24 GB. In the window a crash lost the user's work when another program
# (a local language model, 40 GB) had taken the memory. Before each mesh the free commit
# memory (RAM + page file, what Windows reports as running out) is compared with the need.
GB_PER_FACE = {BAKE_QUALITY: 0.2e-3, BAKE_QUALITY_LARGE: 0.085e-3}
GB_MARGIN = 1.5


class MemoryShortage(Exception):
    pass


def memory_need_gb(me, level=2):
    """Measured at level 2; every further level has four times the faces."""
    return len(me.polygons) * GB_PER_FACE.get(bake_quality(me), 0.2e-3) * 1.05 * 4 ** max(0, level - 2) + GB_MARGIN


FREE_OVERRIDE = [None]      # tests: a worker told it has no memory (RENDERBRICKER_TEST_SHORT_WORKER)


def free_memory_gb():
    """Memory a bake can still use, in GB; None if unknown.
    Windows: free commit memory (RAM + page file, what runs out first there).
    Linux: MemAvailable (free RAM + reclaimable cache) + free swap.
    macOS: free + inactive + speculative + purgeable pages (vm_stat) + free swap."""
    import sys
    if FREE_OVERRIDE[0] is not None:
        return FREE_OVERRIDE[0]
    if sys.platform.startswith("win"):
        try:
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullAvailPageFile / 2**30
        except (AttributeError, OSError):
            pass
        return None
    if sys.platform.startswith("linux"):
        try:
            info = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
            return (info.get("MemAvailable", info.get("MemFree", 0)) + info.get("SwapFree", 0)) / 2**30
        except (OSError, ValueError):
            return None
    if sys.platform == "darwin":
        try:
            import re, subprocess
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+) bytes", out).group(1))
            pages = sum(int(n) for k, n in re.findall(r"Pages (free|inactive|speculative|purgeable):\s+(\d+)", out))
            swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"free = ([\d.]+)M", swap)
            return pages * page / 2**30 + (float(m.group(1)) / 1024 if m else 0.0)
        except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
            return None
    return None


def check_memory(me, level=2):
    """Raise MemoryShortage before a mesh whose bake would not fit into free memory."""
    need, free = memory_need_gb(original_of(me), level), free_memory_gb()
    if free is not None and need > free:
        raise MemoryShortage(f"not enough free memory for {me.name} ({len(me.polygons):,} faces): needs about "
                             f"{need:.0f} GB, {free:.0f} GB free - close other programs and apply again")



def bake_quality(me):
    return BAKE_QUALITY if len(me.polygons) <= QUALITY_FACE_LIMIT else BAKE_QUALITY_LARGE


def copies_by_level(orig):
    return {int(m.get("rb_level", 0)): m for m in all_copies(orig)}


def missing_levels(orig, view, render):
    have = copies_by_level(orig)
    return sorted(lv for lv in {view, render} - {0} if lv not in have)


def up_to_date(orig, view, render):
    """The copies of this mesh for the viewport and render level exist and come from the current rules,
    variant and method - Apply can skip the mesh (user, 2026-09-28). Copies made before 1.0.0 carry no
    rules version and are converted again."""
    have = copies_by_level(orig)
    need = {lv for lv in (view, render) if lv}
    if not need or any(lv not in have for lv in need):
        return False
    return all(have[lv].get("rb_rules") == RULES_VERSION and have[lv].get("rb_variant") == SHADING
               and (have[lv].get("rb_method") == "weld") == (METHOD == "weld") for lv in need)


def bake_levels(orig, levels):
    """Bake further copies of an already processed mesh - the creases are on the original,
    so no rules run: only the subdivision (variant of the existing copies)."""
    global SHADING
    have = copies_by_level(orig)
    variant = next((m.get("rb_variant") for m in have.values() if m.get("rb_variant")), SHADING)
    if METHOD == "weld" and (not have or any(m.get("rb_method") == "weld" for m in have.values())):
        keep, SHADING = SHADING, variant       # weld copies: the creases live only in the welded copy
        try:
            made, _ = _bake_weld(orig, levels)
        finally:
            SHADING = keep
        for lv, cp in made.items():
            cp.name = f"{orig.name} L{lv}"
        return made
    keep, SHADING = SHADING, variant
    work = work_object(orig)
    made = {}
    try:
        add_subsurf(work)
        if variant == "geometric":
            E = {i for i, d in enumerate(orig.attributes["crease_edge"].data) if d.value > 0}
            geometric_shading(work, orig, E)
        for lv in levels:
            made[lv] = bake_copy(orig, work, lv)
            made[lv].name = f"{orig.name} L{lv}"
    finally:
        bpy.data.objects.remove(work)
        drop_work_scene()
        SHADING = keep
    return made


def set_levels(orig, view, render, obs=None):
    """Viewport / render level of a processed mesh: bake what is missing, point the links
    (all objects of this mesh unless `obs` is given; switched-off ones stay off), drop
    copies of other levels that nothing uses. Returns the number of copies baked."""
    missing = missing_levels(orig, view, render)
    if missing:
        bake_levels(orig, missing)
    have = copies_by_level(orig)
    orig["rb_view"] = have[view].name if view else ""
    orig["rb_render"] = have[render].name if render else ""
    if obs is None:
        obs = [o for o in bpy.data.objects if o.type == 'MESH' and original_of(o.data) == orig]
    point_links([o for o in obs if not o.get("rb_off")], orig, "view")
    keep = {have[lv] for lv in (set(PRE_LEVELS) | {view, render}) if lv in have}
    drop_copies(orig, keep)
    return len(missing)


# ---- up to add-on 1.3: masters, instances and per-object modifiers (removed on Apply)
MASTER_COLL = "Renderbricks Masters"
MOD_INST = "Renderbricks Instance"
OLD_MODS = ("Subdivision", "Mecabricks Subdiv", "Mecabricks Smooth", "Smooth After Subdiv")


def find_master(me):
    coll = bpy.data.collections.get(MASTER_COLL)
    return next((o for o in coll.objects if o.data == me), None) if coll else None


def is_master(ob):
    coll = bpy.data.collections.get(MASTER_COLL)
    return bool(coll) and ob.name in coll.objects


def unlink_instance(ob):
    for name in (MOD_INST,) + OLD_MODS:
        if ob.modifiers.get(name):
            ob.modifiers.remove(ob.modifiers[name])


def remove_master(me):
    m = find_master(me)
    ng = bpy.data.node_groups.get(f"RB Instance {me.name}")
    if ng:
        bpy.data.node_groups.remove(ng)
    if m:
        bpy.data.objects.remove(m)
    coll = bpy.data.collections.get(MASTER_COLL)
    if coll and not coll.objects:
        bpy.data.collections.remove(coll)


def self_intersecting(cos):
    """Polygon whose edges cross each other (bowtie quads in the import, run 29: Technic
    panels 87080/87086/64391/64683 of the Porsche). Checked in the polygon's own plane."""
    n = len(cos)
    if n < 4:
        return False
    nrm = max(((cos[(i + 1) % n] - cos[i]).cross(cos[(i + 2) % n] - cos[(i + 1) % n]) for i in range(n)),
              key=lambda v: v.length)
    if nrm.length < 1e-12:
        return False
    ax = nrm.normalized().orthogonal().normalized(); ay = nrm.normalized().cross(ax)
    P = [Vector((c.dot(ax), c.dot(ay))) for c in cos]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                      # adjacent through the wrap-around
            if intersect_line_line_2d(P[i], P[(i + 1) % n], P[j], P[(j + 1) % n]):
                return True
    return False

_broken = {}

def broken_faces(me):
    """K11: faces of the import without a meaningful normal – zero area or self-intersecting.
    The fold check skips them: their subdivision folds because the original does."""
    key = (me.as_pointer(), len(me.polygons), len(me.vertices))
    if key not in _broken:
        co = [v.co.copy() for v in me.vertices]
        _broken.clear()
        _broken[key] = {p.index for p in me.polygons
                        if p.area <= DEGENERATE_AREA or self_intersecting([co[i] for i in p.vertices])}
    return _broken[key]

def sub_offsets(me):
    """Start index of each original face's children in the evaluated mesh (level LEVELS)."""
    sizes = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", sizes)
    return np.concatenate(([0], np.cumsum(sizes * 4 ** (LEVELS - 1))))

def flipped_faces(ob, ev=None, me=None):
    """Original face indices whose subdivided children flip (> 90 deg).
    Vectorised (run 30): the same test as the old face-by-face loop, on arrays.
    ev: an evaluated or baked subdivided mesh; me: its original (default ob.data)."""
    me = me or ob.data
    skip = broken_faces(me)
    own = ev is None
    if own:
        dg = depsgraph_of(ob)
        oe = ob.evaluated_get(dg)
        ev = oe.to_mesh()
    starts = sub_offsets(me)
    n, m = len(me.polygons), len(ev.polygons)
    assert starts[-1] == m, (int(starts[-1]), m)
    on = np.empty(n * 3); me.polygons.foreach_get("normal", on)
    en = np.empty(m * 3); ev.polygons.foreach_get("normal", en)
    ea = np.empty(m); ev.polygons.foreach_get("area", ea)
    owner = np.repeat(np.arange(n), np.diff(starts))
    dots = (en.reshape(-1, 3) * on.reshape(-1, 3)[owner]).sum(1)
    bad = set(np.unique(owner[(ea > 1e-12) & (dots < 0.0)]).tolist()) - skip
    if own:
        oe.to_mesh_clear()
    return bad

escalate_faces = {}

FAN_STEPS = (0.2, 0.3, 0.4, 0.5, 0.7, 1.0)   # diagonal crease tried per T fan
FAN_EPS = 0.005    # depth tolerance when comparing a fan's corner crossing with its full-crease value
FAN_W = {}         # edge index -> crease, fixed before the fold loop
FAN_E = set()      # diagonals creased fully (T pinned) where mirroring is not clean

def t_fans(bm):
    """T fans in flat islands: arc vertex t with three interior edges; the two
    diagonals are the interior edges of the faces that hold the arc edges."""
    flat = {}
    for kind, comp, _ in classify(bm):
        if kind in ("flat", "flat-round"):
            for f in comp:
                flat[f.index] = comp
    out = []
    for t in bm.verts:
        inner = [e for e in t.link_edges if not e.is_boundary]
        arcs = [e for e in t.link_edges if e.is_boundary]
        if not (t.is_boundary and is_round(t) and len(inner) == 3 and len(arcs) == 2):
            continue
        if any(f.index not in flat for f in t.link_faces):
            continue
        diags = [next((e for e in ae.link_faces[0].edges if e in inner), None) for ae in arcs]
        if None not in diags:
            out.append((t, diags, flat[t.link_faces[0].index]))
    return out

def fan_corner_depth(me, ev, fan, starts):
    """How deep sub-edges near the fan cross the island's straight outline."""
    from mathutils.geometry import intersect_line_line_2d
    t, diags, comp = fan
    compset = set(comp)
    near = {f for f in t.link_faces}
    for _ in range(2):
        near |= {g for f in list(near) for e in f.edges for g in e.link_faces if g in compset}
    nrm = comp[0].normal
    ax1 = nrm.orthogonal().normalized(); ax2 = nrm.cross(ax1)
    to2 = lambda co: Vector((co @ ax1, co @ ax2))
    outline = [(to2(e.verts[0].co), to2(e.verts[1].co)) for f in near for e in f.edges
               if e.is_boundary and not (is_round(e.verts[0]) or is_round(e.verts[1]))]
    sub = set()
    for fi in {f.index for f in near}:               # only the fan's faces (run 30: no scan of the whole mesh)
        for q in ev.polygons[int(starts[fi]):int(starts[fi + 1])]:
            vs = list(q.vertices)
            for i in range(len(vs)):
                sub.add(tuple(sorted((vs[i], vs[(i + 1) % len(vs)]))))
    depth = 0.0
    for a, b in sub:
        pa, pb = to2(ev.vertices[a].co), to2(ev.vertices[b].co)
        for oa, ob_ in outline:
            x = intersect_line_line_2d(pa, pb, oa, ob_)
            if x is None or min((x - q).length for q in (pa, pb, oa, ob_)) <= 1e-4:
                continue
            d = ob_ - oa
            n2 = Vector((-d.y, d.x)).normalized()
            depth = max(depth, min(abs((pa - oa).dot(n2)), abs((pb - oa).dot(n2))))
    return depth

def resolve_fans(me, ob):
    """F0: T fans in flat islands get a diagonal crease only where it helps.
    Every fan is evaluated at w = 0 and at each FAN_STEPS value. A fan is
    creased if it folds at w = 0, or if creasing lowers its corner crossing
    (depth at 0 > depth at 1.0 + FAN_EPS); it then gets the lowest w without
    fold whose depth is within FAN_EPS of the full-crease depth. Crossings that
    do not react to the crease come from elsewhere (gear axle hole) and are
    left alone. 48452 upper T: 0.054 -> clean at 0.3; 48168 lower T: folds,
    clean at 0.4."""
    FAN_W.clear(); FAN_E.clear()
    bm = bmesh.new(); bm.from_mesh(me)
    fans = t_fans(bm)
    if not fans:
        bm.free()
        return 0, 0
    table = {i: {} for i in range(len(fans))}          # i -> w -> (folds, depth)
    starts = sub_offsets(me)

    def trial(w):
        PARTIAL.clear()
        E, V, _ = rule_creases(bm, {})
        if w > 0:
            for t, diags, comp in fans:
                for e in diags:
                    PARTIAL[e.index] = w
        unify_seams(bm, E, V)
        write_creases(me, E, V); me.update()
        dg = depsgraph_of(ob); oe = ob.evaluated_get(dg); ev = oe.to_mesh()
        bad = flipped_faces(ob, ev)
        for i, fan in enumerate(fans):
            table[i][w] = (any(f.index in bad for f in fan[0].link_faces), fan_corner_depth(me, ev, fan, starts))
        oe.to_mesh_clear()

    # w = 0 and w = 1 decide every fan; the strengths in between only matter for a
    # fan whose full crease folds (run 30: 7 evaluations -> 2, same result)
    trial(0.0); trial(1.0)
    if any((table[i][0.0][0] or table[i][0.0][1] > table[i][1.0][1] + FAN_EPS) and table[i][1.0][0]
           for i in range(len(fans))):
        for w in FAN_STEPS[:-1]:
            trial(w)
    creased = unresolved = 0
    for i, (t, diags, comp) in enumerate(fans):
        f0, d0 = table[i][0.0]
        f1, d1 = table[i][1.0]
        if not (f0 or d0 > d1 + FAN_EPS):
            continue                                    # crease would not help
        pick = 1.0 if not f1 else next(         # f1 clean: w = 1.0 itself qualifies
            (w for w in FAN_STEPS if not table[i][w][0] and table[i][w][1] <= d1 + FAN_EPS), None)
        if pick is None:
            unresolved += 1; continue
        # can the partial crease be mirrored cleanly? Only if every other vertex
        # at the T position has exactly one interior edge (else R8 pins the T
        # group anyway and the mirrored crease runs on as a chain of points
        # through the rings below: 48168, run 20). Then: diagonal 1.0, T pinned.
        # a partial crease would have to be mirrored onto the partner's edge,
        # and that edge's far end sits on the next ring: the crease runs on
        # as a chain of points through the whole hole (48168, run 20). So the
        # diagonal is creased fully; the T group is pinned (one point, no chain).
        FAN_E.update(e.index for e in diags)
        creased += 1
    bm.free()
    return creased, unresolved

# ================================================================ rules 3.0: weld (runs 48-50)
SEAM_SHARP = 10.0        # dihedral at a former island boundary from which it stays hard
PLANE_RATIO = float(opt("--plane-ratio", "8"))     # W13: plane / face-across area ratio (0: off), run 58
PLANE_MIN_ANGLE = 10.0   # W13: only outline edges bending at least this much
PLANE_EDGES = [0]        # W13 counter (diagnostics)
PLANE_DEBUG = False
EXCLUDE_PLANE = []       # W13 released around these folding faces: (centre, reach), run 58
UV_SMOOTH = opt("--uv-smooth", "PRESERVE_BOUNDARIES")   # Subdivision modifier uv_smooth: Keep Boundaries (run 58)
UV_PROJECT = opt("--uv-project", "0") == "1"   # UVs from the original triangles - tested, off (run 58: distorts lettering)
UV_CHUNK = 2_000_000     # corners per step of the UV projection
INNER_SHARP = float(opt("--inner-sharp", "85"))   # inner island edge creased from this dihedral (W12, run 57)
ORGANIC_CORNER = 60.0    # corner bend on organic (all-curved) surfaces, run 53
DESIGN_TURN = 20.0       # W15 (run 73): designed corner - long crease edge into a short one ...
DESIGN_RATIO = 4.0       # ... edge lengths at least this far apart
DESIGN_EDGES = [0]       # W15b edges creased (count for the report)
MECH_FLAT = 0.12         # W15 on organic spots only on parts with at least this share of not curved area
LAST_FLAT_SHARE = [0.0]  # area share of the not curved islands of the last welded mesh
DESIGN_LOG = None        # a list: (mesh, position, turn) of every designed corner (scans, run 73)
WEDGE_SEAM = 30.0        # seam of a thin wedge island creased from this dihedral (run 56; a general 30 deg
                         # threshold for curved islands, run 54, moved Technic parts by up to 0.32)
SPIKE_TURN = 150.0       # outline turn from which an island corner is the tip of a thin wedge, run 54
WEDGE_TIP = SPIKE_TURN   # W4 ignores wedge tips from this turn (run 54)
WEDGE_SEAM_TIP = SPIKE_TURN   # islands with such a tip are wedges for WEDGE_SEAM (run 56)
GROOVE_TURN = SPIKE_TURN      # hairpin of a crease chain on organic shapes = groove end (run 55)
RING_MIN = 6             # walls in a ring that count as a cylinder
RING_MAX_ANGLE = 61.0
RING_STEPS = 200000       # ring search budget per mesh
RELIEF_H = 0.5           # relief tip: edge shorter than this
RELIEF_FACE = 1.0        # ... between wall faces whose longest edge is shorter than this
TIP_DEBUG = None           # a list collects the relief tips (diagnosis)
TIP_TURN_MAX = 80.0       # ... and less than this: right-angled ends are designed box corners
                          # (pistol 95199 rib ends 80-100 deg; mane tips 59-76 deg - watch this margin)
TIP_TURN = 45.0           # ... and the relief edge bends by at least this at both ends (run 54:
                          # zigzag tips of the mane 61-76 deg, circular rib outlines of pistol 95199 22 deg)
BULGE_MAX = 0.2          # a freed relief tip may move the surface by this share of the step height
BULGES = []
RUNG_CREASE = 0.0         # crease of a relief tip edge (0: fully smooth, run 48e)
P = lambda co: tuple(round(x, 4) for x in co)


RINGS = []
EXCLUDE_RUNG = set()     # relief tips that bulged (midpoints), see bulge_check
REPAIR_PASSES = 4
FLUSH_FACES = 2_000_000  # a worker writes its copies away after this many copy faces (run 61)
WORKER_WAIT = 20         # seconds a worker waits for free memory (after writing its copies away) before
                         # it retires; its remaining meshes are done by the parent at the end. Up to
                         # 2026-09-28 it waited 600 s per mesh: all workers of Italian Riviera (converted
                         # scene, commit memory full) waited for each other, the run stood still (user)
JOB_GB = 6.0             # free memory per worker Blender of a parallel headless run (run 59)
orig_name = [""]


def weld(orig):
    orig_name[0] = orig.name
    bm = bmesh.new(); bm.from_mesh(orig)
    bm.faces.ensure_lookup_table()
    global GEOM_CACHE
    GEOM_CACHE = None
    isl = bm.faces.layers.int.new("rb_island")     # before classify: a new layer reallocates the faces
    kinds = classify(bm)
    kind_of = {}
    for n, (kind, comp, _) in enumerate(kinds):
        kind_of[n] = kind
        for f in comp:
            f[isl] = n
    # share of the area in islands that are not curved: a mechanical part with round surfaces
    # (tire 2515: hub, side wall) against an organic one (hair: almost all curved), W15 (run 73)
    area_all = sum(f.calc_area() for f in bm.faces) or 1.0
    flat_share = sum(f.calc_area() for f in bm.faces if kind_of[f[isl]] != "curved") / area_all
    LAST_FLAT_SHARE[0] = flat_share
    interior = {frozenset((P(e.verts[0].co), P(e.verts[1].co))) for e in bm.edges if len(e.link_faces) == 2}
    # sharp corners of the island outlines (the rules' is_sharp) - they stay corners after
    # welding (run 50: 54200, a corner where three islands meet almost tangentially lost all
    # creases and the surface around it curled by 0.29)
    # Tips of thin wedge islands (turn >= SPIKE_TURN) do not count: welded into a smooth
    # surface they are no corner (hair 13768: a 163 deg wedge tip pinned the corner of the
    # face opening, the welded edge bends only 29 deg there, run 54)
    # A wedge tip only counts as such where it lies inside a smooth outline: the other islands
    # at that point exist and all bend less than SHARP_TURN (hair 13768: 10/23 deg). On Technic
    # parts the neighbours at wedge tips are real corners (92/93 deg) or other wedges (147/160
    # deg) - treating those as smooth moved 87408, 64680, 11950, 15407 by up to 0.21 (run 56).
    at_pos = defaultdict(list)
    for v in bm.verts:
        if v.is_boundary:
            at_pos[P(v.co)].append(v)
    def smooth_wedge_tip(v):
        if (turn(v) or 0) < SPIKE_TURN:
            return False
        others = [w for w in at_pos[P(v.co)] if w is not v]
        return bool(others) and all((turn(w) or 0) < SHARP_TURN for w in others)
    wedge_tips = {v for v in bm.verts if v.is_boundary and smooth_wedge_tip(v)}
    wedge_tip_pos = {P(v.co) for v in wedge_tips}
    sharp_pos = {P(v.co): turn(v) for v in bm.verts if v.is_boundary and is_sharp(v)
                 and not ((turn(v) or 0) >= WEDGE_TIP and P(v.co) in wedge_tip_pos)}
    # thin wedge islands (a smooth wedge tip, see above): their weak seams (< WEDGE_SEAM) stay
    # smooth - on hair 13768 a 29 deg seam of such a wedge made a third crease and so a corner;
    # a general 30 deg seam threshold moved Technic parts by up to 0.32 (run 56)
    wedge_isl = {f[isl] for v in wedge_tips if (turn(v) or 0) >= WEDGE_SEAM_TIP for f in v.link_faces}
    nf = len(bm.faces)
    fi = bm.faces.layers.int.new("rb_fi")
    for f in bm.faces:
        f[fi] = f.index
    snap = bm.copy()
    skip = set()           # positions not welded: faces that would become duplicates (4973)
    # weld only along seams: an open edge whose two end points coincide with those of another
    # open edge. A vertex that merely touches another sheet (54200: the foot of the body rests
    # on the ledge and shares one corner point) stays apart - welding that single point tied
    # two separate surfaces together and notched the edge (run 50d)
    from collections import Counter as _C
    ekey = lambda e: frozenset((P(e.verts[0].co), P(e.verts[1].co)))
    ecount = _C(ekey(e) for e in bm.edges if e.is_boundary)
    on_seam = {P(v.co) for e in bm.edges if e.is_boundary and ecount[ekey(e)] > 1 for v in e.verts}
    for attempt in range(4):
        bnd = [v for v in bm.verts if v.is_boundary and P(v.co) not in skip and P(v.co) in on_seam]
        tm = bmesh.ops.find_doubles(bm, verts=bnd, dist=MERGE_DIST)["targetmap"]
        # never weld two corners of one face (sliver faces would collapse): neither a vertex
        # onto another corner of its face, nor two corners of one face onto the same target
        # (run 50: NINJAGO lost a corner, 1,472 -> 1,448 loops)
        tm = {v: t for v, t in tm.items() if not (set(v.link_faces) & set(t.link_faces))}
        changed = True
        while changed:
            changed = False
            # in face order: a set of BMFaces iterates by memory address, so which corner kept
            # its weld depended on what the process had done before (run 59: 2343 in NINJAGO
            # had 1498 / 1499 / 1502 vertices in a worker, the serial build and alone)
            for f in sorted({f for v in tm for f in v.link_faces}, key=lambda f: f.index):
                tgt = [tm.get(v, v) for v in f.verts]
                if len(set(tgt)) < len(tgt):
                    for v in f.verts:
                        if v in tm and tgt.count(tm[v]) > 1:
                            del tm[v]; changed = True
        bmesh.ops.weld_verts(bm, targetmap=tm)
        if len(bm.faces) == nf:
            break
        lost = set(range(nf)) - {f[fi] for f in bm.faces}
        snap.faces.ensure_lookup_table()
        skip |= {P(v.co) for i in lost for v in snap.faces[i].verts}
        bm.free(); bm = snap.copy()
        isl = bm.faces.layers.int.get("rb_island"); fi = bm.faces.layers.int.get("rb_fi")
    assert len(bm.faces) == nf, (orig.name, nf, len(bm.faces))
    assert sum(len(f.verts) for f in bm.faces) == len(orig.loops), (orig.name, "corners lost")
    snap.free()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    bm.verts.index_update(); bm.edges.index_update(); bm.faces.index_update()

    E, seams, cand = set(), set(), []
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) > 2:
            E.add(e); seams.add(e); continue
        if len(lf) != 2:
            continue
        a, b = lf[0][isl], lf[1][isl]
        d = math.degrees(lf[0].normal.angle(lf[1].normal, 0.0))
        seam = a != b or frozenset((P(e.verts[0].co), P(e.verts[1].co))) not in interior
        if not seam:
            if kind_of[a] == "logo" and d > LOGO_CREASE_ANGLE:
                E.add(e)
            continue
        seams.add(e)
        # a seam of a thin wedge island is a hard edge only from WEDGE_SEAM (hair 13768: a 29 deg
        # seam made a third crease at the corner of the face opening, run 54/56)
        limit = WEDGE_SEAM if (a in wedge_isl or b in wedge_isl) else SEAM_SHARP
        if d >= limit:
            cand.append((e, d, a, b))
    # ring rule on flat patches (faces joined across non-seam edges within 1 deg): the
    # nostril recess of 10509a4 is one island whose six wall faces meet at slits
    patch, npatch = {}, 0
    for f in bm.faces:
        if f in patch:
            continue
        stack = [f]; patch[f] = npatch
        while stack:
            g = stack.pop()
            for e in g.edges:
                if e in seams:
                    continue
                for h in e.link_faces:
                    if h not in patch and math.degrees(h.normal.angle(f.normal, 0.0)) < 1.0:
                        patch[h] = npatch; stack.append(h)
        npatch += 1
    # ring search: walk from patch to patch over seams of the same angle (+-1 deg); the
    # patch normals must keep the same angle to the axis the first three define (+-1 deg);
    # back at the start after >= RING_MIN patches = polygonised cylinder or cone
    pn, pfaces_r = {}, defaultdict(list)
    for f, k in patch.items():
        pn.setdefault(k, f.normal.copy())
        pfaces_r[k].append(f)
    link = defaultdict(list)
    for e, d, _, _ in cand:
        a, b = patch[e.link_faces[0]], patch[e.link_faces[1]]
        if a != b and d <= RING_MAX_ANGLE:
            link[frozenset((a, b))].append((e, d))
    nbrs = defaultdict(list)
    for pr, lst in link.items():
        x, y = tuple(pr)
        d = sum(dd for _, dd in lst) / len(lst)
        nbrs[x].append((y, d)); nbrs[y].append((x, d))
    ring, done = set(), set()
    def angle_ok(path, axis, cand_p):
        if axis is None:
            return True
        ref = math.degrees(pn[path[0]].angle(axis, 0.0))
        return abs(math.degrees(pn[cand_p].angle(axis, 0.0)) - ref) <= 1.0
    steps = [0]
    def walk(path, d0, axis):
        steps[0] += 1
        if len(path) > 64 or steps[0] > RING_STEPS:       # bounded search (large meshes)
            return None
        last = path[-1]
        for q, d in nbrs[last]:
            if abs(d - d0) > 1.0:
                continue
            if q == path[0] and len(path) >= RING_MIN:
                return path
            if q in path:
                continue
            ax = axis
            if ax is None and len(path) >= 2:
                c3 = (pn[path[-2]] - pn[last]).cross(pn[last] - pn[q])
                if c3.length < 1e-6:
                    continue
                ax = c3.normalized()
            if not angle_ok(path, ax, q):
                continue
            r = walk(path + [q], d0, ax)
            if r:
                return r
        return None
    for x in list(nbrs):
        if x in done:
            continue
        for y, d0 in nbrs[x]:
            r = walk([x, y], d0, None)
            if r:
                cyc = set(r)
                done |= cyc
                # only recesses and holes (walls facing the axis: nostril, pin holes); a convex
                # ring is a designed polygon - the facets of the diamond 30153 (run 50: +0.46)
                cen = {k: sum((f.calc_center_median() for f in pfaces_r[k]), Vector()) / len(pfaces_r[k]) for k in cyc}
                mid = sum(cen.values(), Vector()) / len(cen)
                if not all(pn[k].dot(cen[k] - mid) < 0 for k in cyc):
                    RINGS.append((orig_name[0], len(cyc), round(d0, 1), "convex - kept"))
                    break
                # W5b (run 75): six walls bending by 60 deg = a regular planar hexagon, a designed
                # hex socket (box wrench 11402p2, Coppersteam), no polygonised circle - the horse
                # nostril is six walls at 42 deg (a cone), Mecabricks' small round holes are 8+
                if len(cyc) == 6 and abs(d0 - 60.0) <= 1.0:
                    RINGS.append((orig_name[0], len(cyc), round(d0, 1), "hexagon - kept"))
                    break
                es = [(e, dd) for pr, lst in link.items() if pr <= cyc for e, dd in lst]
                ring |= {e for e, _ in es}
                RINGS.append((orig_name[0], len(cyc), round(d0, 1)))
                break
    E |= {e for e, _, _, _ in cand if e not in ring}
    # flat stays flat (as R2 of the rules): a flat island without round outline gets all its
    # inner edges creased - left free, its open edges curled inward (run 50: 54200 0.29)
    # degenerate faces of the import (zero area: two corners at one point, 54200 faces 21/35
    # beside the foot of the body): inert - all edges creased, corners pinned (run 50e)
    degen = [f for f in bm.faces if f.calc_area() <= DEGENERATE_AREA]
    E |= {e for f in degen for e in f.edges}
    degen_v = {v for f in degen for v in f.verts}
    flat_isl = {n for n, k in kind_of.items() if k == "flat"}
    E |= {e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0][isl] == e.link_faces[1][isl]
          and e.link_faces[0][isl] in flat_isl}
    # steep inner edges (W12, run 57): Mecabricks left a right angle inside one island (35787:
    # the two walls of the recess corner share an edge, imported normals smooth across it) -
    # left free, subdivision rounds the corner off by 1.4. No tessellated curve bends this much.
    E |= {e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0][isl] == e.link_faces[1][isl]
          and math.degrees(e.calc_face_angle(0)) >= INNER_SHARP}
    # plane beside a bevel (W13, run 58): Mecabricks models rounded edges as a strip of narrow
    # faces in one island with the large plane faces beside them (86209). Left free, the
    # subdivision pulls the rounding far into the planes - the bevel grows and the part shrinks.
    # A planar patch of the island (normals within FLAT_MAX_ANGLE) much larger than the face
    # across its outline gets that outline edge creased; the bevel then rounds within its width.
    if PLANE_RATIO:
        patch, parea = {}, {}
        for f in bm.faces:
            if f in patch:
                continue
            k = len(parea); stack, n0 = [f], f.normal.copy(); patch[f] = k; parea[k] = 0.0
            while stack:
                g = stack.pop(); parea[k] += g.calc_area()
                for e in g.edges:
                    if len(e.link_faces) != 2:
                        continue
                    h = e.link_faces[0] if e.link_faces[1] is g else e.link_faces[1]
                    if h not in patch and h[isl] == g[isl] and math.degrees(n0.angle(h.normal, 0.0)) <= FLAT_MAX_ANGLE:
                        patch[h] = k; stack.append(h)
        for e in bm.edges:
            if e in E or len(e.link_faces) != 2:
                continue
            f, g = e.link_faces
            if f[isl] != g[isl] or patch[f] == patch[g] or math.degrees(e.calc_face_angle(0)) < PLANE_MIN_ANGLE:
                continue
            if any((v.co - cx).length <= rx for cx, rx in EXCLUDE_PLANE for v in e.verts):
                continue
            if any(parea[patch[x]] >= PLANE_RATIO * max(parea[patch[y]], 1e-9) for x, y in ((f, g), (g, f))):
                E.add(e); PLANE_EDGES[0] += 1
                if PLANE_DEBUG: print('PLANEEDGE', [tuple(round(x, 3) for x in v.co) for v in e.verts], round(math.degrees(e.calc_face_angle(0)), 1), round(parea[patch[f]], 3), round(parea[patch[g]], 3))
    ringv = {v for e in ring for v in e.verts}
    # relief tips (run 48e, zigzag mane of 10509a4): a short creased edge (< RELIEF_H)
    # between two small wall faces (longest edge < RELIEF_FACE), both ends corners of three
    # creased edges, the other faces at both ends in curved islands - the tip of a low
    # relief step. It stays smooth and its ends get no pin: the tip rounds off, the step
    # stays crisp along its length.
    def small(f):
        return max(e.calc_length() for e in f.edges) < RELIEF_FACE
    def ncreased(v):
        return sum(1 for x in v.link_edges if x in E)
    def tip_bend(v, e):
        o = [x for x in v.link_edges if x in E and x is not e]
        if len(o) != 2:
            return 0.0
        a = o[0].other_vert(v).co - v.co; b = o[1].other_vert(v).co - v.co
        return 180.0 - math.degrees(a.angle(b)) if a.length > 1e-9 and b.length > 1e-9 else 0.0
    rung = set()
    for e in E:
        if len(e.link_faces) != 2 or not 1e-6 < e.calc_length() < RELIEF_H or not all(small(f) for f in e.link_faces):
            continue
        if not all(ncreased(v) == 3 for v in e.verts):
            continue
        # a tip of a zigzag: at both ends the relief edge (the two other creased edges) bends by
        # at least TIP_TURN - where it runs on straight, the step ends on a hard line (the ribs
        # of the pistol 95199 end on the straight edge of the bar below: must stay hard, run 54)
        if not all(TIP_TURN <= tip_bend(v, e) < TIP_TURN_MAX for v in e.verts):
            continue
        others = {f for v in e.verts for f in v.link_faces} - set(e.link_faces)
        if (others and all(kind_of[f[isl]] == "curved" for f in others)
                and P((e.verts[0].co + e.verts[1].co) / 2) not in EXCLUDE_RUNG):
            rung.add(e)
            if TIP_DEBUG is not None:
                TIP_DEBUG.append((orig.name, tuple(round(x, 2) for x in (e.verts[0].co + e.verts[1].co) / 2),
                                  round(e.calc_length(), 3), [round(tip_bend(v, e)) for v in e.verts],
                                  [[round(x.calc_length(), 2) for x in v.link_edges if x in E and x is not e]
                                   for v in e.verts]))
    E -= rung
    tipv = {v for e in rung for v in e.verts}
    tip_faces = sorted({f.index for e in rung for f in e.link_faces})
    # islands of a ring are round now: their faces get smooth normals instead of the
    # imported per-wall normals, the ring edges are not sharp (nostril, run 48b)
    ring_isl = {f[isl] for e in ring for f in e.link_faces}
    ring_faces = [f.index for f in bm.faces if f[isl] in ring_isl]

    # corner vertices on crease chains, K3/K3b of the rules applied to the chains
    CE = set(E) | {e for e in bm.edges if len(e.link_faces) == 1}
    # organic shapes (every face at the vertex in a curved island: hair, mane) are rounded
    # coarsely - a bend counts as a corner from ORGANIC_CORNER only; bricks keep SHARP_TURN
    # (run 53: the face opening of hair 13768 stayed angular at 47 deg on the left)
    def organic(v):
        return bool(v.link_faces) and all(kind_of[f[isl]] == "curved" for f in v.link_faces)

    def corner_turn(v):
        return ORGANIC_CORNER if organic(v) else SHARP_TURN

    # on organic shapes a hairpin turn of a crease chain (>= SPIKE_TURN) is the end of a groove
    # or strand, no corner: it stays free and rounds off (tail of 10509a4: the groove between two
    # strands ended in a pinned 161 deg point, P20, run 55)
    def groove_end(v):
        t = tturn(v)
        return t is not None and t >= GROOVE_TURN and organic(v)
    chain = lambda v: [e for e in v.link_edges if e in CE]
    def nb(v):
        return [e.other_vert(v) for e in chain(v)]
    def tturn(v):
        ch = chain(v)
        if len(ch) != 2:
            return None
        p = ch[0].other_vert(v).co - v.co; q = ch[1].other_vert(v).co - v.co
        if p.length < 1e-9 or q.length < 1e-9:
            return None
        return 180.0 - math.degrees(p.angle(q))
    # W15 (run 73): a designed corner - a long straight crease edge turning into a short one
    # (edge lengths >= DESIGN_RATIO apart) that ends at a junction - is a corner from
    # DESIGN_TURN on, also on curved
    # islands: the groove ends of the tire 2515 turned by 27 / 36 deg (11.2 : 1.2 and 10.6 : 2.0)
    # and were rounded off because the tread counts as organic (60 deg). Polygonised arcs have
    # edges of about the same length and stay free (_is_round below as before).
    # The short edge must end at a junction of three or more creased edges: where a straight
    # line runs into a polygonised curve the signature is the same, but the short edge leads on
    # to the next gently turning curve point - pinning that put kinks into 3820v2, 11214 and
    # 98313 of Banana_Mech (first version of W15, run 73).
    # On organic spots (every face curved) only on mechanical parts - at least MECH_FLAT of the
    # area in not curved islands (tire 2515: 0.17): hair (<= 0.10 in Mecabricks_Hairs) keeps the
    # soft corners of run 53 (11908, 13765, 13766 became angular, second version of W15).
    def designed(v, t):
        if t < DESIGN_TURN:
            return False
        a, b = sorted(chain(v), key=lambda e: e.calc_length())
        la, lb = a.calc_length(), b.calc_length()
        if not (la > 1e-9 and lb >= DESIGN_RATIO * la and len(chain(a.other_vert(v))) >= 3):
            return False
        return not organic(v) or flat_share >= MECH_FLAT
    g = globals()
    keep = g["boundary_neighbours"], g["_turn"]
    g["boundary_neighbours"], g["_turn"] = nb, tturn
    try:
        V = {v for v in bm.verts if len(chain(v)) == 2 and v not in ringv and v not in tipv
             and (t := tturn(v)) is not None and (t > corner_turn(v) or designed(v, t))
             and not _is_round(v) and not groove_end(v)}
    finally:
        g["boundary_neighbours"], g["_turn"] = keep
    # W15b: a bend (>= DESIGN_TURN) between two corners, one of them a designed corner, is
    # creased as well - with both ends pinned its rounding bulged into a wedge (run 73)
    Vd = {v for v in V if (t := tturn(v)) is not None and not t > corner_turn(v)}
    if DESIGN_LOG is not None:
        DESIGN_LOG.extend((orig.name, tuple(round(c, 3) for c in v.co), round(tturn(v), 1)) for v in Vd)
    for v in Vd:
        for e in v.link_edges:
            if (e not in E and len(e.link_faces) == 2 and e.other_vert(v) in V
                    and math.degrees(e.calc_face_angle(0)) >= DESIGN_TURN):
                E.add(e); DESIGN_EDGES[0] += 1
    V |= {v for v in bm.verts if P(v.co) in sharp_pos and (sharp_pos[P(v.co)] or 180) > corner_turn(v)
          and v not in ringv and v not in tipv and not groove_end(v)
          and sum(1 for e in v.link_edges if e in E) < 3}
    V |= degen_v

    # T vertices: open vertex on the inside of another open edge
    tv = []
    be = [e for e in bm.edges if len(e.link_faces) == 1]
    bv = [v for v in bm.verts if v.is_boundary]
    if be and bv:
        # KD tree over the open vertices; each open edge asks for the vertices within its
        # half length around its middle (run 49: one pass over all edges per vertex was
        # quadratic - the NINJAGO baseplate has ~100k open vertices)
        from mathutils import kdtree
        kd = kdtree.KDTree(len(bv))
        for v in bv:
            kd.insert(v.co, v.index)
        kd.balance()
        bm.verts.ensure_lookup_table()
        for e in be:
            a, b = e.verts[0].co, e.verts[1].co
            ab = b - a; L = ab.length
            if L < 1e-9:
                continue
            for co, vi, _ in kd.find_range((a + b) / 2, L / 2 + MERGE_DIST):
                v = bm.verts[vi]
                if v in e.verts:
                    continue
                t = (co - a).dot(ab) / (L * L)
                if 1e-3 < t < 1 - 1e-3 and (a + ab * t - co).length < MERGE_DIST:
                    tv.append((vi, e.link_faces[0].index))

    # open points that stay apart - unwelded coincident vertices and T vertices with the ends
    # of their host edge - are pinned on every side, so both sides stay on the original
    # outline and cannot drift apart (run 50f: 4973 cracked at an unwelded point)
    bm.verts.ensure_lookup_table()
    opos = defaultdict(list)
    for v in bm.verts:
        if v.is_boundary:
            opos[P(v.co)].append(v)
    V |= {v for g in opos.values() if len(g) > 1 for v in g}
    bm.faces.ensure_lookup_table()
    for vi, host in tv:
        V.add(bm.verts[vi])
        for e in bm.faces[host].edges:
            if e.is_boundary and (bm.verts[vi].co - (e.verts[0].co + e.verts[1].co) / 2).length <= e.calc_length() / 2 + MERGE_DIST:
                V |= set(e.verts)
    wm = bpy.data.meshes.new(f"{orig.name} RBweld")
    bm.to_mesh(wm)
    for m in orig.materials:
        wm.materials.append(m)
    def attr(name, typ, dom, idx, val=1.0):
        at = wm.attributes.get(name) or wm.attributes.new(name, typ, dom)
        n = len(wm.edges) if dom == 'EDGE' else len(wm.vertices)
        vals = [False] * n if typ == 'BOOLEAN' else [0.0] * n
        for i in idx:
            vals[i] = val
        at.data.foreach_set("value", vals)
    attr("crease_edge", 'FLOAT', 'EDGE', [e.index for e in E])
    if rung and RUNG_CREASE > 0:
        ca = wm.attributes["crease_edge"].data
        for e in rung:
            ca[e.index].value = RUNG_CREASE
    attr("crease_vert", 'FLOAT', 'POINT', [v.index for v in V])
    sharp = wm.attributes.get("sharp_edge")
    old = [False] * len(wm.edges)
    if sharp:
        sharp.data.foreach_get("value", old)
    attr("sharp_edge", 'BOOLEAN', 'EDGE', [e.index for e in seams - ring - rung] + [i for i, x in enumerate(old) if x], True)
    ndiff, zero = 0.0, 0
    if orig.has_custom_normals:
        n0 = np.empty(len(orig.loops) * 3); orig.corner_normals.foreach_get("vector", n0)
        nn = n0.reshape(-1, 3).copy()
        smooth_faces = ring_faces       # relief tips keep the imported normals (run 48e: smooth ones darkened the tips)
        if smooth_faces:
            sf = wm.attributes.get("sharp_face")
            for i in smooth_faces:
                p = wm.polygons[i]
                nn[p.loop_start:p.loop_start + p.loop_total] = 0.0     # zero = Blender's smooth normal
                if sf:
                    sf.data[i].value = False
        wm.normals_split_custom_set(nn.tolist())
        n1 = np.empty(len(wm.loops) * 3); wm.corner_normals.foreach_get("vector", n1)
        a0, a1 = n0.reshape(-1, 3), n1.reshape(-1, 3)
        ok = (np.linalg.norm(a0, axis=1) > 0.5) & (np.linalg.norm(a1, axis=1) > 0.5)   # zero normals of slivers
        for i in ring_faces:
            p = wm.polygons[i]
            ok[p.loop_start:p.loop_start + p.loop_total] = False                     # smoothed on purpose
        dots = np.clip((a0 * a1).sum(1)[ok], -1, 1)
        ndiff = float(np.degrees(np.arccos(dots.min()))) if len(dots) else 0.0
        zero = int((~ok).sum())
    rungs_out = [((e.verts[0].co + e.verts[1].co) / 2, e.calc_length()) for e in rung]
    rep = dict(welded=len(tm), seams=len(seams), creased_seams=len(seams & E), ring_edges=len(ring),
               corners=len(V), relief_tips=len(rung), t_verts=len(tv), normals_diff=round(ndiff, 3),
               zero_normals=zero, unwelded=len(skip))
    bm.free()
    rep["_rungs"] = rungs_out
    return wm, tv, rep


def t_gaps(wm, cp, tv, level):
    """Distance of each T vertex's limit position to the limit outline of its host face."""
    if not tv:
        return 0.0
    global LEVELS
    LEVELS = level
    starts = sub_offsets(wm)
    co = np.empty(len(cp.vertices) * 3); cp.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    ev = np.empty(len(cp.edges) * 2, np.int64); cp.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
    le = np.empty(len(cp.loops), np.int64); cp.loops.foreach_get("edge_index", le)
    cnt = np.bincount(le, minlength=len(cp.edges))
    lt = np.empty(len(cp.polygons), np.int64); cp.polygons.foreach_get("loop_total", lt)
    lface = np.repeat(np.arange(len(cp.polygons)), lt)
    owner = np.repeat(np.arange(len(wm.polygons)), np.diff(starts))
    open_loops = cnt[le] == 1
    worst = 0.0
    for vi, host in tv:
        sel = open_loops & (owner[lface] == host)
        es = ev[np.unique(le[sel])]
        if not len(es):
            continue
        a, b = co[es[:, 0]], co[es[:, 1]]; ab = b - a
        p = co[vi]
        t = np.clip(((p - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-18), 0, 1)
        worst = max(worst, float(np.linalg.norm(a + ab * t[:, None] - p, axis=1).min()))
    return worst


def bulge_check(work, wm, rungs):
    """Relief tips that bulge: after subdividing, the surface near a freed tip must stay
    within BULGE_MAX (times the step height) of the original. Returns the tips that bulge."""
    from mathutils.bvhtree import BVHTree
    if not rungs:
        return []
    bvh = BVHTree.FromPolygons([v.co.copy() for v in wm.vertices], [tuple(p.vertices) for p in wm.polygons])
    dg = depsgraph_of(work)
    ev = work.evaluated_get(dg).to_mesh()
    co = np.empty(len(ev.vertices) * 3); ev.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    bad = []
    for mid, L in rungs:
        near = co[np.linalg.norm(co - np.array(mid), axis=1) < 2.0 * L]
        d = max((bvh.find_nearest(Vector(x))[3] or 0.0) for x in near) if len(near) else 0.0
        BULGES.append((wm.name, round(L, 3), round(d, 4), round(d / max(L, 1e-9), 2)))
        if d > BULGE_MAX * L:
            bad.append(mid)
    work.evaluated_get(dg).to_mesh_clear()
    return bad


def repair_folds(work, wm, passes=None):
    """Fold repair as in the rules: edges of folding faces get crease 0.5, then 1.0, then
    the neighbouring faces too. Returns the number of passes used."""
    passes = passes or REPAIR_PASSES
    ce = wm.attributes["crease_edge"].data
    for n in range(passes):
        bad = flipped_faces(work, me=wm)
        if not bad:
            return n
        faces = set(bad)
        if n >= 2:
            ring = set()
            for i in faces:
                vs = set(wm.polygons[i].vertices)
                ring |= {p.index for p in wm.polygons if vs & set(p.vertices)}
            faces |= ring
        val = 0.5 if n == 0 else 1.0
        for i in faces:
            for li in wm.polygons[i].loop_indices:
                e = wm.loops[li].edge_index
                ce[e].value = max(ce[e].value, val)
        wm.update()
    return passes




def weld_work(orig, repair=True):
    """Welded work object of an original mesh with all creases (rules 3.0): weld, bulge check
    of the relief tips (weld again without the tips that bulged), fold repair. Returns (work object, welded mesh, T vertices,
    report); the caller removes object and mesh."""
    EXCLUDE_RUNG.clear(); EXCLUDE_PLANE.clear()
    wm, tv, rep = weld(orig)
    work = bpy.data.objects.new(WORK_NAME, wm)
    link_work(work)
    add_subsurf(work)
    bad = bulge_check(work, wm, rep.pop("_rungs", []))
    if bad:
        EXCLUDE_RUNG.update(P(m) for m in bad)
        bpy.data.objects.remove(work); bpy.data.meshes.remove(wm)
        wm, tv, rep = weld(orig)
        rep.pop("_rungs", None)
        work = bpy.data.objects.new(WORK_NAME, wm)
        link_work(work)
        add_subsurf(work)
    rep["tips_bulged"] = len(bad)
    rep["repair_passes"] = 0
    if repair:
        work, wm, tv, rep = repair_work(orig, work, wm, tv, rep)
    if SHADING == "geometric":
        E = {i for i, d in enumerate(wm.attributes["crease_edge"].data) if d.value > 0}
        geometric_shading(work, wm, E)
    return work, wm, tv, rep


def repair_work(orig, work, wm, tv, rep):
    """Fold repair (W10) and the W13 fallback on a welded work object."""
    rep["repair_passes"] = passes = repair_folds(work, wm)
    # W13 fallback (run 58, Bugatti 35188): plane creases can leave folds the repair cannot
    # remove - weld again without the W13 edges at the folding faces. Folds can only be
    # left when the repair used all its passes (run 59: no extra evaluation otherwise).
    left = flipped_faces(work, me=wm) if PLANE_RATIO and passes >= REPAIR_PASSES else set()
    if left:
        # the crease that makes a face fold may sit a face ring away (35188: 0.35 from it)
        for i in left:
            vs = [wm.vertices[v].co.copy() for v in wm.polygons[i].vertices]
            reach = 2.0 * max((a - b).length for a in vs for b in vs)
            EXCLUDE_PLANE.append((sum(vs, Vector()) / len(vs), reach))
        bpy.data.objects.remove(work); bpy.data.meshes.remove(wm)
        wm, tv, rep2 = weld(orig)
        rep2.pop("_rungs", None)
        rep2["tips_bulged"] = rep["tips_bulged"]
        rep = rep2
        work = bpy.data.objects.new(WORK_NAME, wm)
        link_work(work)
        add_subsurf(work)
        rep["repair_passes"] = repair_folds(work, wm)
        rep["plane_released"] = len(left)
    return work, wm, tv, rep


def _bake_weld(orig, levels, method_rep=None):
    # run 59 tried baking first and checking folds on the copy: 306 of Ratatouille's 667
    # meshes need the repair anyway and were then baked twice - slower (349 -> 396 s)
    work, wm, tv, rep = weld_work(orig)
    try:
        made = {}
        for lv in sorted(levels):
            cp = bake_copy(orig, work, lv)
            cp["rb_method"] = "weld"
            cp["rb_tv"] = [x for pair in tv for x in pair]      # T vertices for the check (vertex, host face)
            made[lv] = cp
    finally:
        bpy.data.objects.remove(work)
        bpy.data.meshes.remove(wm)
        drop_work_scene()
    return made, rep


def process(me, obs):
    """Rules 3.0 (weld, run 48-50): the original stays untouched (no attributes either); a
    temporary welded copy gets the creases and is subdivided into the copies for viewport
    and render, which every link uses. `me` may already be a copy: its original is processed."""
    if METHOD != "weld":
        return process_24(me, obs)
    orig = prepare(me, obs)
    made, rep = _bake_weld(orig, bake_levels_wanted())
    return finish(orig, obs, made, rep)


def prepare(me, obs):
    """The original of `me`, instances and masters of older add-on versions undone."""
    orig = original_of(me)
    for ob in obs:             # up to add-on 1.3: instances / per-object modifiers
        unlink_instance(ob)
    remove_master(orig)
    return orig


def bake_levels_wanted():
    return (set(PRE_LEVELS) | {VIEW_LEVEL, RENDER_LEVEL}) - {0}


def finish(orig, obs, made, rep, check=True):
    """Baked copies {level: mesh} -> old copies replaced, names, links on the view copy.
    Also used for copies baked by a worker process (headless run with --jobs, run 59)."""
    view = made.get(VIEW_LEVEL, orig)
    new = set(made.values())      # by data-block: a copy in the cache file has the same name (run 62)
    for m in [m for m in all_copies(orig) if m not in new]:
        m.user_remap(view)
        bpy.data.meshes.remove(m)
    for lv, cp in made.items():
        cp.name = f"{orig.name} L{lv}"
    orig["rb_view"] = made[VIEW_LEVEL].name if VIEW_LEVEL else ""
    orig["rb_render"] = made[RENDER_LEVEL].name if RENDER_LEVEL else ""
    orig.use_fake_user = True
    point_links(obs, orig, "view")
    rc = made.get(RENDER_LEVEL) or made.get(VIEW_LEVEL)
    if check:              # a worker's report already has it (run 59)
        rep["flipped"] = len(copy_folds(orig, rc)) if rc else 0
    rep["t_fans_creased"], rep["t_fans_unresolved"] = 0, 0   # T points are pinned (rep["t_verts"])
    rep["copies"] = {lv: len(cp.polygons) for lv, cp in made.items()}
    return rep


def weld_gap(orig, cp):
    """Largest T gap of a weld copy (the only places where a welded copy can open)."""
    flat = list(cp.get("rb_tv", []))
    tv = list(zip(flat[0::2], flat[1::2]))
    return t_gaps(orig, cp, tv, int(cp.get("rb_level", LEVELS))) if tv else 0.0


def process_24(me, obs):
    """Creases on the original mesh, then the subdivided copies for viewport and render,
    which every link uses (run 38). `me` may already be a copy: its original is processed.
    The checks run on a temporary work object at the check level LEVELS, with custom
    normals off (face normals only: evaluation twice as fast, run 32)."""
    global GEOM_CACHE
    orig = original_of(me)
    PARTIAL.clear()
    escalate_faces.clear()     # per mesh: island keys are face indices (run 24 fix)
    for ob in obs:             # up to add-on 1.3: instances / per-object modifiers
        unlink_instance(ob)
    remove_master(orig)
    work = work_object(orig)
    try:
        mod = add_subsurf(work)
        mod.use_custom_normals = False
        GEOM_CACHE = {}
        try:
            rep = _process(orig, [work])
        finally:
            GEOM_CACHE = None
        add_subsurf(work)                       # custom normals back for variant A
        if SHADING == "geometric":
            E = {i for i, d in enumerate(orig.attributes["crease_edge"].data) if d.value > 0}
            geometric_shading(work, orig, E)
        levels = (set(PRE_LEVELS) | {VIEW_LEVEL, RENDER_LEVEL}) - {0}      # chosen levels only (run 61)
        made = {lv: bake_copy(orig, work, lv) for lv in sorted(levels)}
    finally:
        bpy.data.objects.remove(work)
        drop_work_scene()
    # older copies: every link still on one of them (also outside `obs`) moves to the new
    # viewport copy - links share the mesh - then they are removed
    view = made.get(VIEW_LEVEL, orig)
    new = set(made.values())      # by data-block: a copy in the cache file has the same name (run 62)
    for m in [m for m in all_copies(orig) if m not in new]:
        m.user_remap(view)
        bpy.data.meshes.remove(m)
    for lv, cp in made.items():
        cp.name = f"{orig.name} L{lv}"
    orig["rb_view"] = made[VIEW_LEVEL].name if VIEW_LEVEL else ""
    orig["rb_render"] = made[RENDER_LEVEL].name if RENDER_LEVEL else ""
    orig.use_fake_user = True                    # stays in the file even when no link uses it
    point_links(obs, orig, "view")
    rep["copies"] = {lv: len(cp.polygons) for lv, cp in made.items()}
    return rep


def copy_folds(orig, cp):
    """Faces of the original whose children in the copy flip (same test as the checks)."""
    global LEVELS
    keep, LEVELS = LEVELS, int(cp.get("rb_level", LEVELS))
    try:
        return flipped_faces(None, cp, orig)
    finally:
        LEVELS = keep


def _process(me, obs):
    merged = 0
    t_fans = 0
    if REPAIR_T:
        # repair T fans only where the plain rules fold
        bm = bmesh.new(); bm.from_mesh(me)
        PARTIAL.clear()
        E, V, _ = rule_creases(bm, {})
        unify_seams(bm, E, V)
        write_creases(me, E, V); me.update()
        bm.free()
        folding = flipped_faces(obs[0])
        if folding:
            t_fans = repair_t_fans(me, folding)
    fans_creased, fans_open = resolve_fans(me, obs[0])
    escalate = {}
    for p in range(1, MAX_PASSES + 1):
        bm = bmesh.new(); bm.from_mesh(me)
        PARTIAL.clear()
        PARTIAL.update(FAN_W)
        E, V, stats = rule_creases(bm, escalate)
        E |= FAN_E
        stats["seam verts pinned"] = unify_seams(bm, E, V)
        write_creases(me, E, V)
        me.update()
        bad = flipped_faces(obs[0])
        if not bad:
            bm.free()
            break
        bm.faces.ensure_lookup_table()
        for kind, comp, _ in classify(bm):
            ids = {f.index for f in comp} & bad
            if ESCALATE == "none" or (ESCALATE == "curved" and kind != "curved"):
                ids = set()
            if ids:
                key = min(f.index for f in comp)
                escalate[key] = escalate.get(key, 0) + 1
                escalate_faces.setdefault(key, set()).update(ids)
        bm.free()
    return dict(merged=merged, t_fans_creased=fans_creased, t_fans_unresolved=fans_open, passes=p, flipped=len(bad), creased_edges=len(E), partial_creases=len(PARTIAL),
                corner_verts=len(V), islands=dict(stats))

def subdiv_node_group():
    """Subdivision + smooth shading in one node modifier: one toggle, no driver
    (a driver reading the object's own modifier toggle forms a dependency cycle).
    The level lives on the Subdivision node itself (modifier inputs cannot be
    set from Python the same way in every Blender version)."""
    ng = bpy.data.node_groups.get("Mecabricks Subdiv")
    if ng is None:
        ng = bpy.data.node_groups.new("Mecabricks Subdiv", 'GeometryNodeTree')
        ng.is_modifier = True
        ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        N = ng.nodes
        gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
        sd = N.new("GeometryNodeSubdivisionSurface"); sd.name = "Subdivision"
        sd.inputs["Limit Surface"].default_value = True
        sd.inputs["Boundary Smooth"].default_value = 'All'
        sd.inputs["UV Smooth"].default_value = 'Keep Boundaries'
        ce, cv = N.new("GeometryNodeInputNamedAttribute"), N.new("GeometryNodeInputNamedAttribute")
        for node, name in ((ce, "crease_edge"), (cv, "crease_vert")):
            node.data_type = 'FLOAT'
            node.inputs["Name"].default_value = name
        ss = N.new("GeometryNodeSetShadeSmooth")
        ss.domain = 'FACE'
        ss.inputs["Shade Smooth"].default_value = True
        gi.location, ce.location, cv.location = (-500, 0), (-500, -180), (-500, -300)
        sd.location, ss.location, go.location = (-200, 0), (100, 0), (350, 0)
        L = ng.links
        L.new(gi.outputs["Geometry"], sd.inputs["Mesh"])
        L.new(ce.outputs["Attribute"], sd.inputs["Edge Crease"])
        L.new(cv.outputs["Attribute"], sd.inputs["Vertex Crease"])
        L.new(sd.outputs["Mesh"], ss.inputs[0])            # Set Shade Smooth: "Geometry" up to 4.5, "Mesh" from 5.0
        L.new(ss.outputs[0], go.inputs["Geometry"])
    bs = ng.nodes["Subdivision"].inputs["Boundary Smooth"]
    if bs.default_value != 'All':           # groups from before run 42 still say Keep Corners
        bs.default_value = 'All'
    lv = ng.nodes["Subdivision"].inputs["Level"]
    if lv.default_value != LEVELS:          # only on change: a touched node group
        lv.default_value = LEVELS           # re-evaluates every object using it
    return ng

def geometric_shading(ob, me, E):
    # creased edges become sharp too (imported sharp edges are kept); with every
    # face flat-flagged this leaves the imported custom normals untouched
    sharp = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
    vals = [False] * len(me.edges)
    sharp.data.foreach_get("value", vals)
    sharp.data.foreach_set("value", [v or (i in E) for i, v in enumerate(vals)])
    # run 45: the subdivision stays the Subdivision modifier (quality setting - the GN
    # Subdivision node has none, and variant B had seam gaps up to 0.018 at the freed
    # two-edge vertices); a small node group after it only shades smooth
    for name in ("Mecabricks Subdiv", "Smooth After Subdiv"):
        if ob.modifiers.get(name):
            ob.modifiers.remove(ob.modifiers[name])
    if ob.animation_data:
        for fc in list(ob.animation_data.drivers):
            ob.animation_data.drivers.remove(fc)
    add_subsurf(ob)                          # custom normals off for variant B (SHADING)
    gmod = ob.modifiers.get("Mecabricks Smooth") or ob.modifiers.new("Mecabricks Smooth", 'NODES')
    gmod.node_group = smooth_node_group()


def smooth_node_group():
    """Variant B shading after the Subdivision modifier: every face smooth; sharp_edge
    (imported sharp edges + creased edges) keeps the creases crisp."""
    ng = bpy.data.node_groups.get("Mecabricks Smooth")
    if ng is None:
        ng = bpy.data.node_groups.new("Mecabricks Smooth", 'GeometryNodeTree')
        ng.is_modifier = True
        ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        gi, go = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
        ss = ng.nodes.new("GeometryNodeSetShadeSmooth")
        ss.domain = 'FACE'
        ss.inputs["Shade Smooth"].default_value = True
        gi.location, ss.location, go.location = (-300, 0), (0, 0), (300, 0)
        # the geometry socket is the first one; it is called "Geometry" up to Blender 4.5 and
        # "Mesh" from 5.0 (CI, Blender 4.5.14: KeyError 'Mesh' in variant B)
        ng.links.new(gi.outputs[0], ss.inputs[0])
        ng.links.new(ss.outputs[0], go.inputs[0])
    return ng

# ---------------------------------------------------------------- cache file (run 62)
# The copies are 20x the import (Dungeon: 2.7 GB file for a 152 MB import). With the cache they
# live in a .blend next to the scene, linked as a library (relative path): the scene file stays
# about as large as the import and saves fast; render memory stays one copy per mesh.
# Linked meshes are read-only and would bring their own copies of the materials, so the copies
# are written with empty material slots and the objects carry the materials of the original
# on object level (same materials, so Off / viewport 0 look unchanged). A linked mesh nobody
# uses is not kept when the scene is saved: the original holds it by an ID property.
CACHE_KEEP = "rb_keep_L"
CACHE_DEBUG = False
LINK_RATE = [80e6]        # bytes per second linking a cache file, measured on each link (run 70)
CACHE_WRITTEN = [None]    # copies the parallel run already put into the cache (run 66)


def cache_path_for(blend, tag=None):
    """<scene>_rbcache.blend next to the scene (run 62; the version belongs in the scene name,
    a cache belongs to exactly one scene file)."""
    import os
    return os.path.splitext(blend)[0] + "_rbcache.blend"


def cache_library():
    """The library the copies are linked from (None without a cache)."""
    for m in bpy.data.meshes:
        if m.library is not None and (m.get("rb_original") or m.name.rsplit(" L", 1)[-1].isdigit()):
            return m.library
    return None


def cache_state():
    """(library, its file, the file it should be next to the scene, file exists) or None."""
    import os
    lib = cache_library()
    if lib is None:
        return None
    cur = os.path.abspath(bpy.path.abspath(lib.filepath))
    want = os.path.abspath(cache_path_for(bpy.data.filepath)) if bpy.data.filepath else cur
    if os.path.normcase(cur) == os.path.normcase(want):
        want = cur                           # the same file: compared without case (Windows)
    return lib, cur, want, os.path.exists(cur)


def relink_cache(lib, path):
    """Point the cache library to `path` (relative to the scene) and read it again."""
    lib.filepath = bpy.path.relpath(path) if bpy.data.filepath else path
    lib.reload()
    override_materials()                 # the overrides lose their materials on a reload


def move_cache():
    """The cache file next to the scene under the scene's name, the link updated (run 63: after
    Save As under another name or in another folder). Returns (old path, new path)."""
    import os, shutil
    st = cache_state()
    if st is None:
        raise RuntimeError("no cache file linked")
    lib, cur, want, exists = st
    if cur == want:
        return cur, want
    if exists:
        if os.path.exists(want):
            os.remove(want)                  # the caller confirmed replacing it
        shutil.move(cur, want)               # want keeps the case of the scene name
    elif not os.path.exists(want):
        raise RuntimeError(f"cache file not found: {cur}")
    relink_cache(lib, want)
    return cur, want


def relink_cache_on_load():
    """After loading: the linked cache file is gone, but <scene>_rbcache.blend lies next to the
    scene (both moved or renamed in the Explorer) - link that one. Returns True if relinked."""
    import os
    st = cache_state()
    if st is None or st[3] or not bpy.data.filepath:
        return False
    if os.path.exists(st[2]):
        relink_cache(st[0], st[2])
        return True
    return False


def processed_originals():
    return [m for m in bpy.data.meshes if m.library is None and not m.get("rb_original")
            and (m.get("rb_view") or m.get("rb_render") or all_copies(m))]


def _users_of(orig):
    return [o for o in bpy.data.objects if o.type == 'MESH' and o.data is not None
            and (o.data == orig or o.data.get("rb_original") == orig.name)]


def object_materials(ob, orig, on=True):
    """Materials of the original on the object's slots (on) or back on the mesh (off)."""
    for i, slot in enumerate(ob.material_slots):
        if on:
            mt = orig.materials[i] if i < len(orig.materials) else None
            slot.link = 'OBJECT'
            slot.material = mt
        elif slot.link == 'OBJECT':
            slot.material = None
            slot.link = 'DATA'


def run_steps(gen, wait=0.2):
    """Run a step generator to its end (headless, scripts); it yields (fraction, text[, waiting])
    and returns its result. waiting: nothing to do but wait for a helper process."""
    import time
    try:
        while True:
            st = next(gen)
            if len(st) > 2 and st[2]:
                time.sleep(wait)
    except StopIteration as e:
        return e.value


def write_cache(path, files=(), fresh=()):
    return run_steps(write_cache_steps(path, files, fresh))


def write_cache_steps(path, files=(), fresh=()):
    """Generator of write_cache (run 69): yields (fraction, text[, waiting]) between short pieces
    of work so the add-on can show a progress bar; the helper Blender runs in the background.
    files: .blend files with new copies (the workers' parts), fresh: their (original, level)
    keys - they go into the cache without being loaded into this file (run 66: loading 5,538
    copies into the open Dungeon took 134 s, writing them again 65 s).
    All copies in use (the viewport and render level of every processed mesh) into the cache
    at `path`, then linked back as library overrides. Returns the number of copies.
    The objects keep the materials on their mesh: the override of each copy carries the
    original's materials (with object-level materials Cycles stopped sharing a mesh between
    objects - Dungeon ran out of GPU memory, run 64/65). One pass over meshes and objects; copies
    of an earlier cache that stay are carried over by a helper Blender (run 62)."""
    import os, json, subprocess, tempfile, time
    T = [time.time()]

    def mark(what):
        if CACHE_DEBUG:
            print(f"CACHETIME {what} {time.time() - T[0]:.1f} s", flush=True)
        T[0] = time.time()

    yield (0.0, "preparing the cache file")
    # indexes: copies and objects per original (local data-blocks; linked ones are references)
    copies_of, local = {}, {}
    for m in bpy.data.meshes:
        name = m.get("rb_original")
        if name:
            copies_of.setdefault(name, []).append(m)
        elif m.library is None:
            local[m.name] = m
    origs = [m for n, m in local.items() if n in copies_of or m.get("rb_view") or m.get("rb_render")]
    users = {orig.name: [] for orig in origs}
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data is not None:
            key = ob.data.get("rb_original") or ob.data.name
            if key in users and (ob.data.get("rb_original") or ob.data == local.get(key)):
                users[key].append(ob)
    # what every object shows now: its original (0) or a copy of a level - kept as it is
    shown = {ob.name: (int(ob.data["rb_level"]) if ob.data.get("rb_original") else
                       (-1 if ob.get("rb_show_view") else 0))
             for obs in users.values() for ob in obs}
    def level_of(name):
        tail = name.rsplit(" L", 1)[-1] if name else ""
        return int(tail) if tail.isdigit() else None

    want = {}
    for orig in origs:
        want[orig.name] = {}
        for w in ("view", "render"):
            cp = copy_of(orig, w)
            lv = int(cp["rb_level"]) if cp is not None else level_of(orig.get(f"rb_{w}", ""))
            if lv:
                want[orig.name][w] = lv
    fresh = set(fresh)
    for orig in origs:
        for ob in users[orig.name]:
            object_materials(ob, orig, False)    # materials on the mesh (also 1.9.0/1.9.1 scenes)
            ob.data = orig
        for k in [k for k in orig.keys() if k.startswith(CACHE_KEEP)]:
            del orig[k]
    mark("objects to originals")
    # new copies (local, baked here) to write; copies of an earlier cache (overrides or linked)
    # to carry over from their file
    new, drop, old = [], [], []
    for name, cps in copies_of.items():
        levels = set(want.get(name, {}).values())
        for cp in cps:
            if cp.library is None and cp.override_library is None:
                (new if int(cp.get("rb_level", 0)) in levels else drop).append(cp)
            else:
                old.append(cp)
    have_new = {(cp["rb_original"], int(cp["rb_level"])) for cp in new} | fresh
    carry, keys = {}, set(have_new)
    for cp in old:
        ref = cp.override_library.reference if cp.override_library is not None else cp
        if ref is None or ref.library is None or getattr(ref, "is_missing", False):
            continue
        key = (cp["rb_original"], int(cp["rb_level"]))
        if key not in keys and key[1] in set(want.get(key[0], {}).values()):
            keys.add(key)
            carry.setdefault(bpy.path.abspath(ref.library.filepath), []).append(ref.name)
    for cp in new:
        cp.name = f"{cp['rb_original']} L{int(cp['rb_level'])}"
        for i in range(len(cp.materials)):
            cp.materials[i] = None           # the overrides get the materials in this file
    names = ({cp.name for cp in new} | {n for ns in carry.values() for n in ns}
             | {f"{o} L{lv}" for o, lv in fresh})
    tmp = path + ".writing"
    yield (0.05, "writing the cache file")
    # the compressed write is one call without progress (Dungeon 39 s, the text is on screen).
    # Tried in run 69: uncompressed to the temp folder + the helper compressing in the
    # background - progress all the way, but 82 s instead of 65 s: the direct call stays.
    if new and not carry and not files:
        bpy.data.libraries.write(tmp, set(new), fake_user=True, compress=True)   # one call, no progress inside
    elif new or carry or files:
        part = os.path.join(tempfile.gettempdir(), f"rb_cache_new_{os.getpid()}.blend")
        if new:
            bpy.data.libraries.write(part, set(new), fake_user=True, compress=False)
        job = os.path.join(tempfile.gettempdir(), f"rb_cache_job_{os.getpid()}.json")
        sources = ([part] if new else []) + list(files)
        json.dump({"out": tmp, "new": sources, "carry": carry}, open(job, "w", encoding="utf-8"))
        # size of the result, estimated: new parts are written uncompressed (~1/4 when
        # compressed), carried copies are a share of their compressed cache file
        est = 0.25 * sum(os.path.getsize(f) for f in sources if os.path.exists(f))
        for lib_path, ns in carry.items():
            n_lib = sum(1 for m in bpy.data.meshes if m.library is not None
                        and bpy.path.abspath(m.library.filepath) == lib_path) or len(ns)
            est += os.path.getsize(lib_path) * len(ns) / n_lib if os.path.exists(lib_path) else 0
        est = max(est, 1.0)
        n_src = len(sources) + len(carry)
        proc = subprocess.Popen([bpy.app.binary_path, "-b", "--factory-startup", "--python",
                                 os.path.abspath(__file__), "--", "--merge-cache", job],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import threading, queue
        q, tail = queue.Queue(), []
        threading.Thread(target=lambda: [q.put(x) for x in proc.stdout], daemon=True).start()
        loaded = 0
        while proc.poll() is None or not q.empty():
            while not q.empty():
                line = q.get()
                tail.append(line)
                if line.startswith("MERGELOADED"):
                    loaded += 1
            size = max((os.path.getsize(f) for f in (tmp, tmp + "@") if os.path.exists(f)), default=0)
            if size:
                yield (0.35 + 0.4 * min(0.98, size / est), f"writing the cache file {size / 1e9:.2f} GB", True)
            else:
                yield (0.05 + 0.3 * loaded / max(1, n_src), f"joining the copies ({loaded}/{n_src} files)", True)
        for f in (part, job):
            if os.path.exists(f):
                os.remove(f)
        if not os.path.exists(tmp):
            raise RuntimeError("cache merge failed: " + "".join(tail)[-500:])
    mark("write")
    yield (0.76, "writing the cache file")
    refs = [cp.override_library.reference for cp in old if cp.override_library is not None
            and cp.override_library.reference is not None]
    gone = list({*drop, *new, *old, *refs})
    if gone:
        bpy.data.batch_remove(gone)
    cleanup_libraries()
    mark("remove")
    if not names:
        return 0
    os.replace(tmp, path)
    # one call without progress: in portions every call reads the file again (Dungeon: all at
    # once 36 s, 12 portions 63 s, run 70) - instead an estimate from the size and the speed of
    # the last link on this computer
    size = os.path.getsize(path)
    est = size / LINK_RATE[0]
    yield (0.78, f"linking the cache file (about {est:.0f} s)" if est >= 3 else "linking the cache file")
    t_link = time.time()
    with bpy.data.libraries.load(path, link=True, relative=bpy.data.filepath != "") as (src, dst):
        dst.meshes = [n for n in src.meshes if n in names]
    if size > 50e6:
        LINK_RATE[0] = size / max(0.5, time.time() - t_link)
    mark("link")
    by_orig = {}
    refs_new = [r for r in dst.meshes if r is not None]
    for i, ref in enumerate(refs_new):
        ov = ref.override_create(remap_local_usages=False)     # one by one with remap: 192 s (run 65)
        if ov is None:          # 5.3: a linked mesh without a user counts as indirect - a user first (run 71)
            ref.use_fake_user = True
            ov = ref.override_create(remap_local_usages=False)
            ref.use_fake_user = False
        if ov is None:
            raise RuntimeError(f"Blender {bpy.app.version_string} made no override of {ref.name}")
        by_orig.setdefault(ov["rb_original"], {})[int(ov["rb_level"])] = ov
        if i % 200 == 0:
            yield (0.9 + 0.05 * i / len(refs_new), "linking the copies")
    for k, orig in enumerate(origs):
        if k % 200 == 0:
            yield (0.95 + 0.05 * k / max(1, len(origs)), "linking the copies")
        have = by_orig.get(orig.name, {})
        for lv, cp in have.items():
            for i, mt in enumerate(orig.materials):
                if i < len(cp.materials):
                    cp.materials[i] = mt
            orig[f"{CACHE_KEEP}{lv}"] = cp           # keeps the copy nobody shows in the file
        for w, lv in want[orig.name].items():
            if lv in have:
                orig[f"rb_{w}"] = have[lv].name
        view = have.get(want[orig.name].get("view"))
        for ob in users[orig.name]:
            lv = shown[ob.name]              # -1: new copies from the workers - the view copy
            ob.data = (have.get(lv) or view or orig) if lv else orig
    mark("overrides")
    return len(names)


def override_materials():
    """After loading: the overrides of the cache copies get the materials of their original on
    the mesh again (Blender records the change but does not apply it when loading, run 65).
    Returns the number of copies."""
    n = 0
    for me in bpy.data.meshes:
        if me.override_library is None or not me.get("rb_original"):
            continue
        orig = bpy.data.meshes.get((me["rb_original"], None))
        if orig is None:
            continue
        for i, mt in enumerate(orig.materials):
            if i < len(me.materials) and me.materials[i] != mt:
                me.materials[i] = mt
        n += 1
    return n


def _merge_cache(job):
    """Helper Blender of write_cache: new copies + the copies carried over from earlier cache
    files -> one cache file (in an empty file appending is fast)."""
    import json
    j = json.load(open(job, encoding="utf-8"))
    ids = []
    for f in ([j["new"]] if isinstance(j["new"], str) and j["new"] else j["new"] or []):
        with bpy.data.libraries.load(f, link=False) as (src, dst):
            dst.meshes = list(src.meshes)
        ids += [m for m in dst.meshes if m is not None]
        print("MERGELOADED", f, flush=True)
    for lib_path, names in j["carry"].items():
        with bpy.data.libraries.load(lib_path, link=False) as (src, dst):
            dst.meshes = [n for n in src.meshes if n in set(names)]
        ids += [m for m in dst.meshes if m is not None]
        print("MERGELOADED", lib_path, flush=True)
    bpy.data.libraries.write(j["out"], set(ids), fake_user=True, compress=True)
    print("MERGED", len(ids), flush=True)


def drop_cache_links(orig):
    """Remove: the objects take the materials from the mesh again, the cache hold is released."""
    for ob in _users_of(orig):
        object_materials(ob, orig, False)
    for k in [k for k in orig.keys() if k.startswith(CACHE_KEEP)]:
        del orig[k]


def uncache():
    """Cache off (run 64): objects whose mesh has only local copies take the materials from the
    mesh again (object-level materials stop Cycles from sharing meshes), the cache hold is
    released, unused cache libraries removed. Returns the number of objects changed."""
    cleanup_libraries()                  # references of copies an Apply replaced go first
    copies_of = {}
    for m in bpy.data.meshes:
        if m.get("rb_original"):
            copies_of.setdefault(m["rb_original"], []).append(m)
    n = 0
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.data is None or not any(sl.link == 'OBJECT' for sl in ob.material_slots):
            continue
        name = ob.data.get("rb_original") or ob.data.name
        orig = bpy.data.meshes.get((name, None))
        if orig is None or any(c.library or c.override_library for c in copies_of.get(name, [])):
            continue
        object_materials(ob, orig, False)
        n += 1
    for orig in [bpy.data.meshes.get((k, None)) for k in copies_of]:
        if orig is not None and not any(c.library or c.override_library for c in copies_of[orig.name]):
            for k in [k for k in orig.keys() if k.startswith(CACHE_KEEP)]:
                del orig[k]
    cleanup_libraries()
    return n


def embed_cache():
    return run_steps(embed_cache_steps())


def embed_cache_steps():
    """Generator of embed_cache (run 69): yields (fraction, text) after each copy.
    Cache off (run 68): the copies of the cache become ordinary data of this file again -
    each is written into a new mesh by a temporary object in a scene of its own (Dungeon's
    5,538: 14 s; make_local one by one took 310 s, and copy() of an override is an override
    again). Objects and materials as before, references and library removed. Returns the
    number of copies."""
    import time
    cached = [m for m in bpy.data.meshes if m.get("rb_original") and (m.override_library is not None or m.library is not None)
              and not getattr(m, "is_missing", False)]
    refs = {m.override_library.reference for m in cached if m.override_library is not None} - {None}
    cached = [m for m in cached if m not in refs]       # the overrides stand for their references
    if not cached:
        uncache()
        return 0
    work = work_object(cached[0])
    dg = depsgraph_of(work)
    new = {}
    try:
        for i, cm in enumerate(cached):
            yield (0.95 * i / len(cached), f"taking the copies into the scene {i}/{len(cached)}")
            work.data = cm
            dg.update()
            cp = bpy.data.meshes.new_from_object(work.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            for k in cm.keys():
                cp[k] = cm[k]
            orig = bpy.data.meshes.get((cm["rb_original"], None))
            if orig is not None:
                for i, mt in enumerate(orig.materials):
                    if i < len(cp.materials):
                        cp.materials[i] = mt
            cp.use_fake_user = True          # a copy no object shows (the render copy) is kept
            new[cm] = (cp, cm.name)
    finally:
        bpy.data.objects.remove(work)
        drop_work_scene()
    yield (0.95, "taking the copies into the scene")
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data in new:
            orig = bpy.data.meshes.get((ob.data["rb_original"], None))
            ob.data = new[ob.data][0]
            if orig is not None:
                object_materials(ob, orig, False)      # 1.9.0/1.9.1 scenes: materials back on the mesh
    for me in [m for m in bpy.data.meshes if m.library is None and not m.get("rb_original")]:
        for k in [k for k in me.keys() if k.startswith(CACHE_KEEP)]:
            del me[k]
    bpy.data.batch_remove(list(new) + list(refs))
    cleanup_libraries()
    for cp, name in new.values():
        cp.name = name
    return len(new)


def cleanup_libraries():
    """Remove linked copies nothing uses and the libraries nothing is linked from any more (the
    user count of a library is not reliable for this, run 64)."""
    orphans = [m for m in bpy.data.meshes if m.library is not None and m.users == 0]
    if orphans:
        bpy.data.batch_remove(orphans)
    used = set()
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.objects, bpy.data.node_groups,
                 bpy.data.images, bpy.data.collections, bpy.data.textures):
        used |= {i.library for i in coll if i.library is not None}
    gone = [lib for lib in bpy.data.libraries if lib not in used]
    if gone:
        bpy.data.batch_remove(gone)


def cache_missing_fix():
    """After loading: objects whose linked copy is missing (cache deleted or moved) show their
    original. Returns the number of objects switched back."""
    n = 0
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.data is None:
            continue
        ovr = ob.data.override_library
        ref_missing = ovr is not None and (ovr.reference is None or getattr(ovr.reference, "is_missing", False))
        if not (getattr(ob.data, "is_missing", False) or ref_missing):
            continue
        base = ob.data.get("rb_original") or ob.data.name.rsplit(" L", 1)[0]
        orig = bpy.data.meshes.get((base, None))
        if orig is not None and orig.library is None:
            ob.data = orig
            n += 1
    return n


def _progress(i, n, done_w, total_w, t_start, name):
    import time
    el = time.time() - t_start
    left = el / done_w * (total_w - done_w) if done_w else 0
    bar = "#" * int(30 * done_w / total_w)
    return (f"PROGRESS [{bar:<30}] {i}/{n} meshes  {100 * done_w / total_w:5.1f} %  "
            f"elapsed {int(el // 60)}:{int(el % 60):02d}  left ~{int(left // 60)}:{int(left % 60):02d}  {name}")


def _assign(users, weight, n):
    """Meshes -> worker 0..n-1, largest first onto the least loaded (same in every process)."""
    load, part = [0] * n, {}
    for me in sorted(users, key=lambda m: (-weight[m], m.name)):
        k = load.index(min(load))
        part[me.name] = k
        load[k] += weight[me]
    return part


def resolve_jobs(value, n_meshes):
    """--jobs: a number, or 'auto' - one Blender per 2 cores, one per JOB_GB of free memory
    (each worker holds the whole scene), at most 8, at least ~20 meshes each (run 59)."""
    import os
    if value != "auto":
        return max(1, int(value))
    cores = (os.cpu_count() or 2) // 2
    try:
        mem = int(free_memory_gb() // JOB_GB)
    except Exception:
        mem = 2
    return max(1, min(8, cores, mem, n_meshes // 20))


def _run_meshes(users, pick, weight, total_w, show_progress, wait=0, after=None, flush=None):
    """Process the meshes in `pick` one after the other. Prints PART per mesh (the parent of a
    worker counts them), PROGRESS if show_progress. wait: a worker short of memory writes its
    copies away (flush), waits up to `wait` seconds and then retires - it prints RETIRE and
    stops, the meshes it did not do are done by the parent; without wait a mesh short of memory
    is skipped. after: called with each finished mesh. Returns (skipped, failed, reports)."""
    import time
    t_start, done_w = time.time(), 0
    skipped, failed, reps = [], [], {}
    for i, me in enumerate(pick, 1):
        obs = users[me]
        _t0 = time.time()
        deadline = time.time() + wait
        flushed = False
        while True:
            try:
                check_memory(me, max(VIEW_LEVEL, RENDER_LEVEL))
                short = None
                break
            except MemoryShortage as e:
                short = e
                if wait and flush and not flushed:      # give back what this worker holds first
                    flush()
                    flushed = True
                    continue
                if time.time() >= deadline:
                    break
                time.sleep(2)
        if short is not None:
            if wait:                    # a worker: stop and free all its memory for the others
                print(f"RETIRE worker short of memory at {me.name!r} ({len(pick) - i + 1} meshes left, "
                      f"done at the end): {short}", flush=True)
                break
            skipped.append(me.name)
            print(f"SKIP {me.name!r}: {short}", flush=True)
            continue
        try:
            rep = process(me, obs)
        except Exception as e:      # one broken mesh must not end a long headless run
            import traceback
            traceback.print_exc()
            failed.append(me.name)
            print(f"Error in {me.name!r}: {type(e).__name__}: {e} - mesh left as imported", flush=True)
            continue
        rep['seconds'] = round(time.time() - _t0, 1)
        reps[me.name] = rep
        print(f"PART {me.name!r} objects={len(obs)} {rep}", flush=True)
        if after:
            after(me)
        done_w += weight[me]
        if show_progress:
            print(_progress(i, len(pick), done_w, total_w, t_start, me.name), flush=True)
    return skipped, failed, reps


class Workers:
    """Several cores (run 59/60): the saved scene is opened by `jobs` worker Blenders, each
    bakes its share of the meshes and writes only the copies (without materials) to a
    temporary .blend plus a JSON of the reports. Used by the headless run (main) and by the
    add-on's Apply in the window (modal, the window stays usable).
    start -> poll() for progress lines -> merge() the copies into this Blender."""

    def __init__(self, users, jobs, opts, names=None, scene_path=None):
        import os, json, queue, tempfile, threading, subprocess
        self.users = users
        self.by_name = {me.name: me for me in users}
        self.weight = {me: len(me.polygons) + 50 for me in users}
        self.total_w = sum(self.weight.values()) or 1
        self.jobs = jobs
        self.tmp = tempfile.mkdtemp(prefix="rb_jobs_")
        self.q = queue.Queue()
        self.done, self.done_w, self.skipped, self.errors, self.retired = [], 0, [], [], 0
        extra = []
        if names is not None:           # only these meshes (Apply on a selection)
            pm = os.path.join(self.tmp, "meshes.json")
            json.dump(sorted(names), open(pm, "w", encoding="utf-8"))
            extra = ["--meshes", pm]
        self.procs = []
        for i in range(jobs):
            cmd = [bpy.app.binary_path, "-b", "--factory-startup", scene_path or bpy.data.filepath, "--python",
                   os.path.abspath(__file__), "--"] + list(opts) + extra + [
                   "--worker", str(i), str(jobs), self.part(i, "blend"), self.part(i, "json")]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace", creationflags=flags)
            self.procs.append(pr)
            threading.Thread(target=self._reader, args=(pr,), daemon=True).start()

    def part(self, i, ext):
        import os
        return os.path.join(self.tmp, f"part{i}.{ext}")

    def _reader(self, pr):
        for line in pr.stdout:
            self.q.put(line)

    def running(self):
        return any(pr.poll() is None for pr in self.procs) or not self.q.empty()

    def poll(self, timeout=0.0):
        """Read what the workers printed; returns the lines worth showing (PART counted)."""
        import re, queue
        out = []
        while True:
            try:
                line = self.q.get(timeout=timeout).rstrip()
            except queue.Empty:
                return out
            timeout = 0.0
            m = re.match(r"PART '(.+?)' ", line)
            if m and m.group(1) in self.by_name:
                self.done.append(m.group(1))
                self.done_w += self.weight[self.by_name[m.group(1)]]
                out.append(("PART", m.group(1)))
            elif line.startswith("SKIP '"):
                self.skipped.append(line[6:line.index("'", 6)])
                out.append(("SKIP", line))
            elif line.startswith("RETIRE"):
                self.retired += 1
                out.append(("RETIRE", line))
            elif line.startswith(("Error", "Traceback")):
                self.errors.append(line)
                out.append(("ERROR", line))

    def kill(self):
        import shutil
        for pr in self.procs:
            if pr.poll() is None:
                pr.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def merge_to_cache(self, path, on_mesh=None):
        return run_steps(self.merge_to_cache_steps(path, on_mesh))

    def merge_to_cache_steps(self, path, on_mesh=None):
        """With the cache on: the workers' part files go straight into the cache (a helper
        Blender joins them), this file only links the result - the copies are never loaded here
        (run 66: Dungeon 134 s loading + 65 s writing). Returns (reports, meshes without a
        worker result)."""
        import os, json, glob, shutil
        reps, files = {}, []
        for i in range(self.jobs):
            pj = self.part(i, "json")
            if not os.path.exists(pj):
                self.errors.append(f"Error: worker {i} wrote no result (exit {self.procs[i].returncode})")
                continue
            reps.update(json.load(open(pj, encoding="utf-8")))
            files += sorted(glob.glob(glob.escape(os.path.splitext(self.part(i, "blend"))[0]) + "_b*.blend"))
        levels = bake_levels_wanted()
        fresh, rest = set(), []
        for k, (me, obs) in enumerate(self.users.items()):
            if k % 200 == 0:
                yield (0.05 * k / max(1, len(self.users)), "taking over the copies of the workers")
            if me.name in reps:
                orig = prepare(me, obs)
                for ob in obs:              # off the old copies; the cache links the new ones
                    ob.data = orig
                old = all_copies(orig)
                refs = [c.override_library.reference for c in old
                        if c.override_library is not None and c.override_library.reference is not None]
                if old or refs:
                    bpy.data.batch_remove(list({*old, *refs}))
                orig["rb_view"] = f"{orig.name} L{VIEW_LEVEL}" if VIEW_LEVEL else ""
                orig["rb_render"] = f"{orig.name} L{RENDER_LEVEL}" if RENDER_LEVEL else ""
                orig.use_fake_user = True
                for ob in obs:
                    ob.pop("rb_off", None)
                    ob["rb_show_view"] = 1          # write_cache puts them on the view copy
                fresh |= {(orig.name, lv) for lv in levels}
                if on_mesh:
                    on_mesh(me, obs, reps[me.name])
            elif me.name not in self.skipped:
                rest.append(me)
        steps = write_cache_steps(path, files=files, fresh=fresh)
        try:
            while True:
                st = next(steps)
                yield (0.05 + 0.95 * st[0],) + tuple(st[1:])
        except StopIteration as e:
            n = e.value
        for ob in bpy.data.objects:
            ob.pop("rb_show_view", None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return reps, rest, n

    def merge(self, on_mesh=None):
        """Load the workers' copies, give them the materials of their originals and link them
        as process() does. Returns (reports by mesh name, meshes without a worker result)."""
        import os, json, glob, shutil
        made, reps = {}, {}
        loaded = []
        for i in range(self.jobs):
            pj = self.part(i, "json")
            if not os.path.exists(pj):
                self.errors.append(f"Error: worker {i} wrote no result (exit {self.procs[i].returncode})")
                continue
            reps.update(json.load(open(pj, encoding="utf-8")))
            for pb in sorted(glob.glob(glob.escape(os.path.splitext(self.part(i, "blend"))[0]) + "_b*.blend")):
                with bpy.data.libraries.load(pb, link=False) as (src, dst):
                    dst.meshes = list(src.meshes)
                loaded += list(dst.meshes)
        for cp in loaded:
            if cp is None or cp.get("rb_original") not in self.by_name:
                continue
            orig = self.by_name[cp["rb_original"]]
            cp.use_fake_user = True          # not kept by the append - the render copy has no user
            for j, mt in enumerate(orig.materials):     # the worker wrote empty slots
                if j < len(cp.materials):
                    cp.materials[j] = mt
                else:
                    cp.materials.append(mt)
            made.setdefault(orig.name, {})[int(cp["rb_level"])] = cp
        rest = []
        for me, obs in self.users.items():
            if me.name in made and me.name in reps:
                orig = prepare(me, obs)
                finish(orig, obs, made[me.name], reps[me.name], check=False)
                if on_mesh:
                    on_mesh(me, obs, reps[me.name])
            elif me.name not in self.skipped:
                rest.append(me)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return reps, rest


def clean_for_workers(users):
    """Headless run on a converted scene (user, 2026-09-28): the links go back to the imported meshes
    and the copies and the cache library are removed - they are made again anyway. Italian Riviera
    opened with its cache took 3.9 GB instead of 1.0 GB, in the parent and in every worker. Returns
    whether anything was removed."""
    copies = [m for m in bpy.data.meshes if m.get("rb_original") and m.library is None]
    libs = [l for l in bpy.data.libraries if l.filepath.endswith("_rbcache.blend")]
    if not copies and not libs:
        return False
    for orig, obs in users.items():
        for o in obs:
            if o.data != orig:
                o.data = orig
    for m in copies:
        bpy.data.meshes.remove(m)
    for l in libs:
        bpy.data.libraries.remove(l)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    return True


def _parallel(users, weight, total_w, jobs, scene_path=None):
    """Headless run on several cores (run 59): see Workers. scene_path: the file the workers open."""
    import time
    opts = list(args[1:]) if TARGET else list(args)
    if "--jobs" in opts:
        k = opts.index("--jobs")
        del opts[k:k + 2]
    w = Workers(users, jobs, opts, scene_path=scene_path)
    print(f"JOBS {jobs} Blender processes for {len(users)} meshes", flush=True)
    cache = opt("--cache", "")
    t_start = time.time()
    while w.running():
        for kind, x in w.poll(timeout=0.5):
            if kind == "PART":
                print(_progress(len(w.done), len(users), w.done_w, total_w, t_start, x), flush=True)
            else:
                print(x, flush=True)
    print(f"MERGE copies of the workers (bake {time.time() - t_start:.0f} s)", flush=True)
    t_m = time.time()
    if cache:                       # straight into the cache file (run 66)
        reps, rest, n = w.merge_to_cache(cache)
        CACHE_WRITTEN[0] = n
        print(f"CACHE {n} copies in {cache} ({time.time() - t_m:.0f} s)", flush=True)
    else:
        reps, rest = w.merge()
    for e in w.errors:
        if e.startswith("Error: worker"):
            print(e, flush=True)
    print(f"MERGE loaded and linked {time.time() - t_m:.0f} s", flush=True)
    skipped, failed = list(w.skipped), []
    if rest:        # a worker failed: its meshes are done here, one after the other
        print(f"MERGE {len(rest)} meshes without a worker result - processing them here", flush=True)
        s2, f2, _r = _run_meshes(users, rest, weight, total_w, True)
        skipped += s2
        failed += f2
    t_m = time.time()
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    print(f"MERGE cleaned {time.time() - t_m:.0f} s", flush=True)
    return skipped, failed


LOG = opt("--log", "")       # headless conversion with the add-on's option Log file


def say(msg):
    """A result line: to the console (the start script shows it) and, with --log, into the log file."""
    print(msg, flush=True)
    if LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(f"  - {msg}\n")
        except OSError:
            pass


# ---------------------------------------------------------------- render camera (user, 2026-09-28)
# "Render camera: ON" creates the camera "Renderbricks" (framing the model to fill the picture, clip
# end 1000) and a world "Renderbricks Sky" of its own (Physical Sky), makes both active and takes over
# the render settings of the Renderbricks setup scene (setup/renderbricks_setup.blend in the add-on).
# The scene's camera, world and render settings before are kept in the scene and come back with OFF -
# nothing of the user's is overwritten or lost (the old world keeps a fake user while it is unused).
# Framing: the manual way is Lock Camera to View, select all meshes, numpad 0 and period;
# camera_fit_coords is the same fit without a viewport.
CAMERA_NAME = "Renderbricks"
SKY_NAME = "Renderbricks Sky"
SKY_TAG = "rb_sky"                      # the world made or taken over by the add-on
CAMERA_ANGLE = (1.1093, 0.0, 0.8149)    # Blender's default camera: three-quarter view from the front right
CAMERA_MARGIN = 1.05                    # 5 % around the model
CLIP_END = 1000.0
RENDER_STRUCTS = ("render", "cycles", "eevee", "view_settings", "display_settings")
SKIP_PROPS = ("rna_type", "filepath", "name", "preview_pause")      # preview_pause: viewport only, needs a window


def _props(struct, depth=0):
    """(identifier, value or nested struct) of the settable properties - nested structs two levels
    deep, no ID data blocks, no collections."""
    if struct is None:
        return
    for p in struct.bl_rna.properties:
        k = p.identifier
        if k in SKIP_PROPS:
            continue
        if p.type == 'POINTER':
            v = getattr(struct, k, None)
            if depth < 2 and v is not None and not isinstance(v, bpy.types.ID):
                yield k, v, True
            continue
        if p.type == 'COLLECTION' or p.is_readonly:
            continue
        yield k, getattr(struct, k), False


def copy_props(src, dst, depth=0):
    """Copy the settable properties of one settings struct to another."""
    if src is None or dst is None:
        return
    for k, v, nested in _props(src, depth):
        if nested:
            copy_props(v, getattr(dst, k, None), depth + 1)
            continue
        try:
            setattr(dst, k, v)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass


def snapshot_props(struct, depth=0):
    """The settable properties as plain values (for the scene's JSON)."""
    out = {}
    for k, v, nested in _props(struct, depth):
        if nested:
            out[k] = snapshot_props(v, depth + 1)
        elif isinstance(v, (bool, int, float, str)):
            out[k] = v
        elif isinstance(v, set):
            out[k] = {"__set__": sorted(v)}
        else:
            try:
                out[k] = {"__seq__": list(v)}
            except TypeError:
                pass
    return out


def restore_props(struct, snap):
    if struct is None:
        return
    for k, v in snap.items():
        if isinstance(v, dict) and "__set__" in v:
            v = set(v["__set__"])
        elif isinstance(v, dict) and "__seq__" in v:
            v = v["__seq__"]
        elif isinstance(v, dict):
            restore_props(getattr(struct, k, None), v)
            continue
        try:
            setattr(struct, k, v)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass


def sky_world():
    """The world of the add-on, if there is one in the file."""
    return next((w for w in bpy.data.worlds if w.get(SKY_TAG)), None)


def make_sky():
    """A Physical Sky world of its own (when the setup scene is not there)."""
    w = bpy.data.worlds.new(SKY_NAME)
    if hasattr(w, "use_nodes") and not w.node_tree:
        w.use_nodes = True
    nt = w.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    bg = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBackground"), None)
    if bg is None:
        bg = nt.nodes.new("ShaderNodeBackground")
        out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputWorld"), None) or \
            nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(bg.outputs[0], out.inputs[0])
    nt.links.new(sky.outputs[0], bg.inputs[0])
    return w


def apply_template(scene, path):
    """Render settings and colour management of the first scene in the setup file; its world becomes
    the add-on's sky (tagged, kept once). Returns the sky world taken over, or None."""
    import os
    if not path or not os.path.isfile(path):
        return None
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.scenes = src.scenes[:1]
    if not dst.scenes or dst.scenes[0] is None:
        return None
    tpl = dst.scenes[0]
    for attr in RENDER_STRUCTS:
        copy_props(getattr(tpl, attr, None), getattr(scene, attr, None))
    if tpl.render.engine:
        scene.render.engine = tpl.render.engine
    world = tpl.world
    objs = list(tpl.objects)
    bpy.data.scenes.remove(tpl)
    for o in objs:                      # the setup scene's own objects are not taken over
        if o.users == 0:
            bpy.data.objects.remove(o)
    if world is not None:
        world[SKY_TAG] = True
    return world


def visible_meshes(scene):
    vl = scene.view_layers[0] if scene.view_layers else None
    out = []
    for o in scene.objects:
        if o.type == 'MESH' and o.name != WORK_NAME:
            try:
                vis = o.visible_get(view_layer=vl) if vl else not o.hide_get()
            except (RuntimeError, TypeError):
                vis = True
            if vis:
                out.append(o)
    return out


def frame_camera(scene, cam, depsgraph):
    """Move the camera (keeping its direction) so that all visible meshes fill the picture, 5 % margin.
    Returns False without meshes."""
    import numpy as np
    from mathutils import Vector
    obs = visible_meshes(scene)
    if not obs:
        return False
    pts = np.empty((len(obs) * 8, 3))
    for i, o in enumerate(obs):
        m = np.array(o.matrix_world)
        bb = np.array(o.bound_box)
        pts[i * 8:i * 8 + 8] = bb @ m[:3, :3].T + m[:3, 3]
    c = (pts.min(0) + pts.max(0)) / 2
    pts = c + (pts - c) * CAMERA_MARGIN
    loc, _scale = cam.camera_fit_coords(depsgraph, pts.ravel().tolist())
    cam.location = loc
    r = float(np.linalg.norm(pts - c, axis=1).max())
    d = (Vector(loc) - Vector(c.tolist())).length
    cam.data.clip_end = max(CLIP_END, 2.0 * (d + r))     # very large scenes: nothing cut off
    return True


def render_camera(scene, create=True):
    """The camera "Renderbricks" (made when missing and create), linked to the scene. (camera, made)."""
    cam = bpy.data.objects.get(CAMERA_NAME)
    made = False
    if (cam is None or cam.type != 'CAMERA') and create:
        data = bpy.data.cameras.new(CAMERA_NAME)
        data.lens = 50.0
        cam = bpy.data.objects.new(CAMERA_NAME, data)
        cam.rotation_euler = CAMERA_ANGLE
        made = True
    if cam is not None and cam.name not in scene.objects:
        scene.collection.objects.link(cam)
    return cam, made


def render_camera_is_on(scene):
    return bool(scene.get("rb_render_on"))


def render_camera_on(scene, template="", depsgraph=None):
    """Keep the scene's camera, world and render settings, then make the camera "Renderbricks" and the
    world "Renderbricks Sky" active and take over the setup scene's render settings. A new camera is
    framed; an existing one stays where it is. Returns a short text for the summary."""
    import json
    if render_camera_is_on(scene):
        return "render camera already on"
    before = {"camera": scene.camera.name if scene.camera else "",
              "world": scene.world.name if scene.world else "",
              "world_fake": bool(scene.world and scene.world.use_fake_user),
              "settings": {a: snapshot_props(getattr(scene, a, None)) for a in RENDER_STRUCTS}}
    scene["rb_render_before"] = json.dumps(before)
    if scene.world is not None:
        scene.world.use_fake_user = True    # an unused world would not be saved
    have = sky_world()
    taken = apply_template(scene, template)
    if taken is not None and have is not None and taken != have:
        bpy.data.worlds.remove(taken)       # the sky is in the file already
        taken = None
    sky = have or taken or make_sky()
    sky[SKY_TAG] = True
    scene.world = sky
    cam, made = render_camera(scene)
    scene.camera = cam
    framed = False
    if made:
        dg = depsgraph or bpy.context.evaluated_depsgraph_get()
        dg.update()
        framed = frame_camera(scene, cam, dg)
    scene["rb_render_on"] = True
    import os
    used = bool(template) and os.path.isfile(template)
    return ("render camera on: camera Renderbricks" + (" created and framed" if framed else "")
            + f", world {sky.name}" + (", render settings of the setup scene" if used else ""))


def render_camera_off(scene):
    """Back to the scene's camera, world and render settings from before ON."""
    import json
    if not render_camera_is_on(scene):
        return "render camera already off"
    before = json.loads(scene.get("rb_render_before", "{}"))
    for a, snap in before.get("settings", {}).items():
        restore_props(getattr(scene, a, None), snap)
    scene.camera = bpy.data.objects.get(before.get("camera", "")) if before.get("camera") else None
    world = bpy.data.worlds.get(before.get("world", "")) if before.get("world") else None
    scene.world = world
    if world is not None:
        world.use_fake_user = before.get("world_fake", False)
    scene["rb_render_on"] = False
    if "rb_render_before" in scene:
        del scene["rb_render_before"]
    return "render camera off: camera, world and render settings as before"


def main():
    if __name__ != "__main__":      # imported (add-on, tools): no automatic run
        return
    if "--merge-cache" in args:     # helper Blender of write_cache (run 62)
        _merge_cache(args[args.index("--merge-cache") + 1])
        return
    users = {}
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data.polygons and not is_master(ob):
            users.setdefault(original_of(ob.data), []).append(ob)
    # progress for a console (headless run from the add-on, run 57): mesh i / n, weighted by
    # faces, time left
    weight = {me: len(me.polygons) + 50 for me in users}
    total_w = sum(weight.values()) or 1
    if "--worker" in args:          # one share of a parallel headless run (run 59)
        import os, json
        k = args.index("--worker")
        i, n, out_blend, out_json = int(args[k + 1]), int(args[k + 2]), args[k + 3], args[k + 4]
        if os.environ.get("RENDERBRICKER_TEST_SHORT_WORKER") == str(i):     # CI: this worker has no memory
            FREE_OVERRIDE[0] = 0.0
        if "--meshes" in args:      # Apply on a selection: only these meshes
            keep = set(json.load(open(args[args.index("--meshes") + 1], encoding="utf-8")))
            users = {me: obs for me, obs in users.items() if me.name in keep}
        part = _assign(users, weight, n)
        pick = [me for me in users if part[me.name] == i]
        # the copies are written in batches and freed (run 61): kept to the end, 8 workers on
        # Dungeon (3.4 M faces) used up the memory and skipped 236 meshes
        pending, batch = [], [0]

        def flush():
            names = set(pending)
            copies = {m for m in bpy.data.meshes if m.get("rb_original") in names}
            if copies:
                for m in copies:    # written without materials: appending hundreds of materials,
                    for j in range(len(m.materials)):   # images and node groups took 479 s for
                        m.materials[j] = None           # NINJAGO (run 59); the slots stay (run 66)
                base = os.path.splitext(out_blend)[0]
                bpy.data.libraries.write(f"{base}_b{batch[0]:03d}.blend", copies, fake_user=False)
                batch[0] += 1
                for me in [m for m in users if m.name in names]:
                    for ob in users[me]:
                        ob.data = me
                for m in copies:
                    bpy.data.meshes.remove(m)
            pending.clear()

        def after(me):
            pending.append(me.name)
            if sum(len(m.polygons) for m in bpy.data.meshes if m.get("rb_original") in set(pending)) >= FLUSH_FACES:
                flush()

        _s, _f, reps = _run_meshes(users, pick, weight, total_w, False, wait=WORKER_WAIT, after=after, flush=flush)
        flush()
        json.dump(reps, open(out_json, "w", encoding="utf-8"), default=str)     # written last: worker done
        return
    if LOG:
        import datetime
        try:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  Convert headless  "
                         f"(Blender {bpy.app.version_string})\nscene: {bpy.data.filepath}\nresult: {TARGET}\n"
                         f"settings: viewport {VIEW_LEVEL}, render {RENDER_LEVEL}, variant "
                         f"{'A' if SHADING == 'mecabricks' else 'B'}\n")
        except OSError:
            pass
    say(f"MESHES {len(users)}")      # for the progress line of the batch scripts
    clean = clean_for_workers(users) if TARGET else False
    if clean:
        say("CLEAN the previous conversion was removed from the working copy - it is made again")
    jobs = resolve_jobs(opt("--jobs", "1"), len(users)) if bpy.data.filepath else 1
    if jobs > 1:
        scene_path = None
        if clean:                   # the workers open the cleaned scene, not the file on disk
            import os, tempfile
            scene_path = os.path.join(tempfile.gettempdir(), f"rb_clean_{os.getpid()}.blend")
            bpy.ops.wm.save_as_mainfile(filepath=scene_path, copy=True, relative_remap=True, compress=False)
        try:
            skipped, failed = _parallel(users, weight, total_w, jobs, scene_path)
        finally:
            if scene_path:
                try:
                    os.remove(scene_path)
                except OSError:
                    pass
    else:
        skipped, failed, _r = _run_meshes(users, list(users), weight, total_w, True)
    if skipped:
        say(f"SKIPPED for memory: {len(skipped)} meshes ({', '.join(skipped[:5])}) - close other programs and run again")
    if failed:
        say(f"Errors in {len(failed)} meshes ({', '.join(failed)}) - left as imported")
    if "--setup" in args:            # headless, scene never set up: the result gets the render camera
        say("CAMERA " + render_camera_on(bpy.context.scene, opt("--setup", "")))
    cache = opt("--cache", "")
    pending = any(m.get("rb_original") and m.library is None and m.override_library is None for m in bpy.data.meshes)
    if cache and (CACHE_WRITTEN[0] is None or pending):   # not yet (all) by the workers' merge
        import time
        t_c = time.time()
        n = write_cache(cache)
        say(f"CACHE {n} copies in {cache} ({time.time() - t_c:.0f} s)")
    if TARGET:
        import time
        t_s = time.time()
        bpy.ops.wm.save_as_mainfile(filepath=TARGET, copy=True, compress=True)   # copies are large (run 38)
        say(f"SAVED {TARGET} ({time.time() - t_s:.0f} s)")
    if LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write("\n")
        except OSError:
            pass

main()
