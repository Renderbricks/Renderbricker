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

from . import batchpool, bevel, checks, config, copies, maps, meshparts, reparam, welding

BATCH_FACES = int(config.opt("--batch-faces", "40000"))     # faces of the import per batch; 0: never in batches
SHARE = config.opt("--share-shapes", "1") == "1"            # islands of one shape baked once
PARALLEL = config.opt("--parallel-batches", "1") == "1"      # the batches of a mesh in background Blenders (batchpool)
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
        p = co[open_v].astype(np.float64)
        i, j = _pairs_within(p, reach)                         # touching open points
        links.append(np.column_stack((open_v[i], open_v[j])))
        e, j = _points_on_segments(co[ev[open_e, 0]].astype(np.float64), co[ev[open_e, 1]].astype(np.float64), p,
                                   reach)                      # open points on an open edge (T vertices)
        links.append(np.column_stack((ev[open_e[e], 0], open_v[j])))
    links = np.concatenate(links).tolist() if links else []
    lab = meshparts.point_islands(orig, links)
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    unit_of = lab[lv[ls]]
    order = np.argsort(unit_of, kind="stable")
    _keys, starts = np.unique(unit_of[order], return_index=True)
    units = sorted((np.sort(g) for g in np.split(order, starts[1:])), key=lambda g: int(g[0]))
    return units, flat


def _cell_codes(cells):
    """One int64 per integer grid cell (n, 3)."""
    c = cells.astype(np.int64) + (1 << 20)
    return (c[:, 0] << 42) | (c[:, 1] << 21) | c[:, 2]


def _join(keys_a, keys_b):
    """All index pairs (i, j) with keys_a[i] == keys_b[j] (both sorted first: searchsorted with unsorted queries
    is several times slower)."""
    o = np.argsort(keys_b, kind="stable")
    sb = keys_b[o]
    oa = np.argsort(keys_a, kind="stable")
    sa = keys_a[oa]
    lo, hi = np.searchsorted(sb, sa, "left"), np.searchsorted(sb, sa, "right")
    n = hi - lo
    i = oa[np.repeat(np.arange(len(keys_a)), n)]
    first = np.repeat(lo - np.concatenate(([0], np.cumsum(n)[:-1])), n)
    return i, o[np.arange(len(i)) + first]


def _pairs_within(p, reach):
    """The pairs (i, j) of points `p` closer than `reach`, each pair once - a grid of cells of `reach`, sorted once,
    and per point its own cell and the 13 neighbours ahead of it (replaces a KD tree queried point by point: 1.6 M
    Python calls on the cut 4186, run 287)."""
    code = _cell_codes(np.floor(p / reach).astype(np.int64))
    o = np.argsort(code, kind="stable")
    sc = code[o]
    out_i, out_j = [], []
    for d in np.stack(np.meshgrid(*[np.arange(-1, 2)] * 3, indexing="ij"), axis=-1).reshape(-1, 3):
        if tuple(d) < (0, 0, 0):
            continue                                # the pair is found from the other point
        # the code is linear in the cell: a neighbour's is one's own plus a constant, so the queries stay sorted
        # (unsorted, searchsorted took 0.4 s a call for a million points)
        q = sc + int(_cell_codes(d[None, :])[0] - _cell_codes(np.zeros((1, 3), np.int64))[0])
        lo, hi = np.searchsorted(sc, q, "left"), np.searchsorted(sc, q, "right")
        n = hi - lo
        i = o[np.repeat(np.arange(len(p)), n)]
        j = o[np.arange(int(n.sum())) + np.repeat(lo - np.concatenate(([0], np.cumsum(n)[:-1])), n)]
        keep = (i < j) if not d.any() else np.ones(len(i), bool)
        keep &= np.einsum("ij,ij->i", p[i] - p[j], p[i] - p[j]) <= reach * reach
        out_i.append(i[keep])
        out_j.append(j[keep])
    return np.concatenate(out_i), np.concatenate(out_j)


def _points_on_segments(a, b, p, reach):
    """All pairs (segment, point) with the point within `reach` of the segment a-b (its ends included) - each
    segment's box, widened by `reach`, in the cells of a grid as large as the median segment; the points of those
    cells tested at once (replaces a KD query and a numpy call per open edge, run 287)."""
    size = max(float(np.median(np.linalg.norm(b - a, axis=1))), 8 * reach)
    lo = np.floor((np.minimum(a, b) - reach) / size).astype(np.int64)
    hi = np.floor((np.maximum(a, b) + reach) / size).astype(np.int64)
    span = hi - lo + 1
    count = span.prod(axis=1)
    seg = np.repeat(np.arange(len(a)), count)
    k = np.arange(len(seg)) - np.repeat(np.concatenate(([0], np.cumsum(count)[:-1])), count)
    sp = span[seg]
    cell = lo[seg] + np.column_stack((k // (sp[:, 1] * sp[:, 2]), (k // sp[:, 2]) % sp[:, 1], k % sp[:, 2]))
    s_i, p_j = _join(_cell_codes(cell), _cell_codes(np.floor(p / size).astype(np.int64)))
    s_i = seg[s_i]
    ab = b[s_i] - a[s_i]
    t = np.clip(np.einsum("ij,ij->i", p[p_j] - a[s_i], ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    on = np.linalg.norm(p[p_j] - (a[s_i] + t[:, None] * ab), axis=1) < reach
    pairs = np.unique(np.column_stack((s_i[on], p_j[on])), axis=0)
    return pairs[:, 0], pairs[:, 1]


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
                                   # matrices, 0.00013 mm apart, run 287), UVs after their island's own mapping


def cell_classes(arr, cores, fulls, corners, ids, passive):
    """{cell: (the cell of its shape that is baked, its core faces in the order of that one's core, how far it lies
    from that one, per UV map the affine map of the UVs of each face of that one's core, (3, 2): uv @ m[:2] + m[2])}
    for cells equal to an earlier one moved by whole cells. Each face is matched to the face of the other cell at its
    place (its centre relative to the cell's corner, within TOL_PLACE): the import's numbering does not repeat from
    cell to cell, and an order of rounded centres split equal cells at its steps (run 287). Then their corners'
    places, the other attributes the rules read and the UVs must be equal - the UVs up to an affine map of each UV
    island of its own (shifted, turned, mirrored: a plate's top is mapped across the plate and each quadrant its own
    way, its studs alike; with the UVs compared as they are, the 2,312 cells of the 48 x 48 baseplate were 395
    shapes, without them 86, run 287). The subdivision and the slide make every UV of a child an affine combination of
    the UVs of its island (weights summing to 1, set by the places and the island's seams alone), so an affine map of
    the whole island maps the result alike. A cell that differs anywhere is baked itself."""
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
                if islands:                     # per island: its corners and the pseudo-inverse of [uv, 1]
                    isl = np.repeat(_uv_islands(lv[lc], data[n], lt[f]), lt[f])
                    data["island " + n] = [(rows, np.linalg.pinv(np.column_stack((data[n][rows], np.ones(len(rows))))))
                                           for rows in _groups(isl)]
        return data
    for i in ids:
        f = fulls[i]
        key = (len(f), len(cores[i]), np.bincount(lt[f]).tobytes())
        cen = centres(f, corners[i])
        sig = np.concatenate((cen.mean(axis=0), cen.std(axis=0)))   # equal cells: equal within TOL_PLACE
        found = None
        for r, fr, tree, dr in groups[key][-SHAPES_TRIED:]:   # the latest few: cells that differ stay quick
            if np.abs(dr["sig"] - sig).max() > 2 * TOL_PLACE:
                continue
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
            same, fits = True, {}
            first = np.concatenate(([0], np.cumsum(lt[fr])[:-1]))
            for n in names:
                a, b = data[n], dr[n]
                if n in uvs:                            # each island's affine map, fitted to its corners
                    corner_map = np.empty((len(a), 3, 2))
                    for rows, pinv in dr["island " + n]:
                        m = pinv @ a[rows]
                        if np.abs(b[rows] @ m[:2] + m[2] - a[rows]).max() > TOL_UV:
                            same = False
                            break
                        corner_map[rows] = m
                    fits[n] = corner_map[first]         # per face: the map of its island
                else:
                    same = (np.abs(a.astype(np.float64) - b).max() <= 1e-6 if a.dtype.kind == "f"
                            else np.array_equal(a, b))
                if not same:
                    break
            if same:
                found = (r, fr, fc, fits)
                break
        if found is None:
            tree = KDTree(len(f))
            for j, c in enumerate(cen.tolist()):
                tree.insert(c, j)
            tree.balance()
            desc = described(f, corners[i], islands=True)
            desc["sig"] = sig
            groups[key].append((i, f, tree, desc))
            continue
        r, fr, fc, fits = found
        mine = dict(zip(fr.tolist(), fc.tolist(), strict=True))
        at_r = {x: j for j, x in enumerate(fr.tolist())}
        core_at = np.array([at_r[x] for x in cores[r].tolist()], np.int64)     # the core's faces among the cell's
        out[i] = (r, np.array([mine[x] for x in cores[r].tolist()], np.int64), corners[i] - corners[r],
                  {n: fit[core_at] for n, fit in fits.items()})
    return out


def _groups(labels):
    """The indices of each label's elements, label by label."""
    o = np.argsort(labels, kind="stable")
    return np.split(o, np.nonzero(np.diff(labels[o]))[0] + 1)


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
    the next by rounding, and equal cells come out unequal. (Borders on the importer's cut lines, 4 mm beside the
    studs' centres, needed 4 rings of faces to come out as the direct bake at the plate's outer row of studs, these
    2 - run 287; the borders then pass near the studs' centres.)"""
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
HALO = 2        # rings of faces around a cell's core that are baked with it and left out of the copy (3 was no nearer
                # to a direct bake in a crop of the cut 4186, shader and bevel; 1 was further off, run 287)


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
    point_flag = np.zeros(len(co), bool)              # marks set and cleared per cell: no sorting (np.isin and
    face_flag = np.zeros(len(unit), bool)             # np.unique per ring took 6 of 11 s, run 287)
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
        face_flag[core] = True
        take = face_flag[cand]
        face_flag[core] = False
        for _ring in range(HALO):
            marked = cv[np.repeat(take, sizes[cand])]
            point_flag[marked] = True
            take = np.logical_or.reduceat(point_flag[cv], cs)
            point_flag[marked] = False
        out.append((np.sort(unit[core]), np.sort(unit[cand[take]]), corner))
    return out


def pack(islands, ids, size=None):
    """The islands `ids` in batches of up to BATCH_FACES faces, in the order of their first face (cells too: baked
    each alone, a cell of a plate came out further from the direct bake - 0.031 mm against 0.0065 at 99.9 %,
    run 287)."""
    out, cur, filled = [], [], 0
    for i in ids:
        if cur and filled + len(islands[i]) > (size or BATCH_FACES):
            out.append(cur)
            cur, filled = [], 0
        cur.append(i)
        filled += len(islands[i])
    if cur:
        out.append(cur)
    return out


def _packed(fulls, ids):
    """pack, in one batch per background Blender when they are worth it (batchpool)."""
    faces = sum(len(fulls[i]) for i in ids)
    if PARALLEL and faces >= batchpool.MIN_FACES:
        return pack(fulls, ids, batchpool.batch_size(faces, BATCH_FACES))
    return pack(fulls, ids)


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
        todo = _packed(fulls, [i for i in range(len(islands)) if i not in shared])
        done = 0
        while todo:
            subs = []
            for ids in todo:
                faces = np.unique(np.concatenate([fulls[i] for i in ids]))
                sub_arr, *_ = meshparts.select_arrays(arr, faces)
                # the piece each face is the core of, if that piece is in this batch (-1: only a ring here)
                mine = np.isin(face_island[faces], ids)
                isl = np.where(mine, face_island[faces], -1)
                isf = np.where(mine, face_in_island[faces], -1)
                sub_arr["attrs"][ISLAND] = ('FACE', 'INT', isl[:, None].astype(np.int32))
                sub_arr["attrs"][ISLAND_FACE] = ('FACE', 'INT', isf[:, None].astype(np.int32))
                subs.append((faces, meshparts.build_arrays(sub_arr, f"{orig.name}~{len(parts) + len(subs)}", orig)))
            total = done + len(subs)
            if PARALLEL and batchpool.worth(sum(len(f) for f, _s in subs), len(subs)):
                # the batches at once in background Blenders, each with this one's settings and pins (batchpool)
                gen = batchpool.bake([sub for _f, sub in subs], levels)
                while True:
                    try:
                        k, _n = next(gen)
                    except StopIteration as stop:
                        results = stop.value
                        break
                    blenders = batchpool.jobs(len(subs))
                    yield 0.02 + 0.88 * (done + k) / total, f"piece {done + k} of {total} ({blenders} Blenders)"
                for (faces, sub), (made, rep) in zip(subs, results, strict=True):
                    parts.append((faces, sub, made))
                    reports.append(rep)
                done = total
            else:
                for faces, sub in subs:
                    made, rep = welding._bake_weld(sub, levels)
                    parts.append((faces, sub, made))
                    reports.append(rep)
                    done += 1
                    yield 0.02 + 0.88 * done / total, f"piece {done} of {total}"
            # a shape whose copy cannot just be moved: its islands are baked as they are, in another round
            fixed = _fixed_shapes(parts, islands, face_island, set(shared.values()))
            back = sorted(k for k, rep in shared.items() if rep in fixed)
            for k in back:
                del shared[k], moves[k]
            todo = _packed(fulls, back)
    finally:
        ACTIVE[0] = False
        copies.QUALITY_PIN[0] = welding.FLAT_SHARE_PIN[0] = reparam.SIZE_PIN[0] = None
    made = {}
    try:
        for step, lv in enumerate(sorted(levels, reverse=True)):
            yield 0.9 + 0.1 * step / len(levels), f"joining the copies of level {lv}"
            made[lv] = join_copies(orig, arr, islands, moves, [(f, s, m[lv]) for f, s, m in parts], lv, passive,
                                   [c is not None for c in corners])
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
    import's (W18, checks.LAYOUT) - they name faces of its batch. (T points, rb_tv, only feed the check of the T gap;
    join_copies carries them over to the moved copies: they held 6 shapes and 212 cells of the cut 4186, run 287.)"""
    out = set()
    for faces, _sub, made in parts:
        for cp in made.values():
            lay = list(cp.get(checks.LAYOUT) or [])
            if lay:
                pairs = np.array(lay[1:], np.int64).reshape(-1, 2)
                out |= {int(face_island[faces[f]]) for f in pairs[:, 0] if f < len(faces)}
    return out & reps


def join_copies(orig, arr, islands, moves, parts, level, passive, is_cell=None):
    """One copy of `orig` from the copies of its batches [(faces of the import, batch mesh, its copy)] and the moved
    copies of the shared islands: the children of every face of the import in the order of the import, the faces a
    cage has beyond the import's (W18) at the end, batch by batch - as checks.cage_faces reads a copy. A bevelled copy
    is no longer in blocks: joined as it comes. `is_cell`: per piece whether it is a cell - their seams are closed
    (close_seams)."""
    n = len(orig.polygons)
    blocks, lay_pairs, extra_pairs, tvs, folds, gaps, pieces = [], [], [], [], [], [], []
    from_cell = []                                  # per piece: its points that belong to a cell's faces
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
            blocks.append((keys, starts, count))
        lay_pairs += [(int(faces[f]), int(c)) for f, c in pairs[:k_lay] if core[f]]
        extra_pairs += [(int(faces[f]), int(c)) for f, c in pairs[k_lay:] if core[f]]
        flat = list(cp.get("rb_tv", []))
        tv = []
        for v, host in zip(flat[0::2], flat[1::2], strict=True):
            j = int(np.searchsorted(verts, v))
            if j < len(verts) and verts[j] == v and (core[host] if host < nk else new_extra[host - nk] >= 0):
                tv += [j, int(faces[host]) if host < nk else n + int(new_extra[host - nk])]
        tvs.append(tv)
        tv_arr = np.array(tv, np.int64).reshape(-1, 2)  # (point of the piece, face of the import)
        if bevel.EDGE_FOLDS in cp:
            folds += [int(faces[int(x)]) for x in str(cp[bevel.EDGE_FOLDS]).split(",") if x and core[int(x)]]
        if bevel.EDGE_GAP in cp:
            gaps.append(float(cp[bevel.EDGE_GAP]))
        extra_no += int(extra_core.sum())
        offset += len(a["lt"])
        pieces.append(a)
        from_cell.append(_cell_points(a, is_cell, a["attrs"][ISLAND][2][:, 0]))
        del full
        # the shared islands whose shape this batch baked: moved to their places
        isl = a["attrs"][ISLAND][2][:, 0]
        for rep in sorted(set(isl.tolist()) & set(by_rep)):
            piece, pverts, *_ = meshparts.select_arrays(a, np.nonzero(isl == rep)[0])
            # its T points whose face is of its core, in the piece's points and the core's order
            at_core = {f: j for j, f in enumerate(islands[rep].tolist())}
            own = [(int(np.searchsorted(pverts, v)), at_core[h]) for v, h in tv_arr.tolist()
                   if h in at_core and np.searchsorted(pverts, v) < len(pverts)
                   and pverts[np.searchsorted(pverts, v)] == v]
            # its core's blocks, in the order of its core: each copy names its own faces through the move's map
            count = arr["lt"][islands[rep]] * 4 ** (level - 1)
            for k in by_rep[rep]:
                faces_k = moves[k][1]                   # the copy's faces in the order of the baked piece's core
                m = _moved(arr, piece, moves[k], passive)
                if not bevelled:
                    starts = offset + np.concatenate(([0], np.cumsum(count)[:-1]))
                    blocks.append((faces_k, starts, count))
                offset += len(m["lt"])
                pieces.append(m)
                from_cell.append(_cell_points(m, is_cell, np.full(len(m["lt"]), rep)))
                tvs.append([x for v, j in own for x in (v, int(faces_k[j]))])
            if folds:                                   # a fold on the baked piece is on its copies too
                at = {f: j for j, f in enumerate(islands[rep].tolist())}
                hit = [at[f] for f in folds if f in at]
                for k in by_rep[rep]:
                    folds += [int(moves[k][1][j]) for j in hit]
    order = None
    if not bevelled and blocks:                     # the children face by face of the import, as arrays (a list of a
        keys = np.concatenate([b[0] for b in blocks])  # million tuples took seconds per level, run 287)
        o = np.argsort(keys, kind="stable")
        starts, count = np.concatenate([b[1] for b in blocks])[o], np.concatenate([b[2] for b in blocks])[o]
        order = np.arange(int(count.sum())) + np.repeat(starts - (np.cumsum(count) - count), count)
    snapped = close_seams(pieces, from_cell) if is_cell is not None and any(is_cell) else 0
    joined, voff = meshparts.join_arrays(pieces, f"{orig.name} L{level}", parts[0][2], face_order=order,
                                         drop=(ISLAND, ISLAND_FACE))
    del pieces
    # the properties: those of a batch copy, then what belongs to the whole mesh
    joined["rb_original"], joined["rb_src"] = orig.name, copies.source_hash(orig)
    joined["rb_seam_points"] = snapped
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


SEAM_TOL = 0.08    # mm: the open points of two cells' copies this near are one point of their seam (run 287: 16,767 of
                   # 16,821 seam points of the cut 4186 found their partner within 0.05 mm)
SEAM_T_TOL = 0.005  # mm: a point without a partner this near another piece's open edge is put onto it (a T joint)


def _cell_points(piece, is_cell, island):
    """Per point of a piece: whether a face of a cell uses it (`island`: per face, the piece it was baked for)."""
    out = np.zeros(len(piece["co"]), bool)
    if is_cell is not None:
        face = np.asarray(is_cell)[island]
        out[piece["lv"][np.repeat(face, piece["lt"])]] = True
    return out


def close_seams(pieces, from_cell):
    """Cells meet at seams that were one surface in the import; baked apart, the two sides' points of a seam lie up
    to 0.05 mm apart, and the joined copy has hairline cracks there (maintainer, 15.10.2026: thin lines along the
    cells' borders of the 48 x 48 baseplate - Random Walk sees through them). The open points of cells closer than
    SEAM_TOL, of different pieces (the arrays before they are joined; `from_cell`: per piece its points of cells),
    are set to their common mean - the sides then
    share their corners to the bit, and Cycles' intersection is watertight there. Partners are mutual nearest points of
    two pieces. A point with no partner but the open edge of another piece passing within SEAM_T_TOL (a long edge of
    a large face: a T joint) is then put onto that edge. Returns the points moved. (On the arrays, not the joined
    mesh: reading and updating a copy of 14.5 M faces back took 23 s, run 287.)"""
    nv = np.array([len(p["co"]) for p in pieces], np.int64)
    voff = np.concatenate(([0], np.cumsum(nv)[:-1]))
    co = np.concatenate([p["co"] for p in pieces]).astype(np.float64)
    from_cell = np.concatenate(from_cell)
    open_ev = np.concatenate([p["ev"][np.bincount(p["le"], minlength=len(p["ev"])) == 1] + o
                              for p, o in zip(pieces, voff, strict=True)])
    open_ev = open_ev[from_cell[open_ev].all(axis=1)]
    cand = np.unique(open_ev)
    if not len(cand):
        return 0
    piece = np.searchsorted(voff, cand, side="right")
    i, j = _pairs_within(co[cand], SEAM_TOL)
    keep = piece[i] != piece[j]
    i, j = i[keep], j[keep]
    # each point with the nearest point of every other piece, kept where that one's nearest of this piece is it: near
    # a stud's foot open rings of one piece lie 0.05 mm apart, and grouping all near points chained them (run 287:
    # points pulled 0.053 mm out of the top, normals turned)
    i, j = np.concatenate((i, j)), np.concatenate((j, i))
    d = np.einsum("ij,ij->i", co[cand[i]] - co[cand[j]], co[cand[i]] - co[cand[j]])
    o = np.lexsort((d, piece[j], i))
    i, j = i[o], j[o]
    first = np.ones(len(i), bool)
    first[1:] = (i[1:] != i[:-1]) | (piece[j[1:]] != piece[j[:-1]])
    i, j = i[first], j[first]
    best = set(zip(i.tolist(), j.tolist(), strict=True))
    mutual = np.array([(b, a) in best for a, b in zip(i.tolist(), j.tolist(), strict=True)], bool)
    i, j = i[mutual], j[mutual]
    used = np.unique(np.concatenate((i, j)))
    if len(used):
        label = np.arange(len(cand))                # groups of points: the smallest index reached, spread
        while True:
            low = np.minimum(label[i], label[j])
            new = label.copy()
            np.minimum.at(new, i, low)
            np.minimum.at(new, j, low)
            new = new[new]
            if np.array_equal(new, label):
                break
            label = new
        _g, inv = np.unique(label[used], return_inverse=True)
        mean = np.zeros((int(inv.max()) + 1, 3))
        np.add.at(mean, inv, co[cand[used]])
        mean /= np.bincount(inv)[:, None]
        co[cand[used]] = mean[inv]
    alone = np.setdiff1d(np.arange(len(cand)), used)
    moved = 0
    if len(alone):
        seg, pt = _points_on_segments(co[open_ev[:, 0]], co[open_ev[:, 1]], co[cand[alone]], SEAM_T_TOL)
        keep = np.searchsorted(voff, open_ev[seg, 0], side="right") != piece[alone[pt]]
        seg, pt = seg[keep], pt[keep]
        _u, first = np.unique(pt, return_index=True)
        seg, pt = seg[first], pt[first]
        a, b = co[open_ev[seg, 0]], co[open_ev[seg, 1]]
        t = np.clip(np.einsum("ij,ij->i", co[cand[alone[pt]]] - a, b - a)
                    / np.maximum(np.einsum("ij,ij->i", b - a, b - a), 1e-18), 0, 1)
        co[cand[alone[pt]]] = a + t[:, None] * (b - a)
        moved = len(pt)
    if len(used) or moved:
        changed = np.zeros(len(co), bool)
        changed[cand[used]] = True
        if moved:
            changed[cand[alone[pt]]] = True
        for p, o, n in zip(pieces, voff, nv, strict=True):
            if changed[o:o + n].any():
                p["co"] = co[o:o + n].astype(np.float32)
    return int(len(used)) + moved


def _moved(arr, piece, move, passive):
    """The copy `piece` of a baked piece at the place of another of its shape - `move` = (that piece, the other's core
    faces in the order of its core, the offset, per UV map the affine map of each core face): moved, UVs mapped, the
    passive face attributes (the importer's stud numbers) its own, through the face each child comes from."""
    _rep, faces, offset, uv_maps = move
    isf = piece["attrs"][ISLAND_FACE][2][:, 0]
    m = dict(piece)
    m["co"] = (piece["co"].astype(np.float64) + offset).astype(np.float32)
    m["attrs"] = dict(piece["attrs"])
    for name in passive:
        d, t, values = arr["attrs"][name]
        if name in m["attrs"]:
            m["attrs"][name] = (d, t, values[faces[isf]])
    same = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    for name, fit in uv_maps.items():                   # per face of the baked core: its children's corners
        if name in m["attrs"] and np.abs(fit - same).max() > 0:
            d, t, values = m["attrs"][name]
            per = np.repeat(fit[isf], piece["lt"], axis=0)
            uv = values.astype(np.float64)
            m["attrs"][name] = (d, t, (np.einsum("ni,nij->nj", uv, per[:, :2]) + per[:, 2]).astype(np.float32))
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
