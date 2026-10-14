"""Large meshes in batches of islands (UPDATES #54, run 287). The memory of a bake grows with the mesh: the 48 x 48
baseplate 4186 needs about 58 GB as Mecabricks made it and 91 GB with the importer's Clean Stud Bases. The
subdivision never reaches across an island, and the welded copies of a baseplate are thousands of small islands
(3857: 2,561, the largest 1,129 of 1.73 M vertices). So a large mesh is welded once to find its islands, then every
batch of islands goes through the whole chain of rules as a mesh of its own (welding._bake_weld, unchanged), and the
copies of the batches are joined in the face order of a direct bake. Three values the rules take from the whole mesh
are kept for every batch: the bake quality (copies.bake_quality, by the face count), the flat share (welding, W15) and
the part size (reparam, MIN_SLIDE). Everything else is decided per island (shrink.py, welding._bake_weld, reparam).

Islands of one shape are baked once (maintainer: "Eine Grundplatte ist ein modulares, symmetrisches Objekt."): an
island equal to an earlier one up to where it lies - corners, positions relative to its first point, every attribute
the rules read - takes that one's copy, moved to its place; the face attributes the rules do not read (the importer's
stud numbers) stay its own. The 48 x 48 baseplate has 11,521 islands of 6 shapes (run 287). An island joined to
another through a T vertex, or whose copy has faces of its own (W18) or T points, is baked as it is.

The memory is that of the largest batch plus the joined copies. bake_steps reports its progress (fraction, text)."""
from collections import defaultdict

import bpy
import numpy as np

from . import bevel, checks, config, copies, maps, meshparts, reparam, welding

BATCH_FACES = int(config.opt("--batch-faces", "40000"))     # faces of the import per batch; 0: never in batches
SHARE = config.opt("--share-shapes", "1") == "1"            # islands of one shape baked once
ACTIVE = [False]               # a batch is being baked: no batches inside a batch
BEVEL_COUNTS = ("rb_bevel_normals", "rb_bevel_support", "rb_bevel_plain", "rb_bevel_moved", "rb_bevel_back",
                "rb_bevel_flat")   # counts bevel.bevel_copy leaves on a copy: added over the batches
ISLAND, ISLAND_FACE = "rb_isl", "rb_isf"     # face attributes while batches are baked: the island, the face in it
GEOMETRIC_FACE = ("sharp_face", "material_index")   # face attributes the rules read; any other is carried per place


def wanted(orig):
    """Whether this mesh is baked in batches."""
    return not ACTIVE[0] and BATCH_FACES > 0 and len(orig.polygons) > BATCH_FACES


REACH = 3.0     # x config.MERGE_DIST: open points this close, or this close to an open edge, are one unit


def unit_plan(orig, arr):
    """The units of the import, as its faces (each sorted; the units in the order of their first face): its islands,
    joined where they touch - open points closer than REACH (a seam the weld closes, or points that only touch, which
    the weld pins on both sides) or an open point on the open edge of another island (a T vertex). The weld joins no
    more than that (welding: seams, `_t_vertices`, both within config.MERGE_DIST), so every unit is whole welded
    islands, and a batch of units welds as the whole mesh would - without welding the whole mesh first (the 48 x 48
    baseplate: 44 s, run 287). Also returns the flat share of the whole mesh (welding, stage 1)."""
    import types

    from mathutils import kdtree
    w = types.SimpleNamespace(orig=orig)
    welding._islands(w)
    flat = w.flat_share
    w.bm.free()
    co, ev, lv, le, lt = arr["co"], arr["ev"], arr["lv"], arr["le"], arr["lt"]
    open_e = np.nonzero(np.bincount(le, minlength=len(ev)) == 1)[0]
    open_v = np.unique(ev[open_e])
    links = []
    if len(open_v):
        reach = REACH * config.MERGE_DIST
        kd = kdtree.KDTree(len(open_v))
        for i, p in enumerate(co[open_v].tolist()):
            kd.insert(p, i)
        kd.balance()
        for i, p in enumerate(co[open_v].tolist()):            # touching open points
            for _c, j, _d in kd.find_range(p, reach):
                if j != i:
                    links.append((open_v[i], open_v[j]))
        a, b = co[ev[open_e, 0]].astype(np.float64), co[ev[open_e, 1]].astype(np.float64)
        ab = b - a
        length = np.linalg.norm(ab, axis=1)
        for e, m, half in zip(open_e.tolist(), ((a + b) / 2).tolist(), (length / 2 + reach).tolist(), strict=True):
            near = kd.find_range(m, half)                       # open points on this open edge (T vertices)
            if len(near) <= 2:
                continue
            j = np.array([x[1] for x in near], np.int64)
            p = co[open_v[j]].astype(np.float64)
            va, vb = ev[e]
            s = ((p - co[va]) * (co[vb] - co[va])).sum(axis=1) / max(float(((co[vb] - co[va]) ** 2).sum()), 1e-18)
            foot = co[va] + np.clip(s, 0.0, 1.0)[:, None] * (co[vb] - co[va])
            on = np.linalg.norm(p - foot, axis=1) < reach
            links += [(va, int(open_v[x])) for x in j[on]]
    lab = meshparts.point_islands(orig, links)
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    unit_of = lab[lv[ls]]
    order = np.argsort(unit_of, kind="stable")
    _keys, starts = np.unique(unit_of[order], return_index=True)
    units = sorted((np.sort(g) for g in np.split(order, starts[1:])), key=lambda g: int(g[0]))
    return units, flat


def shape_classes(arr, units, passive, cores=None):
    """{unit: the first unit of its shape} for every unit that is another one moved: the same faces with the same
    corners, the corners meeting their points in the same order, the positions relative to the first corner's point
    equal to 0.0001 mm, every attribute but the `passive` ones equal (floats to 1e-6). Compared group by group of units
    of the same size, as rows of one array each (11,521 units of the 48 x 48 baseplate in a second, run 287). With
    `cores` (per unit, its faces that are kept - a cell's core in its rings) those must lie the same way too."""
    co, lv, le, lt = arr["co"], arr["lv"], arr["le"], arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    size = {}
    for k, g in enumerate(units):
        size.setdefault((len(g), int(lt[g].sum())), []).append(k)
    shared = {}
    for ids in size.values():
        if len(ids) < 2:
            continue
        faces = np.stack([units[k] for k in ids])                     # (units, faces)
        lt2 = lt[faces]
        _rows, same_lt = np.unique(lt2, axis=0, return_inverse=True)
        for c in np.unique(same_lt):
            sel = np.nonzero(same_lt == c)[0]
            if len(sel) < 2:
                continue
            f2 = faces[sel]
            seq = lt2[sel[0]]
            offs = np.concatenate([np.arange(t) for t in seq])
            loops = np.repeat(ls[f2], seq, axis=1) + offs[None, :]     # (units, corners)
            v2 = lv[loops]
            # the order the corners meet their points: each corner names the first corner of its point
            order = np.argsort(v2, axis=1, kind="stable")
            sv = np.take_along_axis(v2, order, axis=1)
            start = np.ones(sv.shape, bool)
            start[:, 1:] = sv[:, 1:] != sv[:, :-1]
            col = np.maximum.accumulate(np.where(start, np.arange(sv.shape[1])[None, :], 0), axis=1)
            first = np.empty_like(order)
            np.put_along_axis(first, order, np.take_along_axis(order, col, axis=1), axis=1)
            rel = np.round((co[v2] - co[v2[:, :1]]).astype(np.float64) * 1e4).astype(np.int64)
            feats = [first, rel.reshape(len(sel), -1)]
            if cores is not None:
                feats.append(np.stack([np.isin(units[ids[x]], cores[ids[x]]) for x in sel]).astype(np.int64))
            pick = {'CORNER': loops, 'POINT': v2, 'EDGE': le[loops], 'FACE': f2}
            for name in sorted(arr["attrs"]):
                domain, _t, values = arr["attrs"][name]
                if name in passive or name.startswith("."):
                    continue
                v = values[pick[domain]]
                v = np.round(v.astype(np.float64) * 1e6).astype(np.int64) if v.dtype.kind == "f" else v.astype(np.int64)
                feats.append(v.reshape(len(sel), -1))
            _rows, cls = np.unique(np.concatenate(feats, axis=1), axis=0, return_inverse=True)
            cls = cls.ravel()
            rep = {}
            for k, c2 in zip((ids[x] for x in sel), cls.tolist(), strict=True):
                r = rep.setdefault(c2, k)
                if r != k:
                    shared[k] = r
    return shared


SHAPES_TRIED = 32                  # shapes of one count of faces a cell is compared with
TOL_PLACE, TOL_UV = 5e-4, 1e-5     # cells of one shape: places in mm (the importer places the knobs through float
                                   # matrices, 0.00013 mm apart, run 287), UVs after their own shift


def cell_classes(arr, cores, fulls, corners, ids, passive):
    """{cell: (the cell of its shape that is baked, its core faces in the order of that one's core, how far it lies
    from that one, per UV map the shift of the UVs of each face of that one's core)} for cells equal to an earlier one
    moved by whole cells. Each face is matched to the face of the other cell at its place (its centre relative to the
    cell's corner, within TOL_PLACE): the import's numbering does not repeat from cell to cell, and an order of rounded
    centres split equal cells at its steps (run 287). Then their corners' places, the other attributes the rules read
    and the UVs must be equal - the UVs up to a shift of each UV island of its own (a plate's top is mapped across the
    plate, its studs each alike, run 287): the subdivision smooths UVs within an island, a shift of the whole island
    moves its result alike. A cell that differs anywhere is baked itself."""
    from mathutils.kdtree import KDTree
    co, lv, le, lt = arr["co"], arr["lv"], arr["le"], arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    names = [n for n in sorted(arr["attrs"]) if n not in passive and not n.startswith(".")]
    uvs = {n for n in names if arr["attrs"][n][0] == 'CORNER' and arr["attrs"][n][1] == 'FLOAT2'}
    groups, out = defaultdict(list), {}

    def centres(f, corner):
        sizes = lt[f]
        starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
        pts = co[lv[meshparts.face_loops(ls, lt, f)]].astype(np.float64) - corner
        return np.add.reduceat(pts, starts) / sizes[:, None]

    def described(f, corner, islands=False):
        lc = meshparts.face_loops(ls, lt, f)
        data = {"place": co[lv[lc]].astype(np.float64) - corner}
        pick = {'CORNER': lc, 'POINT': lv[lc], 'EDGE': le[lc], 'FACE': f}
        for n in names:
            data[n] = arr["attrs"][n][2][pick[arr["attrs"][n][0]]]
            if n in uvs:
                data[n] = data[n].astype(np.float64)
                if islands:
                    data["island " + n] = _uv_islands(lv[lc], data[n], lt[f])
        return data
    for i in ids:
        f = fulls[i]
        key = (len(f), len(cores[i]), np.bincount(lt[f]).tobytes())
        cen = centres(f, corners[i])
        found = None
        for r, fr, tree, dr in groups[key][-SHAPES_TRIED:]:   # the latest few: cells that differ stay quick
            at = np.array([tree.find(c)[1:] for c in cen.tolist()], dtype=np.float64)
            if at[:, 1].max() > TOL_PLACE or len(np.unique(at[:, 0])) != len(f):
                continue
            fc = np.empty_like(f)
            fc[at[:, 0].astype(np.int64)] = f          # this cell's faces in the order of the other's
            if not np.array_equal(lt[fc], lt[fr]) or not np.array_equal(np.isin(fc, cores[i]), np.isin(fr, cores[r])):
                continue
            data = described(fc, corners[i])
            if np.abs(data["place"] - dr["place"]).max() > TOL_PLACE:
                continue
            same, shifts = True, {}
            first = np.concatenate(([0], np.cumsum(lt[fr])[:-1]))
            for n in names:
                a, b = data[n], dr[n]
                if n in uvs:                            # each island's shift: that of its first face's first corner
                    isl = dr["island " + n]
                    _u, lead, back = np.unique(isl, return_index=True, return_inverse=True)
                    face_shift = (a - b)[first][lead][back.ravel()]
                    same = np.abs(a - b - np.repeat(face_shift, lt[fr], axis=0)).max() <= TOL_UV
                    shifts[n] = face_shift
                else:
                    same = (np.abs(a.astype(np.float64) - b).max() <= 1e-6 if a.dtype.kind == "f"
                            else np.array_equal(a, b))
                if not same:
                    break
            if same:
                found = (r, fr, fc, shifts)
                break
        if found is None:
            tree = KDTree(len(f))
            for j, c in enumerate(cen.tolist()):
                tree.insert(c, j)
            tree.balance()
            groups[key].append((i, f, tree, described(f, corners[i], islands=True)))
            continue
        r, fr, fc, shifts = found
        mine = dict(zip(fr.tolist(), fc.tolist(), strict=True))
        at_r = {x: j for j, x in enumerate(fr.tolist())}
        core_at = np.array([at_r[x] for x in cores[r].tolist()], np.int64)     # the core's faces among the cell's
        out[i] = (r, np.array([mine[x] for x in cores[r].tolist()], np.int64), corners[i] - corners[r],
                  {n: sh[core_at] for n, sh in shifts.items()})
    return out


def _uv_islands(points, uv, sizes):
    """Per face (corners `points` and `uv` face after face, `sizes` corners each) its UV island: faces joined where
    they share a point with the same UV."""
    face = np.repeat(np.arange(len(sizes)), sizes)
    parent = list(range(len(sizes)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    key = np.column_stack((points, np.round(uv * 1e6).astype(np.int64)))
    _u, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    o = np.argsort(inv, kind="stable")
    for grp in np.split(face[o], np.nonzero(np.diff(inv[o]))[0] + 1):
        for b in grp[1:].tolist():
            ra, rb = find(int(grp[0])), find(b)
            if ra != rb:
                parent[rb] = ra
    return np.array([find(a) for a in range(len(sizes))], np.int64)


def grid_origin(arr, unit):
    """The corner of the CELL grid for a unit: per axis in the middle of the widest gap between its faces' centres
    (modulo CELL), so that no face lies on a border by a hair - a face whose centre sits on it falls into one cell or
    the next by rounding, and equal cells come out unequal. On a plate cut by the importer's cells of the studs' grid
    the borders land on those cells' borders (its corner is 0.04 mm off the grid: the edge of a LEGO part is inset)."""
    co, lv, lt = arr["co"], arr["lv"], arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    sizes = lt[unit]
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    cen = np.add.reduceat(co[lv[meshparts.face_loops(ls, lt, unit)]].astype(np.float64), starts) / sizes[:, None]
    low = cen.min(axis=0)
    origin = np.empty(3)
    for k in range(3):
        m = np.sort(np.mod(cen[:, k] - low[k], CELL))
        gaps = np.diff(np.concatenate((m, [m[0] + CELL])))
        j = int(np.argmax(gaps))
        origin[k] = low[k] + m[j] + gaps[j] / 2 - CELL
    return origin


CELL = 8.0      # mm: the cells a unit too large for a batch is cut into - the LEGO module (grid_origin)
CELL_FACES = int(config.opt("--cell-faces", "100000"))   # a unit above this is baked in cells (about 9 GB at the
                                                          # large parts' quality) - smaller ones whole, in a batch
HALO = 3        # rings of faces around a cell's core that are baked with it and left out of the copy


def cells(arr, unit, origin):
    """A unit too large for one batch in the cells of a CELL grid from `origin` (grid_origin: the studs of a plate
    stand at 4 + 8 k mm from its edge, one in each cell): [(core, faces, corner)] - the core the faces whose
    centre lies in the cell, `faces` the core and HALO rings of faces around it (joined over shared points, the faces of
    the unit within the cells around the core's box), `corner` the cell's corner of the grid. The subdivision of a face
    reaches its neighbours, the rules of the weld a few rings: baked with the rings, the core comes out as in the whole
    unit; the rings' copies are left out (run 287: the 48 x 48 baseplate with the importer's Studs for Random Walk welds
    into one island of 1,007,324 faces). The last resort for a unit that would not fit (CELL_FACES): rules that judge a
    whole island of the import (flat or curved, rings round a hole, whole cylinders) see it cut off in the rings - on an
    ordinary part that moved points by 0.3 mm (25972, run 287); on a plate a cell holds its stud, its logo and its piece
    of the top whole."""
    co, lv, lt = arr["co"], arr["lv"], arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    sizes = lt[unit]
    loops = meshparts.face_loops(ls, lt, unit)
    starts = np.concatenate(([0], np.cumsum(sizes)[:-1]))
    pts = co[lv[loops]].astype(np.float64)
    cen = np.add.reduceat(pts, starts) / sizes[:, None]
    lo_c = np.floor((np.minimum.reduceat(pts, starts) - origin) / CELL).astype(np.int64)
    hi_c = np.floor((np.maximum.reduceat(pts, starts) - origin) / CELL).astype(np.int64)
    key = np.floor((cen - origin) / CELL).astype(np.int64)
    base = np.minimum(lo_c.min(axis=0), key.min(axis=0)) - 1
    dims = np.maximum(hi_c.max(axis=0), key.max(axis=0)) - base + 2

    def code(c):
        c = c - base
        return (c[..., 0] * dims[1] + c[..., 1]) * dims[2] + c[..., 2]
    # every face in each cell its box touches (most faces lie in one cell)
    one = np.all(lo_c == hi_c, axis=1)
    reg_cell, reg_face = [code(lo_c[one])], [np.nonzero(one)[0]]
    for f in np.nonzero(~one)[0].tolist():
        rng = [np.arange(lo_c[f, k], hi_c[f, k] + 1) for k in range(3)]
        g = np.stack(np.meshgrid(*rng, indexing="ij"), axis=-1).reshape(-1, 3)
        reg_cell.append(code(g))
        reg_face.append(np.full(len(g), f))
    reg_cell, reg_face = np.concatenate(reg_cell), np.concatenate(reg_face)
    o = np.argsort(reg_cell, kind="stable")
    rk, rs = np.unique(reg_cell[o], return_index=True)
    in_cell = dict(zip(rk.tolist(), np.split(reg_face[o], rs[1:]), strict=True))
    # the corners of the unit's faces, local
    vert = lv[loops]
    out = []
    ck = code(key)
    o = np.argsort(ck, kind="stable")
    _kk, ks = np.unique(ck[o], return_index=True)
    for core in np.split(o, ks[1:]):
        corner = origin + key[core[0]] * CELL
        c_lo, c_hi = lo_c[core].min(axis=0) - 1, hi_c[core].max(axis=0) + 1
        rng = [np.arange(c_lo[k], c_hi[k] + 1) for k in range(3)]
        g = code(np.stack(np.meshgrid(*rng, indexing="ij"), axis=-1).reshape(-1, 3))
        cand = np.unique(np.concatenate([in_cell[c] for c in g.tolist() if c in in_cell] + [core]))
        cl = meshparts.face_loops(starts, sizes, cand)          # corners of the candidates (local to the unit)
        cv = vert[cl]
        cs = np.concatenate(([0], np.cumsum(sizes[cand])[:-1]))
        take = np.isin(cand, core)
        for _ring in range(HALO):
            marked = np.unique(cv[np.repeat(take, sizes[cand])])
            take = np.logical_or.reduceat(np.isin(cv, marked), cs)
        out.append((np.sort(unit[core]), np.sort(unit[cand[take]]), corner))
    return out


def pack(islands, ids):
    """The islands `ids` in batches of up to BATCH_FACES faces, in the order of their first face (cells too: baked
    each alone, a cell of a plate came out further from the direct bake - 0.031 mm against 0.0065 at 99.9 %,
    run 287)."""
    out, cur, size = [], [], 0
    for i in ids:
        if cur and size + len(islands[i]) > BATCH_FACES:
            out.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(islands[i])
    if cur:
        out.append(cur)
    return out


def bake(orig, levels):
    """The copies of `orig` for `levels` and the report, as welding._bake_weld gives them - baked batch by batch."""
    gen = bake_steps(orig, levels)
    while True:
        try:
            next(gen)
        except StopIteration as e:
            return e.value


def bake_steps(orig, levels):
    """bake as a step generator: yields (fraction, text) after each batch; returns (copies, report)."""
    yield 0.0, "finding the pieces"
    arr = meshparts.mesh_arrays(orig)
    units, flat = unit_plan(orig, arr)
    # the pieces: each unit, or the cells of a unit too large for a batch (with rings of faces around their cores)
    islands, fulls, corners = [], [], []            # per piece: its core (kept), its faces (baked), a cell's corner
    for u in units:
        for core, faces, corner in (cells(arr, u, grid_origin(arr, u)) if len(u) > CELL_FACES else [(u, u, None)]):
            islands.append(core)
            fulls.append(faces)
            corners.append(corner)
    n = len(orig.polygons)
    face_island = np.full(n, -1, np.int64)
    face_in_island = np.full(n, -1, np.int64)
    for k, g in enumerate(islands):
        face_island[g], face_in_island[g] = k, np.arange(len(g))
    passive = {name for name, (d, _t, _v) in arr["attrs"].items()
               if d == 'FACE' and name not in GEOMETRIC_FACE and not name.startswith(".")}
    # piece -> (the piece of its shape that is baked, its core in the order of that one's, its offset, UV shifts)
    moves = {}
    if SHARE:
        whole = [i for i, c in enumerate(corners) if c is None]
        ls = np.concatenate(([0], np.cumsum(arr["lt"])[:-1]))
        first = arr["co"][arr["lv"][ls[[islands[i][0] for i in whole]]]].astype(np.float64) if whole else None
        at = {i: x for x, i in enumerate(whole)}
        for k, r in shape_classes(arr, [fulls[i] for i in whole], passive).items():
            moves[whole[k]] = (whole[r], islands[whole[k]], first[at[whole[k]]] - first[at[whole[r]]], {})
        moves.update(cell_classes(arr, islands, fulls, corners, [i for i, c in enumerate(corners) if c is not None],
                                  passive))
    shared = {k: m[0] for k, m in moves.items()}
    quality = copies.bake_quality(orig)
    _guard(orig, levels, fulls, [i for i in range(len(islands)) if i not in shared], quality)
    yield 0.02, f"{len(islands):,} pieces of {len(islands) - len(shared):,} shapes"
    ACTIVE[0] = True
    copies.QUALITY_PIN[0], welding.FLAT_SHARE_PIN[0], reparam.SIZE_PIN[0] = quality, flat, reparam.part_size(orig)
    parts, reports = [], []
    try:
        todo = pack(fulls, [i for i in range(len(islands)) if i not in shared])
        done = 0
        while todo:
            for j, ids in enumerate(todo):
                faces = np.unique(np.concatenate([fulls[i] for i in ids]))
                sub_arr, *_ = meshparts.select_arrays(arr, faces)
                # the piece each face is the core of, if that piece is in this batch (-1: only a ring here)
                mine = np.isin(face_island[faces], ids)
                isl = np.where(mine, face_island[faces], -1)
                isf = np.where(mine, face_in_island[faces], -1)
                sub_arr["attrs"][ISLAND] = ('FACE', 'INT', isl[:, None].astype(np.int32))
                sub_arr["attrs"][ISLAND_FACE] = ('FACE', 'INT', isf[:, None].astype(np.int32))
                sub = meshparts.build_arrays(sub_arr, f"{orig.name}~{len(parts)}", orig)
                made, rep = welding._bake_weld(sub, levels)
                parts.append((faces, sub, made))
                reports.append(rep)
                done += 1
                total = done + len(todo) - j - 1
                yield 0.02 + 0.88 * done / total, f"piece {done} of {total}"
            # a shape whose copy cannot just be moved: its islands are baked as they are, in another round
            fixed = _fixed_shapes(parts, islands, face_island, set(shared.values()))
            back = sorted(k for k, rep in shared.items() if rep in fixed)
            for k in back:
                del shared[k], moves[k]
            todo = pack(fulls, back)
    finally:
        ACTIVE[0] = False
        copies.QUALITY_PIN[0] = welding.FLAT_SHARE_PIN[0] = reparam.SIZE_PIN[0] = None
    made = {}
    try:
        for step, lv in enumerate(sorted(levels, reverse=True)):
            yield 0.9 + 0.1 * step / len(levels), f"joining the copies of level {lv}"
            made[lv] = join_copies(orig, arr, islands, moves, [(f, s, m[lv]) for f, s, m in parts], lv, passive)
            for _f, sub, m in parts:                # that level's batch copies are not needed any more
                copies.discard_copy(sub, m.pop(lv))
    finally:
        for _f, sub, m in parts:
            for cp in m.values():
                copies.discard_copy(sub, cp)
            bpy.data.meshes.remove(sub)
    rep = merge_reports(reports)
    rep["batches"] = len(parts)
    rep["batch_faces_max"] = max(len(f) for f, _s, _m in parts)
    rep["islands"], rep["islands_shared"] = len(islands), len(shared)
    return made, rep


def _guard(orig, levels, islands, ids, quality):
    """The memory guard counted on batches of BATCH_FACES; one island can be larger (run 287: 4186 with the importer's
    Clean Stud Bases welds into one island of most of the plate - the run crashed at 56 GB): the largest batch is
    checked against the free memory now, so that Apply stops cleanly instead (memory.check_memory, run 49)."""
    largest = max((sum(len(islands[i]) for i in b) for b in pack(islands, ids)), default=0)
    if largest <= BATCH_FACES:
        return
    from . import memory
    level = max(levels)
    need = largest * memory.GB_PER_FACE.get(quality, 0.2e-3) * 1.05 * 4 ** max(0, level - 2) \
        + len(orig.polygons) * memory.GB_PER_FACE_KEPT * 4 ** max(0, level - 2) + memory.GB_MARGIN
    free = memory.free_memory_gb()
    if free is not None and need > free:
        raise memory.MemoryShortage(
            f"not enough free memory for {orig.name} ({len(orig.polygons):,} faces, one piece of {largest:,} faces "
            f"that cannot be split): needs about {need:.0f} GB, {free:.0f} GB free - close other programs and apply again")


def _fixed_shapes(parts, islands, face_island, reps):
    """The baked islands of `reps` whose copy cannot be moved to another place as it is: faces of its own beyond the
    import's (W18, checks.LAYOUT) or T points (rb_tv) - those name faces of its batch."""
    out = set()
    for faces, _sub, made in parts:
        for cp in made.values():
            lay = list(cp.get(checks.LAYOUT) or [])
            if lay:
                pairs = np.array(lay[1:], np.int64).reshape(-1, 2)
                out |= {int(face_island[faces[f]]) for f in pairs[:, 0] if f < len(faces)}
            flat = list(cp.get("rb_tv", []))
            out |= {int(face_island[faces[h]]) for h in flat[1::2] if h < len(faces)}
    return out & reps


def join_copies(orig, arr, islands, moves, parts, level, passive):
    """One copy of `orig` from the copies of its batches [(faces of the import, batch mesh, its copy)] and the moved
    copies of the shared islands: the children of every face of the import in the order of the import, the faces a
    cage has beyond the import's (W18) at the end, batch by batch - as checks.cage_faces reads a copy. A bevelled copy
    is no longer in blocks: joined as it comes."""
    n = len(orig.polygons)
    blocks, lay_pairs, extra_pairs, tvs, folds, gaps, pieces = [], [], [], [], [], [], []
    offset, extra_no = 0, 0
    bevelled = bevel.is_bevelled(parts[0][2])
    by_rep = {}
    for k, move in moves.items():
        by_rep.setdefault(move[0], []).append(k)
    for faces, sub, cp in parts:
        nk = len(faces)
        full = meshparts.mesh_arrays(cp)
        core = meshparts.attribute_values(sub, ISLAND)[:, 0] >= 0        # per batch face: a core here (not a ring)
        lay = list(cp.get(checks.LAYOUT) or [])
        k_lay = int(lay[0]) if lay else 0
        pairs = np.array(lay[1:], np.int64).reshape(-1, 2) if lay else np.zeros((0, 2), np.int64)
        extra_core = core[pairs[k_lay:, 0]] if len(pairs) else np.zeros(0, bool)    # W18 faces: their face's
        new_extra = np.full(len(extra_core), -1, np.int64)
        new_extra[extra_core] = extra_no + np.arange(int(extra_core.sum()))
        # only the children of the cores: the rings were baked for them and are left out
        a, verts, _e, _f = meshparts.select_arrays(full, np.nonzero(full["attrs"][ISLAND][2][:, 0] >= 0)[0])
        if not bevelled:
            sizes, _owner = checks.cage_faces(sub, cp)
            kept = np.concatenate([core, extra_core])
            count = (sizes * 4 ** (level - 1))[kept]
            starts = offset + np.concatenate(([0], np.cumsum(count)[:-1]))
            idx = np.nonzero(kept)[0]
            keys = faces[np.minimum(idx, nk - 1)].copy()
            extra = idx >= nk
            keys[extra] = n + new_extra[idx[extra] - nk]
            blocks += list(zip(keys.tolist(), starts.tolist(), count.tolist()))
        lay_pairs += [(int(faces[f]), int(c)) for f, c in pairs[:k_lay] if core[f]]
        extra_pairs += [(int(faces[f]), int(c)) for f, c in pairs[k_lay:] if core[f]]
        flat = list(cp.get("rb_tv", []))
        tv = []
        for v, host in zip(flat[0::2], flat[1::2], strict=True):
            j = int(np.searchsorted(verts, v))
            if j < len(verts) and verts[j] == v and (core[host] if host < nk else new_extra[host - nk] >= 0):
                tv += [j, int(faces[host]) if host < nk else n + int(new_extra[host - nk])]
        tvs.append(tv)
        if bevel.EDGE_FOLDS in cp:
            folds += [int(faces[int(x)]) for x in str(cp[bevel.EDGE_FOLDS]).split(",") if x and core[int(x)]]
        if bevel.EDGE_GAP in cp:
            gaps.append(float(cp[bevel.EDGE_GAP]))
        extra_no += int(extra_core.sum())
        offset += len(a["lt"])
        pieces.append(a)
        del full
        # the shared islands whose shape this batch baked: moved to their places
        isl = a["attrs"][ISLAND][2][:, 0]
        for rep in sorted(set(isl.tolist()) & set(by_rep)):
            piece, *_ = meshparts.select_arrays(a, np.nonzero(isl == rep)[0])
            # its core's blocks, in the order of its core: each copy names its own faces through the move's map
            count = arr["lt"][islands[rep]] * 4 ** (level - 1)
            for k in by_rep[rep]:
                faces_k = moves[k][1]                   # the copy's faces in the order of the baked piece's core
                m = _moved(arr, piece, moves[k], passive)
                if not bevelled:
                    starts = offset + np.concatenate(([0], np.cumsum(count)[:-1]))
                    blocks += list(zip(faces_k.tolist(), starts.tolist(), count.tolist(), strict=True))
                offset += len(m["lt"])
                pieces.append(m)
                tvs.append([])
            if folds:                                   # a fold on the baked piece is on its copies too
                at = {f: j for j, f in enumerate(islands[rep].tolist())}
                hit = [at[f] for f in folds if f in at]
                for k in by_rep[rep]:
                    folds += [int(moves[k][1][j]) for j in hit]
    order = None
    if not bevelled:
        blocks.sort()
        order = np.concatenate([np.arange(s, s + c) for _k, s, c in blocks]) if blocks else None
    joined, voff = meshparts.join_arrays(pieces, f"{orig.name} L{level}", parts[0][2], face_order=order,
                                         drop=(ISLAND, ISLAND_FACE))
    del pieces
    # the properties: those of a batch copy, then what belongs to the whole mesh
    joined["rb_original"], joined["rb_src"] = orig.name, copies.source_hash(orig)
    if checks.LAYOUT in joined:
        del joined[checks.LAYOUT]
    if lay_pairs or extra_pairs:
        joined[checks.LAYOUT] = [len(lay_pairs)] + [x for p in lay_pairs + extra_pairs for x in p]
    flat_tv = []
    for tv, off in zip(tvs, voff, strict=True):           # (vertex of the piece, face of the import) - now joined
        for v, host in zip(tv[0::2], tv[1::2], strict=True):
            flat_tv += [int(off + v), host]
    joined["rb_tv"] = flat_tv
    if any(bevel.EDGE_FOLDS in cp for _f, _s, cp in parts):
        joined[bevel.EDGE_FOLDS] = ",".join(str(i) for i in sorted(set(folds)))
    if gaps:
        joined[bevel.EDGE_GAP] = max(gaps)
    for key in BEVEL_COUNTS:                        # what bevel_copy counted, over all batches (a batch without a
        if any(key in cp for _f, _s, cp in parts):  # chosen edge has no counts; the moved copies are not counted)
            joined[key] = sum(int(cp.get(key, 0)) for _f, _s, cp in parts)
    if any(bevel.EDGE_ATTR in cp for _f, _s, cp in parts):
        joined[bevel.EDGE_ATTR] = next(cp[bevel.EDGE_ATTR] for _f, _s, cp in parts if bevel.EDGE_ATTR in cp)
    if any(cp.get(maps.MARK) for _f, _s, cp in parts):
        # the mark of the EEVEE bevel map is the number of the copy's shape (rb_src): a batch marked its own shape,
        # the joined copy is the whole import's (the material's switch compares the two)
        maps.mark_copy(joined, orig)
    joined.use_fake_user = True
    if copies._COPY_INDEX[0] is not None:
        copies._COPY_INDEX[0].setdefault(orig.name, []).append(joined)
    return joined


def _moved(arr, piece, move, passive):
    """The copy `piece` of a baked piece at the place of another of its shape - `move` = (that piece, the other's core
    faces in the order of its core, the offset, per UV map the shift of each core face): moved, UVs shifted, the passive
    face attributes (the importer's stud numbers) its own, through the face each child comes from."""
    _rep, faces, offset, uv_shift = move
    isf = piece["attrs"][ISLAND_FACE][2][:, 0]
    m = dict(piece)
    m["co"] = (piece["co"].astype(np.float64) + offset).astype(np.float32)
    m["attrs"] = dict(piece["attrs"])
    for name in passive:
        d, t, values = arr["attrs"][name]
        if name in m["attrs"]:
            m["attrs"][name] = (d, t, values[faces[isf]])
    for name, shift in uv_shift.items():                # per face of the baked core: its children's corners
        if name in m["attrs"] and np.any(shift != 0):
            d, t, values = m["attrs"][name]
            m["attrs"][name] = (d, t, (values.astype(np.float64) + np.repeat(shift[isf], piece["lt"], axis=0))
                                .astype(np.float32))
    return m


def merge_reports(reports):
    """One report of the batches': counts added, measures (floats) as their largest value."""
    out = {}
    for rep in reports:
        for k, v in rep.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                out.setdefault(k, v)
            elif isinstance(v, int):
                out[k] = out.get(k, 0) + v
            else:
                out[k] = max(out.get(k, v), v)
    return out
