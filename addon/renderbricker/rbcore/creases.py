"""The crease rules: islands, round and sharp boundary corners, logos, T fans, seams (see docs/RULES.md)."""
import bmesh, math
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d
from collections import Counter, defaultdict
from . import checks, config, copies, welding


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
    if t is None or not (config.ROUND_TURN[0] < t < config.ROUND_TURN[1]):
        return False
    nb = boundary_neighbours(v)
    if len(nb) != 2:
        return False
    t1 = [turn(w) for w in nb]
    if all(x is not None and abs(x - t) <= config.ROUND_REGULAR for x in t1):
        return True                                  # period 1 (unchanged test)
    if any(x is None or not (config.ROUND_TURN[0] < x < config.ROUND_TURN[1]) for x in t1):
        return False
    # period 2: the vertices two steps away turn like this one
    t2 = []
    for w in nb:
        nxt = [u for u in boundary_neighbours(w) if u is not v]
        if len(nxt) != 1:
            return False
        t2.append(turn(nxt[0]))
    return all(x is not None and abs(x - t) <= config.ROUND_REGULAR for x in t2)


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
    arc = lambda x: x is not None and ARC_MIN_TURN < x < config.ROUND_TURN[1]
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
    return t is not None and t > config.SHARP_TURN and not is_round(v)


def is_arc_end(v):
    """Last point of a circle arc where a straight edge begins: turns like an
    arc point, but only one boundary neighbour is on the arc. Left free, the
    straight edge bows (3648 cross-axle hole: 0.081). Pinned when ARC_END."""
    t = turn(v)
    if t is None or is_round(v) or is_sharp(v) or not (config.ROUND_TURN[0] < t < config.ROUND_TURN[1]):
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
    if math.sqrt(sum(d * d for d in diag)) > config.LOGO_MAX_SIZE:
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
        if not (config.LOGO_HEIGHT[0] < hmax - hmin < config.LOGO_HEIGHT[1]):
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
        real = [f for f in comp if f.calc_area() > config.DEGENERATE_AREA] or comp
        n0 = max(real, key=lambda f: f.calc_area()).normal
        flat = all(math.degrees(n0.angle(f.normal, 0.0)) <= config.FLAT_MAX_ANGLE for f in real)
        verts = {v for f in comp for v in f.verts}
        roundb = any(is_round(v) for v in verts if v.is_boundary)
        out.append(("flat-round" if flat and roundb else "flat" if flat else "curved", comp, None))
    return out


def merge_logo_slits(me):
    bm = bmesh.new(); bm.from_mesh(me)
    logo_verts = {v for kind, comp, _ in classify(bm) if kind == "logo" for f in comp for v in f.verts}
    n = len(bm.verts)
    if logo_verts:
        bmesh.ops.remove_doubles(bm, verts=list(logo_verts), dist=config.MERGE_DIST)
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
            le = {e for e in edges if (a := dihedral(e)) is not None and a > config.LOGO_CREASE_ANGLE}
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
                if v.is_boundary and (is_sharp(v) or (config.ARC_END and is_arc_end(v))):
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
                bad = set(checks.escalate_faces.get(key, set()))
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
                                    config.PARTIAL[e.index] = max(config.PARTIAL.get(e.index, 0.0), config.FAN_CREASE)
                        else:
                            for e in f.edges:
                                if not e.is_boundary:
                                    config.PARTIAL[e.index] = max(config.PARTIAL.get(e.index, 0.0), config.REPAIR_CREASE)
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
            w = max((config.PARTIAL.get(e.index, 0.0) for v in g for e in inner(v)), default=0.0)
            if w <= 0.0:
                continue
            carriers = [v for v in g if any(config.PARTIAL.get(e.index, 0.0) > 0 for e in inner(v))]
            multi = [v for v in g if len(inner(v)) != 1]
            if len(multi) <= 1 and all(v in carriers for v in multi):
                for v in g:
                    if len(inner(v)) == 1:
                        e = inner(v)[0]
                        if config.PARTIAL.get(e.index, 0.0) != w and e.index not in E:
                            config.PARTIAL[e.index] = w; changed = True
            else:
                for v in g:
                    V.add(v.index); added += 1
                changed = True
    return added + len(added_slit)


def write_creases(me, E, V):
    ea = me.attributes.get("crease_edge") or me.attributes.new("crease_edge", 'FLOAT', 'EDGE')
    ea.data.foreach_set("value", [1.0 if i in E else config.PARTIAL.get(i, 0.0) for i in range(len(me.edges))])
    va = me.attributes.get("crease_vert") or me.attributes.new("crease_vert", 'FLOAT', 'POINT')
    va.data.foreach_set("value", [1.0 if i in V else 0.0 for i in range(len(me.vertices))])


def add_subsurf(ob):
    mod = ob.modifiers.get("Subdivision") or ob.modifiers.new("Subdivision", 'SUBSURF')
    mod.subdivision_type = 'CATMULL_CLARK'
    mod.levels = config.LEVELS
    mod.render_levels = config.LEVELS
    mod.use_creases = True
    mod.boundary_smooth = 'ALL'            # corners pinned by vertex crease instead (M1b, run 42)
    mod.use_limit_surface = True
    mod.use_custom_normals = config.SHADING == "mecabricks"
    # W14 (run 58): UVs smoothed with the island boundaries kept (Blender's default). The
    # subdivision also moves vertices within a plane; smoothed UVs move along, so prints keep
    # their shape. Linear UVs ('NONE') or UVs projected from the original distorted the
    # lettering of 86209. The wavy print lines of 86209 came from the spreading bevel (W13).
    mod.uv_smooth = welding.UV_SMOOTH
    return mod


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
    starts = checks.sub_offsets(me)

    def trial(w):
        config.PARTIAL.clear()
        E, V, _ = rule_creases(bm, {})
        if w > 0:
            for t, diags, comp in fans:
                for e in diags:
                    config.PARTIAL[e.index] = w
        unify_seams(bm, E, V)
        write_creases(me, E, V); me.update()
        dg = copies.depsgraph_of(ob); oe = ob.evaluated_get(dg); ev = oe.to_mesh()
        bad = checks.flipped_faces(ob, ev)
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
