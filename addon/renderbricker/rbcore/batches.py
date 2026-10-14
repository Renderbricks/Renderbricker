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


def shape_classes(arr, units, passive):
    """{unit: the first unit of its shape} for every unit that is another one moved: the same faces with the same
    corners, the corners meeting their points in the same order, the positions relative to the first corner's point
    equal to 0.0001 mm, every attribute but the `passive` ones equal (floats to 1e-6). Compared group by group of units
    of the same size, as rows of one array each (11,521 units of the 48 x 48 baseplate in a second, run 287)."""
    co, lv, le, lt = arr["co"], arr["lv"], arr["le"], arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    size = {}
    for k, g in enumerate(units):
        size.setdefault((len(g), int(lt[g].sum())), []).append(k)
    shared = {}
    for (nf, _nl), ids in size.items():
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


def pack(islands, ids):
    """The islands `ids` in batches of up to BATCH_FACES faces, in the order of their first face."""
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
    islands, flat = unit_plan(orig, arr)
    n = len(orig.polygons)
    face_island = np.empty(n, np.int64)
    face_in_island = np.empty(n, np.int64)
    for k, g in enumerate(islands):
        face_island[g], face_in_island[g] = k, np.arange(len(g))
    passive = {name for name, (d, _t, _v) in arr["attrs"].items()
               if d == 'FACE' and name not in GEOMETRIC_FACE and not name.startswith(".")}
    shared = shape_classes(arr, islands, passive) if SHARE else {}      # island -> the island of its shape baked
    quality = copies.bake_quality(orig)
    _guard(orig, levels, islands, [i for i in range(len(islands)) if i not in shared], quality)
    yield 0.02, f"{len(islands):,} islands of {len(islands) - len(shared):,} shapes"
    ACTIVE[0] = True
    copies.QUALITY_PIN[0], welding.FLAT_SHARE_PIN[0], reparam.SIZE_PIN[0] = quality, flat, reparam.part_size(orig)
    parts, reports = [], []
    try:
        todo = pack(islands, [i for i in range(len(islands)) if i not in shared])
        done = 0
        while todo:
            for j, ids in enumerate(todo):
                faces = np.sort(np.concatenate([islands[i] for i in ids]))
                sub_arr, *_ = meshparts.select_arrays(arr, faces)
                sub_arr["attrs"][ISLAND] = ('FACE', 'INT', face_island[faces][:, None].astype(np.int32))
                sub_arr["attrs"][ISLAND_FACE] = ('FACE', 'INT', face_in_island[faces][:, None].astype(np.int32))
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
                del shared[k]
            todo = pack(islands, back)
    finally:
        ACTIVE[0] = False
        copies.QUALITY_PIN[0] = welding.FLAT_SHARE_PIN[0] = reparam.SIZE_PIN[0] = None
    made = {}
    try:
        for step, lv in enumerate(sorted(levels, reverse=True)):
            yield 0.9 + 0.1 * step / len(levels), f"joining the copies of level {lv}"
            made[lv] = join_copies(orig, arr, islands, shared, face_island,
                                   [(f, s, m[lv]) for f, s, m in parts], lv, passive)
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


def join_copies(orig, arr, islands, shared, face_island, parts, level, passive):
    """One copy of `orig` from the copies of its batches [(faces of the import, batch mesh, its copy)] and the moved
    copies of the shared islands: the children of every face of the import in the order of the import, the faces a
    cage has beyond the import's (W18) at the end, batch by batch - as checks.cage_faces reads a copy. A bevelled copy
    is no longer in blocks: joined as it comes."""
    n = len(orig.polygons)
    blocks, lay_pairs, extra_pairs, tvs, folds, gaps, pieces = [], [], [], [], [], [], []
    offset, extra_no = 0, 0
    bevelled = bevel.is_bevelled(parts[0][2])
    by_rep = {}
    for k, rep in shared.items():
        by_rep.setdefault(rep, []).append(k)
    for faces, sub, cp in parts:
        nk = len(faces)
        a = meshparts.mesh_arrays(cp)
        if not bevelled:
            sizes, _owner = checks.cage_faces(sub, cp)
            count = sizes * 4 ** (level - 1)
            starts = offset + np.concatenate(([0], np.cumsum(count)[:-1]))
            keys = np.where(np.arange(len(sizes)) < nk, faces[np.minimum(np.arange(len(sizes)), nk - 1)],
                            n + extra_no + np.arange(len(sizes)) - nk)
            blocks += list(zip(keys.tolist(), starts.tolist(), count.tolist()))
        lay = list(cp.get(checks.LAYOUT) or [])
        if lay:
            k = int(lay[0])
            pairs = np.array(lay[1:], np.int64).reshape(-1, 2)
            lay_pairs += [(int(faces[f]), int(c)) for f, c in pairs[:k]]
            extra_pairs += [(int(faces[f]), int(c)) for f, c in pairs[k:]]
        tvs.append((list(cp.get("rb_tv", [])), faces, nk, extra_no))
        if bevel.EDGE_FOLDS in cp:
            folds += [int(faces[int(x)]) for x in str(cp[bevel.EDGE_FOLDS]).split(",") if x]
        if bevel.EDGE_GAP in cp:
            gaps.append(float(cp[bevel.EDGE_GAP]))
        extra_no += len(lay[1:]) // 2 - int(lay[0]) if lay else 0
        offset += len(a["lt"])
        pieces.append(a)
        # the shared islands whose shape this batch baked: moved to their places
        isl = a["attrs"][ISLAND][2][:, 0]
        for rep in sorted(set(isl.tolist()) & set(by_rep)):
            piece, *_ = meshparts.select_arrays(a, np.nonzero(isl == rep)[0])
            moved = _moved(arr, islands, rep, by_rep[rep], piece, passive)
            for k, m in zip(by_rep[rep], moved, strict=True):
                if not bevelled:
                    count = arr["lt"][islands[k]] * 4 ** (level - 1)
                    starts = offset + np.concatenate(([0], np.cumsum(count)[:-1]))
                    blocks += list(zip(islands[k].tolist(), starts.tolist(), count.tolist()))
                offset += len(m["lt"])
                pieces.append(m)
                tvs.append(([], None, 0, 0))
            if folds:                                   # a fold on the baked island is on its copies too
                rep_faces = set(islands[rep].tolist())
                at = {f: j for j, f in enumerate(islands[rep].tolist())}
                hit = [at[f] for f in folds if f in rep_faces]
                for k in by_rep[rep]:
                    folds += [int(islands[k][j]) for j in hit]
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
    for (flat, faces, nk, extra0), off in zip(tvs, voff, strict=True):
        for v, host in zip(flat[0::2], flat[1::2], strict=True):
            flat_tv += [int(off + v), int(faces[host]) if host < nk else n + extra0 + (host - nk)]
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


def _moved(arr, islands, rep, members, piece, passive):
    """The copy `piece` of the island `rep` at the places of the islands `members` (each moved by the difference of
    their first points; the passive face attributes their own, through the face of the island each face comes from)."""
    lt = arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    co, lv = arr["co"], arr["lv"]
    anchor = co[lv[ls[islands[rep][0]]]].astype(np.float64)
    isf = piece["attrs"][ISLAND_FACE][2][:, 0]
    out = []
    for k in members:
        m = dict(piece)
        m["co"] = (piece["co"].astype(np.float64) + (co[lv[ls[islands[k][0]]]] - anchor)).astype(np.float32)
        m["attrs"] = dict(piece["attrs"])
        for name in passive:
            d, t, values = arr["attrs"][name]
            if name in m["attrs"]:
                m["attrs"][name] = (d, t, values[islands[k][isf]])
        out.append(m)
    return out


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
