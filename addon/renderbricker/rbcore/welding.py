"""The conversion of one part: weld the islands in a work copy, set the creases (W rules), repair
folds, bake the copies (process)."""
import bpy, bmesh, math
import numpy as np
from mathutils import Vector
from collections import defaultdict
from . import checks, config, copies, creases, shading


# ================================================================ rules 3.0: weld (runs 48-50)
SEAM_SHARP = 10.0        # dihedral at a former island boundary from which it stays hard


PLANE_RATIO = float(config.opt("--plane-ratio", "8"))     # W13: plane / face-across area ratio (0: off), run 58


PLANE_MIN_ANGLE = 10.0   # W13: only outline edges bending at least this much


PLANE_EDGES = [0]        # W13 counter (diagnostics)


PLANE_DEBUG = False


EXCLUDE_PLANE = []       # W13 released around these folding faces: (centre, reach), run 58


UV_SMOOTH = config.opt("--uv-smooth", "PRESERVE_BOUNDARIES")   # Subdivision modifier uv_smooth: Keep Boundaries (run 58)


UV_PROJECT = config.opt("--uv-project", "0") == "1"   # UVs from the original triangles - tested, off (run 58: distorts lettering)


UV_CHUNK = 2_000_000     # corners per step of the UV projection


INNER_SHARP = float(config.opt("--inner-sharp", "85"))   # inner island edge creased from this dihedral (W12, run 57)


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


orig_name = [""]


def weld(orig):
    orig_name[0] = orig.name
    bm = bmesh.new(); bm.from_mesh(orig)
    bm.faces.ensure_lookup_table()
    pass
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
    g = vars(creases)                   # the crease rules read these two functions
    keep = g["boundary_neighbours"], g["_turn"]
    g["boundary_neighbours"], g["_turn"] = nb, tturn
    try:
        V = {v for v in bm.verts if len(chain(v)) == 2 and v not in ringv and v not in tipv
             and (t := tturn(v)) is not None and (t > corner_turn(v) or designed(v, t))
             and not creases._is_round(v) and not groove_end(v)}
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
    pass
    config.LEVELS = level
    starts = checks.sub_offsets(wm)
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
    dg = copies.depsgraph_of(work)
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
    work = bpy.data.objects.new(copies.WORK_NAME, wm)
    copies.link_work(work)
    creases.add_subsurf(work)
    bad = bulge_check(work, wm, rep.pop("_rungs", []))
    if bad:
        EXCLUDE_RUNG.update(P(m) for m in bad)
        bpy.data.objects.remove(work); bpy.data.meshes.remove(wm)
        wm, tv, rep = weld(orig)
        rep.pop("_rungs", None)
        work = bpy.data.objects.new(copies.WORK_NAME, wm)
        copies.link_work(work)
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
        work = bpy.data.objects.new(copies.WORK_NAME, wm)
        copies.link_work(work)
        creases.add_subsurf(work)
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
            cp = copies.bake_copy(orig, work, lv)
            cp["rb_method"] = "weld"
            cp["rb_tv"] = [x for pair in tv for x in pair]      # T vertices for the check (vertex, host face)
            made[lv] = cp
    finally:
        bpy.data.objects.remove(work)
        bpy.data.meshes.remove(wm)
        copies.drop_work_scene()
    return made, rep


def process(me, obs):
    """Rules 3.0 (weld, run 48-50): the original stays untouched (no attributes either); a
    temporary welded copy gets the creases and is subdivided into the copies for viewport
    and render, which every link uses. `me` may already be a copy: its original is processed."""
    if config.METHOD != "weld":
        return process_24(me, obs)
    orig = prepare(me, obs)
    made, rep = _bake_weld(orig, bake_levels_wanted())
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
    rep["t_fans_creased"], rep["t_fans_unresolved"] = 0, 0   # T points are pinned (rep["t_verts"])
    rep["copies"] = {lv: len(cp.polygons) for lv, cp in made.items()}
    return rep


def weld_gap(orig, cp):
    """Largest T gap of a weld copy (the only places where a welded copy can open)."""
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
    work = copies.work_object(orig)
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
        copies.drop_work_scene()
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
    pass
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
