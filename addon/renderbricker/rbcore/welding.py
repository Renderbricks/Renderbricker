"""The conversion of one part: weld the islands in a work copy, set the creases (W rules), repair
folds, bake the copies (process)."""
import bpy, bmesh, math, types
import numpy as np
from mathutils import Vector
from collections import defaultdict
from . import bevel, checks, config, copies, creases, meshparts, shading, shrink, workscene


# ================================================================ rules 3.0: weld (runs 48-50)
SEAM_SHARP = 10.0        # dihedral at a former island boundary from which it stays hard


PLANE_RATIO = float(config.opt("--plane-ratio", "8"))     # W13: plane / face-across area ratio (0: off), run 58


PLANE_MIN_ANGLE = 10.0   # W13: only outline edges bending at least this much


PLANE_EDGES = [0]        # W13 counter (diagnostics)


PLANE_DEBUG = False


EXCLUDE_PLANE = []       # W13 released around these folding faces: (centre, reach), run 58


INNER_SHARP = float(config.opt("--inner-sharp", "85"))   # inner island edge creased from this dihedral (W12, run 57)


ORGANIC_CORNER = 60.0    # corner bend on organic (all-curved) surfaces, run 53
COARSE_ROUNDING = config.opt("--coarse-rounding", "1") == "1"   # W17 (run 282); "0": rules 3.6, for comparisons
ROUNDING_TOTAL = 100.0   # W17: the three bends of a coarse rounding make no more than this ...
ROUNDING_RATIO = 2.0     # ... its two pieces are about the same length ...
ROUNDING_DEPTH = 0.06    # ... and the free point gives way by no more than this (mm): a corner radius up to about 0.6
ROUND_ENDS = config.opt("--round-ends", "1") == "1"   # W18 (run 283); "0": rules 3.7, for comparisons
ENDS_LOG = None          # a list: (mesh, middle of the seam, why not / "released") of every seam W18 looks at (scans)
NO_ENDS = [None]         # the import's faces where W18 is left out: the islands whose copy folded with it (_bake_weld)


DESIGN_TURN = 20.0       # W15 (run 73): designed corner - long crease edge into a short one ...


DESIGN_RATIO = 4.0       # ... edge lengths at least this far apart


DESIGN_EDGES = [0]       # W15b edges creased (count for the report)


MECH_FLAT = 0.12         # W15 on organic spots only on parts with at least this share of not curved area


LAST_FLAT_SHARE = [0.0]  # area share of the not curved islands of the last welded mesh
FLAT_SHARE_PIN = [None]  # a batch of a large mesh takes the share of the whole mesh (batches.py, UPDATES #54)


DESIGN_LOG = None        # a list: (mesh, position, turn) of every designed corner (scans, run 73)


WEDGE_SEAM = 30.0        # seam of a thin wedge island creased from this dihedral (run 56; a general 30 deg
                         # threshold for curved islands, run 54, moved Technic parts by up to 0.32) - on
                         # mechanical parts only (flat share >= MECH_FLAT, rules 3.14, run 291l)
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


orig_name = [""]


def weld(orig):
    """The welded work mesh of an imported mesh, with every crease the rules ask for (rules 3.x, docs/RULES.md W).

    The import is only read. Returns (work mesh "<name> RBweld", T vertices [(vertex, host face)], report).
    The stages hand their results on in `w` (a namespace; each stage says what it reads and what it adds):
      1 _islands          classify the islands (flat, curved, logo ...) and number them on the faces
      2 _outline_corners  what must survive the weld: edges inside an island, sharp outline corners, thin wedges
      3 _weld_seams       weld vertices along real seams only - no face and no corner may be lost
      4 _seam_creases     seams hard from SEAM_SHARP (thin wedges of mechanical parts: WEDGE_SEAM), logo edges
      5 _hole_rings       the walls of a polygonised hole stay smooth; convex rings and hexagons stay hard (W5b)
      6 _island_creases   flat stays flat, degenerate faces, steep inner edges (W12), plane beside a bevel (W13)
      7 _relief_tips      the tips of low relief steps are released
      8 _pinned_corners   corners on the crease chains: brick and organic thresholds, designed corners (W15),
                          coarse roundings stay free (W17)
        _rounding_ends    a coarse rounding runs out softly where it ends in a seam: the seam is released, the
                          next wall gets the support edge the import does not have (W18) - the cage then has
                          other faces than the import there (checks.LAYOUT on the copies)
      9 _t_vertices       T vertices and open points that stay apart are pinned
        release_arc_corners   coarse arcs across a flat island (W16)
     10 _work_mesh        the mesh with crease_edge, crease_vert, sharp_edge and normals; the report"""
    orig_name[0] = orig.name
    w = types.SimpleNamespace(orig=orig)
    _islands(w)
    _outline_corners(w)
    _weld_seams(w)
    _seam_creases(w)
    _hole_rings(w)
    _island_creases(w)
    _relief_tips(w)
    _pinned_corners(w)
    _rounding_ends(w)
    _t_vertices(w)
    arc_released = release_arc_corners(w.E, w.V, w.kind_of, w.isl)
    w.bm.verts.index_update()
    free = sorted(v.index for v in w.rounded_points)     # W17 points: left free by the shrink compensation
    wm, tv, rep = _work_mesh(w, arc_released)
    rep[shrink.SHRINK_FREE] = free
    rep["rounding_freed"] = w.rounded           # W17: middle points of coarse roundings left free
    rep["rounding_ends"], rep["support_points"] = len(w.soft), w.supports      # W18
    return wm, tv, rep


def _islands(w):
    """Stage 1. Adds bm (the import as a BMesh), isl (face layer rb_island: the island number), kind_of
    {island: kind}, flat_share (share of the area in islands that are not curved)."""
    orig = w.orig
    bm = bmesh.new(); bm.from_mesh(orig)
    bm.faces.ensure_lookup_table()
    creases.GEOM_CACHE = None
    isl = bm.faces.layers.int.new("rb_island")     # before classify: a new layer reallocates the faces
    kinds = creases.classify(bm)
    kind_of = {}
    for n, (kind, comp, _) in enumerate(kinds):
        kind_of[n] = kind
        for f in comp:
            f[isl] = n
    # share of the area in islands that are not curved: a mechanical part with round surfaces
    # (tire 2515: hub, side wall) against an organic one (hair: almost all curved), W15 (run 73)
    area_all = sum(f.calc_area() for f in bm.faces) or 1.0
    flat_share = sum(f.calc_area() for f in bm.faces if kind_of[f[isl]] != "curved") / area_all
    if FLAT_SHARE_PIN[0] is not None:
        flat_share = FLAT_SHARE_PIN[0]
    LAST_FLAT_SHARE[0] = flat_share
    w.bm, w.isl, w.kind_of, w.flat_share = bm, isl, kind_of, flat_share


def _outline_corners(w):
    """Stage 2, before the weld changes the outlines. Reads bm, isl. Adds interior (the edges inside an island,
    by position), sharp_pos {position: turn} of the sharp outline corners, wedge_isl (thin wedge islands)."""
    bm, isl = w.bm, w.isl
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
        if (creases.turn(v) or 0) < SPIKE_TURN:
            return False
        others = [w for w in at_pos[P(v.co)] if w is not v]
        return bool(others) and all((creases.turn(w) or 0) < config.SHARP_TURN for w in others)
    wedge_tips = {v for v in bm.verts if v.is_boundary and smooth_wedge_tip(v)}
    wedge_tip_pos = {P(v.co) for v in wedge_tips}
    sharp_pos = {P(v.co): creases.turn(v) for v in bm.verts if v.is_boundary and creases.is_sharp(v)
                 and not ((creases.turn(v) or 0) >= WEDGE_TIP and P(v.co) in wedge_tip_pos)}
    # thin wedge islands (a smooth wedge tip, see above): their weak seams (< WEDGE_SEAM) stay
    # smooth - on hair 13768 a 29 deg seam of such a wedge made a third crease and so a corner;
    # a general 30 deg seam threshold moved Technic parts by up to 0.32 (run 56)
    wedge_isl = {f[isl] for v in wedge_tips if (creases.turn(v) or 0) >= WEDGE_SEAM_TIP for f in v.link_faces}
    w.interior, w.sharp_pos, w.wedge_isl = interior, sharp_pos, wedge_isl


def _weld_seams(w):
    """Stage 3. Reads orig, bm, isl. Replaces bm and isl (an attempt that loses a face starts again from a copy,
    leaving those points apart). Adds tm (the weld map of the last attempt), skip (positions left apart)."""
    orig, bm, isl = w.orig, w.bm, w.isl
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
        tm = bmesh.ops.find_doubles(bm, verts=bnd, dist=config.MERGE_DIST)["targetmap"]
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
    w.bm, w.isl, w.tm, w.skip = bm, isl, tm, skip


def _seam_creases(w):
    """Stage 4. Reads bm, isl, kind_of, interior, wedge_isl, flat_share. Adds E (the creased edges: here logo edges and edges
    of more than two faces), seams (edges between islands), cand (seams sharp enough to stay hard: edge, angle,
    the two islands - stage 5 decides)."""
    bm, isl, kind_of, interior, wedge_isl = w.bm, w.isl, w.kind_of, w.interior, w.wedge_isl
    # on organic parts a wedge is a strand: its seams are hard edges as every seam (hair 23186: the 10-30 deg
    # strand edges left soft widened the strands and smeared their tips, run 291l); on mechanical parts the
    # wedge is a modelled chamfer's end and stays soft (47758: creased, its corner stood out 0.5)
    if w.flat_share < MECH_FLAT:
        wedge_isl = set()
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
            if kind_of[a] == "logo" and d > config.LOGO_CREASE_ANGLE:
                E.add(e)
            continue
        seams.add(e)
        # a seam of a thin wedge island is a hard edge only from WEDGE_SEAM (hair 13768: a 29 deg
        # seam made a third crease at the corner of the face opening, run 54/56)
        limit = WEDGE_SEAM if (a in wedge_isl or b in wedge_isl) else SEAM_SHARP
        if d >= limit:
            cand.append((e, d, a, b))
    w.E, w.seams, w.cand = E, seams, cand


def _hole_rings(w):
    """Stage 5. Reads bm, seams, cand. Adds ring (the seam edges between the walls of a polygonised hole - they
    stay smooth) and puts every other sharp seam of cand into E."""
    bm, E, seams, cand = w.bm, w.E, w.seams, w.cand
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
    w.ring = ring


def _island_creases(w):
    """Stage 6. Reads bm, isl, kind_of. Adds to E the edges inside islands that must stay hard; adds degen_v (the
    corners of degenerate faces - pinned in stage 8)."""
    bm, isl, kind_of, E = w.bm, w.isl, w.kind_of, w.E
    # flat stays flat (as R2 of the rules): a flat island without round outline gets all its
    # inner edges creased - left free, its open edges curled inward (run 50: 54200 0.29)
    # degenerate faces of the import (zero area: two corners at one point, 54200 faces 21/35
    # beside the foot of the body): inert - all edges creased, corners pinned (run 50e)
    degen = [f for f in bm.faces if f.calc_area() <= config.DEGENERATE_AREA]
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
                    if h not in patch and h[isl] == g[isl] and math.degrees(n0.angle(h.normal, 0.0)) <= config.FLAT_MAX_ANGLE:
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
    w.degen_v = degen_v


def _relief_tips(w):
    """Stage 7. Reads orig, bm, isl, kind_of, E, ring. Takes the relief tips out of E. Adds rung (those edges),
    tipv and ringv (the vertices of tips and rings - never pinned), ring_faces (faces that get smooth normals)."""
    orig, bm, isl, kind_of, E, ring = w.orig, w.bm, w.isl, w.kind_of, w.E, w.ring
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
    # islands of a ring are round now: their faces get smooth normals instead of the
    # imported per-wall normals, the ring edges are not sharp (nostril, run 48b)
    ring_isl = {f[isl] for e in ring for f in e.link_faces}
    ring_faces = [f.index for f in bm.faces if f[isl] in ring_isl]
    w.ringv, w.rung, w.tipv, w.ring_faces = ringv, rung, tipv, ring_faces


def _pinned_corners(w):
    """Stage 8. Reads orig, bm, isl, kind_of, E, flat_share, ringv, tipv, sharp_pos, degen_v. Adds V (the pinned
    corner vertices) and, for W15b, a few more edges to E."""
    orig, bm, isl, kind_of, E, flat_share = w.orig, w.bm, w.isl, w.kind_of, w.E, w.flat_share
    ringv, tipv, sharp_pos, degen_v = w.ringv, w.tipv, w.sharp_pos, w.degen_v
    # corner vertices on crease chains, K3/K3b of the rules applied to the chains
    CE = set(E) | {e for e in bm.edges if len(e.link_faces) == 1}
    # organic shapes (every face at the vertex in a curved island: hair, mane) are rounded
    # coarsely - a bend counts as a corner from ORGANIC_CORNER only; bricks keep SHARP_TURN
    # (run 53: the face opening of hair 13768 stayed angular at 47 deg on the left)
    def organic(v):
        return bool(v.link_faces) and all(kind_of[f[isl]] == "curved" for f in v.link_faces)

    def corner_turn(v):
        return ORGANIC_CORNER if organic(v) else config.SHARP_TURN

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

    # W17 (run 282, maintainer 2026-10-13: "18747 wird nicht richtig rund gemacht."): the middle point of a coarse
    # rounding - a corner rounded with two straight pieces (18747: bends of 23.5 / 45.1 / 21.4 degrees, pieces of
    # 0.3 mm). Its bend lies above SHARP_TURN, so on a brick it was pinned and the outline stayed two straight
    # pieces at every level, while the same point on the wall's other rim (all faces curved: ORGANIC_CORNER) was
    # free. It stays free when it touches a curved island (the wall of the rounding), its two pieces are about the
    # same length, and the creased line goes on at both neighbours with a gentle bend the same way - the three
    # bends making no more than ROUNDING_TOTAL. A chamfer (45 / 45) and a single kink have no such neighbours.
    # Only small roundings: the free point gives way by |a + b - 2v| / 6 (the limit of a creased line), 0.040 on
    # 18747; above ROUNDING_DEPTH the corner stays (library, run 282: the larger ones are corners of organic
    # shapes with pieces of 1.3 to 3.3 mm - the tip of the mudguard 31582 would lose 0.29).
    #
    # The same rounding on the outline of a flat face (maintainer 2026-10-14, 18747 again: "Prüfst Du beide
    # Seiten?" - the back of the plate was round, the stud side kept two straight pieces at both lower corners):
    # there "flat stays flat" (W3) creases the edges inside the face, they end in the points of the rounding and
    # make each of them a corner of three creased edges. So the rounding is read along the rim - the creased edges
    # that are no such inner edges - and where it is one, the inner edges are released at its three points (as W16
    # does at a gentle arc; the face stays planar, its outline stays creased).
    def inner_flat(e):
        return (len(e.link_faces) == 2 and e.link_faces[0][isl] == e.link_faces[1][isl]
                and kind_of[e.link_faces[0][isl]] == "flat")

    def rim(v):
        return [e for e in chain(v) if not inner_flat(e)]

    def coarse_rounding(v, t):
        if not COARSE_ROUNDING or not config.SHARP_TURN < t <= ORGANIC_CORNER:
            return False
        if not any(kind_of[f[isl]] == "curved" for f in v.link_faces):
            return False
        if len(rim(v)) != 2:
            return False
        a, b = rim(v)
        la, lb = a.calc_length(), b.calc_length()
        if min(la, lb) < 1e-9 or max(la, lb) > ROUNDING_RATIO * min(la, lb):
            return False
        if ((a.other_vert(v).co - v.co) + (b.other_vert(v).co - v.co)).length / 6.0 > ROUNDING_DEPTH:
            return False
        bend = (a.other_vert(v).co - v.co).normalized() + (b.other_vert(v).co - v.co).normalized()
        if bend.length < 1e-9:
            return False
        bend.normalize()
        total = t
        for e in (a, b):
            n = e.other_vert(v)
            back, best = (v.co - n.co).normalized(), None
            for x in rim(n):                    # the line goes on along the creased edge that turns least
                on = x.other_vert(n).co - n.co
                if x is e or on.length < 1e-9:
                    continue
                turn = 180.0 - math.degrees(back.angle(on))
                if best is None or turn < best[0]:
                    best = (turn, back + on.normalized())
            if (best is None or not ARC_RELEASE_TURN < best[0] < config.SHARP_TURN or best[1].length < 1e-9
                    or best[1].normalized().dot(bend) <= 0.5):
                return False
            total += best[0]
        return total <= ROUNDING_TOTAL

    def rim_turn(v):
        a, b = rim(v)
        p, q = a.other_vert(v).co - v.co, b.other_vert(v).co - v.co
        return None if p.length < 1e-9 or q.length < 1e-9 else 180.0 - math.degrees(p.angle(q))
    g = vars(creases)                   # the crease rules read these two functions
    keep = g["boundary_neighbours"], g["_turn"]
    g["boundary_neighbours"], g["_turn"] = nb, tturn
    try:
        V = {v for v in bm.verts if len(chain(v)) == 2 and v not in ringv and v not in tipv
             and (t := tturn(v)) is not None and (t > corner_turn(v) or designed(v, t))
             and not creases._is_round(v) and not groove_end(v)}
        rounded = {v for v in V if not designed(v, t := tturn(v)) and coarse_rounding(v, t)}
        V -= rounded
        # ... and on the outline of a flat face: a point with inner edges of the face besides its two rim edges
        on_flat = {v for v in bm.verts if len(chain(v)) > 2 and v not in ringv and v not in tipv and v not in degen_v
                   and len(rim(v)) == 2 and (t := rim_turn(v)) is not None and coarse_rounding(v, t)}
        for v in on_flat:
            for u in [v] + [e.other_vert(v) for e in rim(v)]:
                if u not in V:
                    E.difference_update([e for e in u.link_edges if e in E and inner_flat(e)])
        rounded |= on_flat
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
          and v not in ringv and v not in tipv and not groove_end(v) and v not in rounded
          and sum(1 for e in v.link_edges if e in E) < 3}
    V |= degen_v
    w.V, w.rounded, w.rounded_points = V, len(rounded - V), rounded - V        # (the points: for W18)


def _rounding_ends(w):
    """Stage 8b, W18 (run 283, maintainer 2026-10-14 on 18747: "Nur die untere Seite wird unterteilt, nicht die
    obere"). Reads bm, E, V, seams, rounded_points. Adds soft (the seams released: edge, the face of the rounding's
    wall), supports (points made), new_points, corners_before (the corners of every face it changes, as they were);
    takes the seams out of E and the ends of roundings out of V, splits edges of the cage and cuts faces.

    A coarse rounding (W17) is the wall between two rims. Where that wall meets the next wall the import can
    have a hard edge - a seam across the wall. Its two ends then carry three creased edges each (the rim of the
    rounding, the rim going on, the seam): corners for the subdivision, and the outline keeps a kink there at every
    level (18747: 21.8 degrees where the rounding meets the top; at the side, where the import has no such edge and
    a point 0.29 mm on, the rounding runs out softly). Taking the crease off the seam alone moves the kink instead
    of removing it: the rim then goes on for 2 mm without a point and the end slides along it. And a point on the
    rim alone leaves the seam itself to the middle of the next wall: the surface gives way most between the rims
    (library, run 283: by 0.15 mm on walls 6 to 9 mm wide; two parts folded). The side has what it takes - an edge
    across the next wall, one piece from the rounding. So
      the seam is released (no crease, no hard edge; the wall takes the next wall's normal along it), and
      the next wall gets that edge: a point one piece from the seam on each of its two edges there (the next
      point of the edge if it is no further than ROUNDING_RATIO pieces), the face cut from one to the other.
    The next wall has to be a convex face for that.
    A seam counts when its two faces bend by less than SHARP_TURN and one of its ends is such an end of a rounding
    W17 has freed (the rim's next point is its middle point): just these three creased edges, the rim of the rounding
    on one face and the rim going on on the other, bending on gently, the end giving way by no more than
    ROUNDING_DEPTH. Only W17's roundings: the same pattern at a point of a polygonised arc (18747: the outline of the
    body, bends of 27 and 33 degrees, where it meets this very seam) is no rounded corner. (On 18747 both faces
    of the seam lie in one curved island - the band round the plate; the import has the edge split.) The seam's
    other end, if it is not one too (18747: there the rim turns by 65 degrees into the outline of the body), is
    pinned and stays a corner - moved by what the free end gives way (18747: 0.019 mm down), so that the seam stays
    level: left where it was, it stood out above the lowered rim as a peak in the outline (seen from the back)."""
    bm, E, V = w.bm, w.E, w.V
    w.soft, w.supports, w.new_points, w.corners_before = [], 0, set(), {}
    if not (ROUND_ENDS and COARSE_ROUNDING):
        return
    fi = bm.faces.layers.int.get("rb_fi")
    off = NO_ENDS[0] or ()

    def left_out(f):
        return (f[fi] if fi is not None else f.index) in off

    def creased(v):
        return [e for e in v.link_edges if e in E or len(e.link_faces) == 1]

    def convex(f):
        n, vs = f.normal, [v.co for v in f.verts]
        k = len(vs)
        return all((vs[(i + 1) % k] - vs[i]).cross(vs[(i + 2) % k] - vs[(i + 1) % k]).dot(n) > -1e-9 for i in range(k))

    def end(s, n, wall, plane):
        """(rim piece of the rounding, its other point, piece length, what the end gives way) at the end `n` of the
        seam `s`, or the reason why `n` is no end of a rounding."""
        others = [e for e in creased(n) if e is not s]
        if len(others) != 2 or n in w.degen_v:
            return f"{len(others) + 1} creased edges"
        e = next((x for x in others if x in wall.edges), None)
        r = others[1] if e is others[0] else others[0]
        if e is None or r not in plane.edges or r in wall.edges:
            return "the rims are not one on the wall and one on the face beyond"
        m = e.other_vert(n)
        if m not in w.rounded_points or m in V:
            return "no rounding W17 has freed"
        back, on = m.co - n.co, r.other_vert(n).co - n.co
        le, lr = back.length, on.length
        if le < 1e-9 or lr < 1e-9:
            return "a rim without length"
        turn = 180.0 - math.degrees(back.angle(on))
        if not ARC_RELEASE_TURN < turn < config.SHARP_TURN:
            return "the rim bends on by %.1f" % turn
        far = on * (le / lr) if lr > ROUNDING_RATIO * le else on
        if (back + far).length / 6.0 > ROUNDING_DEPTH:
            return "gives way by %.3f" % ((back + far).length / 6.0)
        return e, m, le, (back + far) / 6.0

    found = []
    for s in sorted((e for e in E if len(e.link_faces) == 2), key=lambda e: e.index):
        fa, fb = s.link_faces
        if off and (left_out(fa) or left_out(fb)):
            continue
        if not ARC_RELEASE_TURN < math.degrees(fa.normal.angle(fb.normal, 0.0)) < config.SHARP_TURN:
            continue
        for wall, plane in ((fa, fb), (fb, fa)):            # which of the two faces is the wall of the rounding
            ends = [end(s, n, wall, plane) for n in s.verts]
            if not convex(plane):
                ends = ["the face beyond is not convex"] * 2
            if ENDS_LOG is not None:
                ENDS_LOG.append((w.orig.name, tuple(round(c, 3) for c in (s.verts[0].co + s.verts[1].co) / 2),
                                 [x if isinstance(x, str) else "end of a rounding" for x in ends]))
            ends = [None if isinstance(x, str) else x for x in ends]
            if ends[0] is not None or ends[1] is not None:
                found.append((s, wall, ends))
                break
    # a point that is the end of a rounding on one seam and not on another stays a corner; a seam left without a
    # free end is not released
    while True:
        hard = {n for s, _wall, ends in found for n, x in zip(s.verts, ends, strict=True) if x is None}
        keep = [(s, wall, ends) for s, wall, ends in found
                if any(x is not None and n not in hard for n, x in zip(s.verts, ends, strict=True))]
        if len(keep) == len(found):
            break
        found = keep
    if not found:
        return
    for s, wall, _ends in found:
        E.discard(s)
        w.soft.append((s, wall))
        V.difference_update(s.verts)
    V |= hard                                   # the end of a rounding is free, any other end stays a corner
    moved = set()
    for s, _wall, ends in found:
        for n, x in zip(s.verts, ends, strict=True):
            other = s.other_vert(n)
            if x is not None and n not in hard and other in hard and other not in moved and not other.is_boundary:
                other.co += x[3]                # ... level with the free end
                moved.add(other)

    def remember(f):
        if f[fi] not in w.corners_before:       # (the first time: as the import has them)
            w.corners_before[f[fi]] = list(f.verts)

    def support(plane, s, n, d):
        """The point of the next wall's outline `d` from the seam's end `n`: the next point of that edge if it is
        near enough, else a new one on it."""
        t = next(x for x in plane.edges if n in x.verts and x is not s)
        length = t.calc_length()
        if length <= ROUNDING_RATIO * d:
            return t.other_vert(n)
        for f in t.link_faces:
            remember(f)
        new_edge, new_vert = bmesh.utils.edge_split(t, n, d / length)
        for group in (E, w.seams, w.ring, w.rung):
            if t in group:
                group.add(new_edge)
        w.new_points.add(new_vert)
        w.supports += 1
        return new_vert

    bm.faces.index_update()
    new_faces = []
    for s, wall, ends in found:
        plane = next(f for f in s.link_faces if f is not wall)
        piece = [x[2] if x is not None and n not in hard else None for n, x in zip(s.verts, ends, strict=True)]
        # (a pinned end: the piece of the free one)
        piece = [p or q for p, q in zip(piece, reversed(piece), strict=True)]
        pts = [support(plane, s, n, d) for n, d in zip(s.verts, piece, strict=True)]
        if pts[0] is not pts[1] and bm.edges.get(pts) is None:
            remember(plane)
            new_faces.append(bmesh.utils.face_split(plane, pts[0], pts[1])[0])
    if new_faces:                               # the import's faces first and in their order, then the cut-off ones
        after = {f: k for k, f in enumerate(new_faces)}
        bm.faces.sort(key=lambda f: len(bm.faces) + after[f] if f in after else f.index)
    bm.verts.index_update(); bm.edges.index_update(); bm.faces.index_update()
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    bm.normal_update()


def _t_vertices(w):
    """Stage 9. Reads bm, V. Adds tv [(vertex, host face)] and pins (adds to V) the T vertices, the ends of their
    host edges and every open point that stays apart."""
    bm, V = w.bm, w.V
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
            for co, vi, _ in kd.find_range((a + b) / 2, L / 2 + config.MERGE_DIST):
                v = bm.verts[vi]
                if v in e.verts:
                    continue
                t = (co - a).dot(ab) / (L * L)
                if 1e-3 < t < 1 - 1e-3 and (a + ab * t - co).length < config.MERGE_DIST:
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
            if e.is_boundary and (bm.verts[vi].co - (e.verts[0].co + e.verts[1].co) / 2).length <= e.calc_length() / 2 + config.MERGE_DIST:
                V |= set(e.verts)
    w.tv = tv


def _cage_corners(w, wm):
    """For the normals of the cage `wm`: per corner of the cage the corner of the import it is (welding keeps faces
    and corners in order; -1 for the corner of a point W18 made), for each such new corner a corner of the import
    whose normal it takes (pairs: corner of the cage, corner of the import - one of its own face where it has one:
    a face cut off between two support edges has only new points), and the corners along the released seams as
    pairs (corner of the rounding's wall, corner of the face beyond at the same point)."""
    nl, nf = len(wm.loops), len(wm.polygons)
    lt_w = np.empty(nf, np.int64); wm.polygons.foreach_get("loop_total", lt_w)
    ls_w = np.cumsum(lt_w) - lt_w
    lt_o = np.empty(len(w.orig.polygons), np.int64); w.orig.polygons.foreach_get("loop_total", lt_o)
    ls_o = np.cumsum(lt_o) - lt_o
    own = np.arange(nf, dtype=np.int32)
    if wm.attributes.get("rb_fi") is not None:
        wm.attributes["rb_fi"].data.foreach_get("value", own)
    src = np.repeat(ls_o[own] - ls_w, lt_w) + np.arange(nl)         # right for every face W18 left alone
    fill, softened = [], []
    if not w.soft:
        return src, fill, softened
    lv = np.empty(nl, np.int64); wm.loops.foreach_get("vertex_index", lv)
    made = {v.index for v in w.new_points}
    for f in np.nonzero(np.isin(own, list(w.corners_before)))[0].tolist():
        was = {v.index: k for k, v in enumerate(w.corners_before[int(own[f])])}
        corners = range(int(ls_w[f]), int(ls_w[f] + lt_w[f]))
        for j in corners:
            k = was.get(int(lv[j]))
            src[j] = -1 if k is None or int(lv[j]) in made else ls_o[own[f]] + k
        old = next((int(src[j]) for j in corners if src[j] >= 0), int(ls_o[own[f]]))
        fill.extend((j, old) for j in corners if src[j] < 0)
    for s, wall in w.soft:
        plane = next(f for f in s.link_faces if f is not wall)
        for v in s.verts:
            at = [next(j for j in wm.polygons[f.index].loop_indices if lv[j] == v.index) for f in (wall, plane)]
            softened.append((at[0], at[1]))
    return src, fill, softened


def _work_mesh(w, arc_released):
    """Stage 10. Reads everything; frees bm. Returns (work mesh, T vertices, report) - the result of weld()."""
    orig, bm, E, V, seams, ring, rung = w.orig, w.bm, w.E, w.V, w.seams, w.ring, w.rung
    ring_faces, tm, tv, skip = w.ring_faces, w.tm, w.tv, w.skip
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
    soft_edges = {s.index for s, _wall in w.soft}       # W18: a released seam is no hard edge any more
    attr("sharp_edge", 'BOOLEAN', 'EDGE', [e.index for e in seams - ring - rung if e.index not in soft_edges]
         + [i for i, x in enumerate(old) if x and i not in soft_edges], True)
    ndiff, zero = 0.0, 0
    if orig.has_custom_normals:
        n0 = np.empty(len(orig.loops) * 3); orig.corner_normals.foreach_get("vector", n0)
        src, fill, softened = _cage_corners(w, wm)      # corner of the cage -> corner of the import (-1: W18's)
        nn = n0.reshape(-1, 3)[np.maximum(src, 0)]
        for j, k in fill:                       # a point W18 made: the normal of a corner the import's face has
            nn[j] = n0.reshape(-1, 3)[k]
        for j, k in softened:                   # the wall takes the next wall's normal along a released seam
            nn[j] = nn[k]
        smooth_faces = ring_faces       # relief tips keep the imported normals (run 48e: smooth ones darkened the tips)
        if smooth_faces:
            sf = wm.attributes.get("sharp_face")
            for i in smooth_faces:
                p = wm.polygons[i]
                nn[p.loop_start:p.loop_start + p.loop_total] = 0.0     # zero = Blender's smooth normal
                if sf:
                    sf.data[i].value = False
        wm.normals_split_custom_set(nn)
        n1 = np.empty(len(wm.loops) * 3); wm.corner_normals.foreach_get("vector", n1)
        a0, a1 = n0.reshape(-1, 3)[np.maximum(src, 0)], n1.reshape(-1, 3)
        ok = (np.linalg.norm(a0, axis=1) > 0.5) & (np.linalg.norm(a1, axis=1) > 0.5)   # zero normals of slivers
        for i in ring_faces:
            p = wm.polygons[i]
            ok[p.loop_start:p.loop_start + p.loop_total] = False                     # smoothed on purpose
        zero = int((~ok).sum())
        ok[src < 0] = False                                                          # W18: made or softened on purpose
        ok[[j for j, _k in softened]] = False
        dots = np.clip((a0 * a1).sum(1)[ok], -1, 1)
        ndiff = float(np.degrees(np.arccos(dots.min()))) if len(dots) else 0.0
    rungs_out = [((e.verts[0].co + e.verts[1].co) / 2, e.calc_length()) for e in rung]
    rep = dict(welded=len(tm), seams=len(seams), creased_seams=len(seams & E), ring_edges=len(ring),
               corners=len(V), relief_tips=len(rung), t_verts=len(tv), normals_diff=round(ndiff, 3),
               zero_normals=zero, unwelded=len(skip), arc_released=arc_released)
    bm.free()
    rep["_rungs"] = rungs_out
    return wm, tv, rep


ARC_RELEASE_TURN = 0.5   # W16: below this an outline vertex lies on a straight line - nothing to release


def release_arc_corners(E, V, kind_of, isl):
    """W16 (run 206): coarse arcs across a flat island. "Flat stays flat" creases every inner edge of a
    flat island; where such an inner edge (0 deg) ends on the island's outline, the outline vertex has
    3+ creased edges and the subdivision keeps it as a corner - the crease curve along a rounding turns
    into a polyline. Curved slopes 29119 / 29120 (user report 2026-10-04): the curved top meets the 45 deg
    face in turns of 3.8 / 4.9 deg, below ROUND_TURN, so the face is "flat", not "flat-round".
    The inner edges are released at an outline vertex that lies on one crease curve (exactly two other
    creased edges), bends ARC_RELEASE_TURN..SHARP_TURN, touches a curved island and has a neighbour on
    the curve bending alike - a coarse arc. A single designed kink (4587's hitching rail, 9.4 deg between
    straight runs) has no such neighbour and keeps its corner (without the neighbour test it was rounded
    off by 0.41). The face stays planar: every subdivision point of a planar island is a combination of
    planar points. Removes the released edges from E; returns their number."""
    def inner_flat(e):
        return (len(e.link_faces) == 2 and e.link_faces[0][isl] == e.link_faces[1][isl]
                and kind_of[e.link_faces[0][isl]] == "flat")

    def curve(v):
        """(turn, bend direction, the two neighbours) along the crease curve through v, or None."""
        rest = [e for e in v.link_edges if e in E and not inner_flat(e)]
        if len(rest) != 2:
            return None
        nb = [e.other_vert(v) for e in rest]
        a, b = nb[0].co - v.co, nb[1].co - v.co
        if a.length < 1e-9 or b.length < 1e-9:
            return None
        bend = a.normalized() + b.normalized()
        return 180.0 - math.degrees(a.angle(b)), bend.normalized() if bend.length > 1e-12 else bend, nb

    gentle = lambda t: ARC_RELEASE_TURN < t < config.SHARP_TURN
    free = set()
    for v in {v for e in E if inner_flat(e) for v in e.verts}:
        if v in V or not any(kind_of[f[isl]] == "curved" for f in v.link_faces):
            continue
        c0 = curve(v)
        if c0 is None or not gentle(c0[0]):
            continue
        if not any((c1 := curve(w)) is not None and gentle(c1[0]) and c1[1].dot(c0[1]) > 0.5 for w in c0[2]):
            continue
        free |= {e for e in v.link_edges if e in E and inner_flat(e)}
    E -= free
    return len(free)


def t_gaps(wm, cp, tv, level):
    """Distance of each T vertex's limit position to the limit outline of its host face."""
    if not tv:
        return 0.0
    pass
    config.LEVELS = level
    starts = checks.sub_offsets(wm, cp)
    co = np.empty(len(cp.vertices) * 3); cp.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    ev = np.empty(len(cp.edges) * 2, np.int64); cp.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
    le = np.empty(len(cp.loops), np.int64); cp.loops.foreach_get("edge_index", le)
    cnt = np.bincount(le, minlength=len(cp.edges))
    lt = np.empty(len(cp.polygons), np.int64); cp.polygons.foreach_get("loop_total", lt)
    lface = np.repeat(np.arange(len(cp.polygons)), lt)
    owner = np.repeat(np.arange(len(starts) - 1), np.diff(starts))      # (by cage face: a T point's host is one)
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
    dg = workscene.depsgraph_of(work)
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
        bad = checks.flipped_faces(work, me=wm)
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
    work = bpy.data.objects.new(workscene.WORK_NAME, wm)
    workscene.link_work(work)
    creases.add_subsurf(work)
    bad = bulge_check(work, wm, rep.pop("_rungs", []))
    if bad:
        EXCLUDE_RUNG.update(P(m) for m in bad)
        bpy.data.objects.remove(work); bpy.data.meshes.remove(wm)
        wm, tv, rep = weld(orig)
        rep.pop("_rungs", None)
        work = bpy.data.objects.new(workscene.WORK_NAME, wm)
        workscene.link_work(work)
        creases.add_subsurf(work)
    rep["tips_bulged"] = len(bad)
    rep["repair_passes"] = 0
    if repair:
        work, wm, tv, rep = repair_work(orig, work, wm, tv, rep)
    if config.SHADING == "geometric":
        E = {i for i, d in enumerate(wm.attributes["crease_edge"].data) if d.value > 0}
        shading.geometric_shading(work, wm, E)
    return work, wm, tv, rep


def repair_work(orig, work, wm, tv, rep):
    """Fold repair (W10) and the W13 fallback on a welded work object."""
    rep["repair_passes"] = passes = repair_folds(work, wm)
    # W13 fallback (run 58, Bugatti 35188): plane creases can leave folds the repair cannot
    # remove - weld again without the W13 edges at the folding faces. Folds can only be
    # left when the repair used all its passes (run 59: no extra evaluation otherwise).
    left = checks.flipped_faces(work, me=wm) if PLANE_RATIO and passes >= REPAIR_PASSES else set()
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
        work = bpy.data.objects.new(workscene.WORK_NAME, wm)
        workscene.link_work(work)
        creases.add_subsurf(work)
        rep["repair_passes"] = repair_folds(work, wm)
        rep["plane_released"] = len(left)
    return work, wm, tv, rep


def _bake_work(orig, work, levels, tv):
    """The copies of the given levels from the finished work object, marked as made by the weld."""
    made = {}
    for lv in sorted(levels):
        cp = copies.bake_copy(orig, work, lv)
        cp["rb_method"] = "weld"
        cp["rb_tv"] = [x for pair in tv for x in pair]      # T vertices for the check (vertex, host face)
        made[lv] = cp
    return made


def baked_folds(orig, cp, level):
    """Original faces whose children fold in a baked copy of `level` (as Check / verify_part)."""
    keep = config.LEVELS
    config.LEVELS = level                       # sub_offsets maps the children by LEVELS
    try:
        return checks.flipped_faces(None, ev=cp, me=orig)
    finally:
        config.LEVELS = keep


def _fit(work, wm, rep):
    """The shrink compensation of the cage (UPDATES #51), its numbers into the report."""
    free = rep.pop(shrink.SHRINK_FREE, [])
    rep["shrink_points"], rep["shrink_max"], rep["shrink_left"], rep["shrink_cylinders"] = shrink.compensate_shrink(work, wm, free)


def _bake_weld(orig, levels, method_rep=None):
    from . import batches
    if batches.wanted(orig):                    # a large mesh: batch by batch of islands (UPDATES #54, run 287)
        return batches.bake(orig, levels)
    # run 59 tried baking first and checking folds on the copy: 306 of Ratatouille's 667
    # meshes need the repair anyway and were then baked twice - slower (349 -> 396 s)
    work, wm, tv, rep = weld_work(orig)
    try:
        _fit(work, wm, rep)
        if bevel.signature():                   # Edges: Bevel - the part's own sharp edges, as bevel weight on
            rep["bevel_edges"] = bevel.mark_edges(orig, wm)      # the cage; the subdivision carries it along
        made = _bake_work(orig, work, levels, tv)
        # W10b (run 211): the repair checks the work object at the modifier's quality 3, the copies are baked at
        # the bake quality (10 / 6) - a fold that only exists from quality 4 up passes the repair (46524: four
        # tiny faces). The baked copy is tested for free; only if it folds is the repair run again at the bake
        # quality and the copies baked again (1 of 1,372 parts in the library; doing every check at the bake
        # quality cost 2.5-3.6x the repair time).
        lv = config.RENDER_LEVEL if config.RENDER_LEVEL in made else max(made)
        folded = baked_folds(orig, made[lv], lv) if rep.get("shrink_points") else ()
        if folded:
            # the compensation must not cost a fold: the islands that fold go back to the import's places, baked
            # again (per island since UPDATES #54 - before, one fold took it back on the whole mesh)
            back = shrink.undo_shrink(work, wm, folded)
            rep["shrink_dropped"], rep["shrink_points"] = 1, max(0, rep["shrink_points"] - back)
            for cp in made.values():
                copies.discard_copy(orig, cp)
            made = _bake_work(orig, work, levels, tv)
        folded = baked_folds(orig, made[lv], lv) if rep.get("rounding_ends") else ()
        if folded:
            # W18 must not cost a fold (library, run 283: con1 folded on two faces with it, on none without): the
            # islands that fold are welded again as rules 3.7 make them (per island since UPDATES #54)
            own = np.arange(len(wm.polygons))
            at = wm.attributes.get("rb_fi")
            if at is not None:
                at.data.foreach_get("value", own)
            off = set(own[meshparts.island_faces(wm, folded)].tolist())
            for cp in made.values():
                copies.discard_copy(orig, cp)
            bpy.data.objects.remove(work); bpy.data.meshes.remove(wm)
            NO_ENDS[0] = off
            try:
                work, wm, tv, rep = weld_work(orig)
            finally:
                NO_ENDS[0] = None
            rep["rounding_ends_dropped"] = 1
            _fit(work, wm, rep)
            if bevel.signature():
                rep["bevel_edges"] = bevel.mark_edges(orig, wm)
            made = _bake_work(orig, work, levels, tv)
        if baked_folds(orig, made[lv], lv):
            work.modifiers["Subdivision"].quality = copies.bake_quality(orig)
            rep["repair_bake_quality"] = repair_folds(work, wm)
            for cp in made.values():
                copies.discard_copy(orig, cp)
            made = _bake_work(orig, work, levels, tv)
        if bevel.signature():
            # the checks read a copy by the layout of the subdivision; the bevel changes it. So the verdict is
            # taken now and kept on the copy, then the copy is bevelled (copy_folds, weld_gap read the verdict).
            for lv in list(made):
                cp = made[lv]
                cp[bevel.EDGE_FOLDS] = ",".join(str(i) for i in sorted(baked_folds(orig, cp, lv)))
                cp[bevel.EDGE_GAP] = float(weld_gap(orig, cp))
                new = bevel.bevel_copy(cp)
                copies.swap_copy(orig, cp, new)
                made[lv] = new
    finally:
        bpy.data.objects.remove(work)
        bpy.data.meshes.remove(wm)
        workscene.drop_work_scene()
    return made, rep


def bake_levels(orig, levels):
    """Bake further copies of an already processed mesh - the creases are on the original,
    so no rules run: only the subdivision (variant of the existing copies)."""
    have = copies.copies_by_level(orig)
    variant = next((m.get("rb_variant") for m in have.values() if m.get("rb_variant")), config.SHADING)
    if config.METHOD == "weld" and (not have or any(m.get("rb_method") == "weld" for m in have.values())):
        keep, config.SHADING = config.SHADING, variant       # weld copies: the creases live only in the welded copy
        try:
            made, _ = _bake_weld(orig, levels)
        finally:
            config.SHADING = keep
        for lv, cp in made.items():
            cp.name = f"{orig.name} L{lv}"
        return made
    keep, config.SHADING = config.SHADING, variant
    work = workscene.work_object(orig)
    made = {}
    try:
        creases.add_subsurf(work)
        if variant == "geometric":
            E = {i for i, d in enumerate(orig.attributes["crease_edge"].data) if d.value > 0}
            shading.geometric_shading(work, orig, E)
        for lv in levels:
            made[lv] = copies.bake_copy(orig, work, lv)
            made[lv].name = f"{orig.name} L{lv}"
    finally:
        bpy.data.objects.remove(work)
        workscene.drop_work_scene()
        config.SHADING = keep
    return made


def set_levels(orig, view, render, obs=None):
    """Viewport / render level of a processed mesh: bake what is missing, point the links
    (all objects of this mesh unless `obs` is given; switched-off ones stay off), drop
    copies of other levels that nothing uses. Returns the number of copies baked."""
    missing = copies.missing_levels(orig, view, render)
    if missing:
        bake_levels(orig, missing)
    have = copies.copies_by_level(orig)
    orig["rb_view"] = have[view].name if view else ""
    orig["rb_render"] = have[render].name if render else ""
    if obs is None:
        obs = [o for o in bpy.data.objects if o.type == 'MESH' and copies.original_of(o.data) == orig]
    copies.point_links([o for o in obs if not o.get("rb_off")], orig, "view")
    keep = {have[lv] for lv in (set(config.PRE_LEVELS) | {view, render}) if lv in have}
    copies.drop_copies(orig, keep)
    return len(missing)


# ---- up to add-on 1.3: masters, instances and per-object modifiers (removed on Apply)


def process(me, obs):
    """Rules 3.0 (weld, run 48-50): the original stays untouched (no attributes either); a
    temporary welded copy gets the creases and is subdivided into the copies for viewport
    and render, which every link uses. `me` may already be a copy: its original is processed."""
    gen = process_steps(me, obs)
    while True:
        try:
            next(gen)
        except StopIteration as e:
            return e.value


def process_steps(me, obs):
    """process as a step generator: a mesh baked in batches (batches.py, UPDATES #54) yields (fraction, text) after
    each batch, so that Apply's progress bar moves within a large part; returns the report."""
    from . import batches
    if config.METHOD != "weld":
        return process_24(me, obs)
    orig = prepare(me, obs)
    levels = bake_levels_wanted()
    if batches.wanted(orig):
        made, rep = yield from batches.bake_steps(orig, levels)
    else:
        made, rep = _bake_weld(orig, levels)
    return finish(orig, obs, made, rep)


def prepare(me, obs):
    """The original of `me`, instances and masters of older add-on versions undone."""
    orig = copies.original_of(me)
    for ob in obs:             # up to add-on 1.3: instances / per-object modifiers
        copies.unlink_instance(ob)
    copies.remove_master(orig)
    return orig


def bake_levels_wanted():
    return (set(config.PRE_LEVELS) | {config.VIEW_LEVEL, config.RENDER_LEVEL}) - {0}


def finish(orig, obs, made, rep, check=True):
    """Baked copies {level: mesh} -> old copies replaced, names, links on the view copy.
    Also used for copies baked by a worker process (headless run with --jobs, run 59)."""
    view = made.get(config.VIEW_LEVEL, orig)
    new = set(made.values())      # by data-block: a copy in the cache file has the same name (run 62)
    for m in [m for m in copies.all_copies(orig) if m not in new]:
        m.user_remap(view)
        bpy.data.meshes.remove(m)
    for lv, cp in made.items():
        cp.name = f"{orig.name} L{lv}"
    orig["rb_view"] = made[config.VIEW_LEVEL].name if config.VIEW_LEVEL else ""
    orig["rb_render"] = made[config.RENDER_LEVEL].name if config.RENDER_LEVEL else ""
    orig.use_fake_user = True
    copies.point_links(obs, orig, "view")
    rc = made.get(config.RENDER_LEVEL) or made.get(config.VIEW_LEVEL)
    if check:              # a worker's report already has it (run 59)
        rep["flipped"] = len(copy_folds(orig, rc)) if rc else 0
    if any(bevel.is_bevelled(cp) for cp in made.values()):     # the material's own rounding off for these copies
        bevel.build_switches(orig)
    rep["t_fans_creased"], rep["t_fans_unresolved"] = 0, 0   # T points are pinned (rep["t_verts"])
    rep["copies"] = {lv: len(cp.polygons) for lv, cp in made.items()}
    return rep


def weld_gap(orig, cp):
    """Largest T gap of a weld copy (the only places where a welded copy can open)."""
    if bevel.is_bevelled(cp) and bevel.EDGE_GAP in cp:      # measured before the bevel changed the layout
        return float(cp[bevel.EDGE_GAP])
    flat = list(cp.get("rb_tv", []))
    tv = list(zip(flat[0::2], flat[1::2]))
    return t_gaps(orig, cp, tv, int(cp.get("rb_level", config.LEVELS))) if tv else 0.0


def process_24(me, obs):
    """Creases on the original mesh, then the subdivided copies for viewport and render,
    which every link uses (run 38). `me` may already be a copy: its original is processed.
    The checks run on a temporary work object at the check level LEVELS, with custom
    normals off (face normals only: evaluation twice as fast, run 32)."""
    pass
    orig = copies.original_of(me)
    config.PARTIAL.clear()
    checks.escalate_faces.clear()     # per mesh: island keys are face indices (run 24 fix)
    for ob in obs:             # up to add-on 1.3: instances / per-object modifiers
        copies.unlink_instance(ob)
    copies.remove_master(orig)
    work = workscene.work_object(orig)
    try:
        mod = creases.add_subsurf(work)
        mod.use_custom_normals = False
        creases.GEOM_CACHE = {}
        try:
            rep = _process(orig, [work])
        finally:
            creases.GEOM_CACHE = None
        creases.add_subsurf(work)                       # custom normals back for variant A
        if config.SHADING == "geometric":
            E = {i for i, d in enumerate(orig.attributes["crease_edge"].data) if d.value > 0}
            shading.geometric_shading(work, orig, E)
        levels = (set(config.PRE_LEVELS) | {config.VIEW_LEVEL, config.RENDER_LEVEL}) - {0}      # chosen levels only (run 61)
        made = {lv: copies.bake_copy(orig, work, lv) for lv in sorted(levels)}
    finally:
        bpy.data.objects.remove(work)
        workscene.drop_work_scene()
    # older copies: every link still on one of them (also outside `obs`) moves to the new
    # viewport copy - links share the mesh - then they are removed
    view = made.get(config.VIEW_LEVEL, orig)
    new = set(made.values())      # by data-block: a copy in the cache file has the same name (run 62)
    for m in [m for m in copies.all_copies(orig) if m not in new]:
        m.user_remap(view)
        bpy.data.meshes.remove(m)
    for lv, cp in made.items():
        cp.name = f"{orig.name} L{lv}"
    orig["rb_view"] = made[config.VIEW_LEVEL].name if config.VIEW_LEVEL else ""
    orig["rb_render"] = made[config.RENDER_LEVEL].name if config.RENDER_LEVEL else ""
    orig.use_fake_user = True                    # stays in the file even when no link uses it
    copies.point_links(obs, orig, "view")
    rep["copies"] = {lv: len(cp.polygons) for lv, cp in made.items()}
    return rep


def copy_folds(orig, cp):
    """Faces of the original whose children in the copy flip (same test as the checks)."""
    if bevel.is_bevelled(cp) and bevel.EDGE_FOLDS in cp:    # tested before the bevel changed the layout
        return [int(x) for x in str(cp[bevel.EDGE_FOLDS]).split(",") if x]
    keep, config.LEVELS = config.LEVELS, int(cp.get("rb_level", config.LEVELS))
    try:
        return checks.flipped_faces(None, cp, orig)
    finally:
        config.LEVELS = keep


def _process(me, obs):
    merged = 0
    t_fans = 0
    if config.REPAIR_T:
        # repair T fans only where the plain rules fold
        bm = bmesh.new(); bm.from_mesh(me)
        config.PARTIAL.clear()
        E, V, _ = creases.rule_creases(bm, {})
        creases.unify_seams(bm, E, V)
        creases.write_creases(me, E, V); me.update()
        bm.free()
        folding = checks.flipped_faces(obs[0])
        if folding:
            t_fans = creases.repair_t_fans(me, folding)
    fans_creased, fans_open = creases.resolve_fans(me, obs[0])
    escalate = {}
    for p in range(1, config.MAX_PASSES + 1):
        bm = bmesh.new(); bm.from_mesh(me)
        config.PARTIAL.clear()
        config.PARTIAL.update(creases.FAN_W)
        E, V, stats = creases.rule_creases(bm, escalate)
        E |= creases.FAN_E
        stats["seam verts pinned"] = creases.unify_seams(bm, E, V)
        creases.write_creases(me, E, V)
        me.update()
        bad = checks.flipped_faces(obs[0])
        if not bad:
            bm.free()
            break
        bm.faces.ensure_lookup_table()
        for kind, comp, _ in creases.classify(bm):
            ids = {f.index for f in comp} & bad
            if config.ESCALATE == "none" or (config.ESCALATE == "curved" and kind != "curved"):
                ids = set()
            if ids:
                key = min(f.index for f in comp)
                escalate[key] = escalate.get(key, 0) + 1
                checks.escalate_faces.setdefault(key, set()).update(ids)
        bm.free()
    return dict(merged=merged, t_fans_creased=fans_creased, t_fans_unresolved=fans_open, passes=p, flipped=len(bad), creased_edges=len(E), partial_creases=len(config.PARTIAL),
                corner_verts=len(V), islands=dict(stats))
