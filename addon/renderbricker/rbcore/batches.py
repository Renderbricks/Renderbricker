"""Large meshes in batches of islands (UPDATES #54, run 287). The memory of a bake grows with the mesh: the 48 x 48
baseplate 4186 needs about 58 GB as Mecabricks made it and 91 GB with the importer's Clean Stud Bases. The
subdivision never reaches across an island, and the welded copies of a baseplate are thousands of small islands
(3857: 2,561, the largest 1,129 of 1.73 M vertices). So a large mesh is welded once to find its islands, then every
batch of islands goes through the whole chain of rules as a mesh of its own (welding._bake_weld, unchanged), and the
copies of the batches are joined in the face order of a direct bake. Three values the rules take from the whole mesh
are kept for every batch: the bake quality (copies.bake_quality, by the face count), the flat share (welding, W15) and
the part size (reparam, MIN_SLIDE). Everything else is decided per island (shrink.py, welding._bake_weld, reparam).
The memory is then that of the largest batch plus the joined copies."""
import bpy
import numpy as np
from . import bevel, checks, config, copies, meshparts, reparam, welding

BATCH_FACES = int(config.opt("--batch-faces", "40000"))     # faces of the import per batch; 0: never in batches
ACTIVE = [False]               # a batch is being baked: no batches inside a batch
BEVEL_COUNTS = ("rb_bevel_normals", "rb_bevel_support", "rb_bevel_plain", "rb_bevel_moved", "rb_bevel_back",
                "rb_bevel_flat")   # counts bevel.bevel_copy leaves on a copy: added over the batches


def wanted(orig):
    """Whether this mesh is baked in batches."""
    return not ACTIVE[0] and BATCH_FACES > 0 and len(orig.polygons) > BATCH_FACES


def island_batches(orig):
    """Batches of the import's faces: whole islands of the welded mesh (with its T vertices, which join a point of one
    island to the face of another), packed in the order of their first face up to BATCH_FACES faces. Also returns the
    flat share of the whole mesh (welding, stage 1)."""
    welding.EXCLUDE_RUNG.clear(); welding.EXCLUDE_PLANE.clear()      # as weld_work starts
    wm, tv, _rep = welding.weld(orig)
    try:
        flat = welding.LAST_FLAT_SHARE[0]
        co, ev, lv, le, ls, lt = meshparts.topology(wm)
        links = [(v, lv[ls[host]]) for v, host in tv]      # a T vertex belongs to the island of its host face
        lab = meshparts.point_islands(wm, links)
        n = len(orig.polygons)
        own = np.arange(len(lt))
        at = wm.attributes.get("rb_fi")     # the import's face of every cage face (W18 cuts faces in two)
        if at is not None:
            at.data.foreach_get("value", own)
        label = lab[lv[ls]]
        island_of = np.full(n, -1, np.int64)
        island_of[own] = label
    finally:
        bpy.data.meshes.remove(wm)
    order = np.argsort(island_of, kind="stable")
    keys, starts = np.unique(island_of[order], return_index=True)
    groups = sorted(np.split(order, starts[1:]), key=lambda g: int(g[0]))
    batches, cur = [], []
    for g in groups:
        if cur and sum(len(x) for x in cur) + len(g) > BATCH_FACES:
            batches.append(np.sort(np.concatenate(cur)))
            cur = []
        cur.append(g)
    if cur:
        batches.append(np.sort(np.concatenate(cur)))
    return batches, flat


def bake(orig, levels):
    """The copies of `orig` for `levels` and the report, as welding._bake_weld gives them - baked batch by batch."""
    batches, flat = island_batches(orig)
    quality = copies.bake_quality(orig)
    # the memory guard counted on batches of BATCH_FACES; one island can be larger (run 287: 4186 with the importer's
    # Clean Stud Bases welds into one island of most of the plate - the run crashed at 56 GB): the largest batch is
    # checked against the free memory now, so that Apply stops cleanly instead (memory.check_memory, run 49)
    largest = max(len(b) for b in batches)
    if largest > BATCH_FACES:
        from . import memory
        level = max(levels)
        need = largest * memory.GB_PER_FACE.get(quality, 0.2e-3) * 1.05 * 4 ** max(0, level - 2) \
            + len(orig.polygons) * memory.GB_PER_FACE_KEPT * 4 ** max(0, level - 2) + memory.GB_MARGIN
        free = memory.free_memory_gb()
        if free is not None and need > free:
            raise memory.MemoryShortage(
                f"not enough free memory for {orig.name} ({len(orig.polygons):,} faces, one piece of "
                f"{largest:,} faces that cannot be split): needs about {need:.0f} GB, {free:.0f} GB free - close "
                f"other programs and apply again")
    parts, reports = [], []
    ACTIVE[0] = True
    copies.QUALITY_PIN[0], welding.FLAT_SHARE_PIN[0], reparam.SIZE_PIN[0] = quality, flat, reparam.part_size(orig)
    try:
        for k, faces in enumerate(batches):
            sub, *_ = meshparts.sub_mesh(orig, faces, f"{orig.name}~{k}")
            made, rep = welding._bake_weld(sub, levels)
            parts.append((faces, sub, made))
            reports.append(rep)
    finally:
        ACTIVE[0] = False
        copies.QUALITY_PIN[0] = welding.FLAT_SHARE_PIN[0] = reparam.SIZE_PIN[0] = None
    try:
        made = {lv: join_copies(orig, [(f, s, m[lv]) for f, s, m in parts], lv) for lv in levels}
    finally:
        for _f, sub, m in parts:
            for cp in m.values():
                copies.discard_copy(sub, cp)
            bpy.data.meshes.remove(sub)
    rep = merge_reports(reports)
    rep["batches"], rep["batch_faces_max"] = len(batches), max(len(b) for b in batches)
    return made, rep


def join_copies(orig, parts, level):
    """One copy of `orig` from the copies of its batches [(faces of the import, batch mesh, its copy)]: the children of
    every face of the import in the order of the import, the faces a cage has beyond the import's (W18) at the end,
    batch by batch - as checks.cage_faces reads a copy. A bevelled copy is no longer in blocks: joined as it comes."""
    n = len(orig.polygons)
    blocks, lay_pairs, extra_pairs, tv, folds, gaps = [], [], [], [], [], []
    offset, extra_no = 0, 0
    bevelled = bevel.is_bevelled(parts[0][2])
    for faces, sub, cp in parts:
        nk = len(faces)
        if not bevelled:
            sizes, owner = checks.cage_faces(sub, cp)
            count = sizes * 4 ** (level - 1)
            starts = offset + np.concatenate(([0], np.cumsum(count)[:-1]))
            for i in range(len(sizes)):
                key = int(faces[i]) if i < nk else n + extra_no + (i - nk)
                blocks.append((key, int(starts[i]), int(count[i])))
        lay = list(cp.get(checks.LAYOUT) or [])
        if lay:
            k = int(lay[0])
            pairs = np.array(lay[1:], np.int64).reshape(-1, 2)
            lay_pairs += [(int(faces[f]), int(c)) for f, c in pairs[:k]]
            extra_pairs += [(int(faces[f]), int(c)) for f, c in pairs[k:]]
        flat = list(cp.get("rb_tv", []))
        tv.append((flat, faces, nk, extra_no))
        if bevel.EDGE_FOLDS in cp:
            folds += [int(faces[int(x)]) for x in str(cp[bevel.EDGE_FOLDS]).split(",") if x]
        if bevel.EDGE_GAP in cp:
            gaps.append(float(cp[bevel.EDGE_GAP]))
        extra_no += len(lay[1:]) // 2 - int(lay[0]) if lay else 0
        offset += len(cp.polygons)
    order = None
    if not bevelled:
        blocks.sort()
        order = np.concatenate([np.arange(s, s + c) for _k, s, c in blocks]) if blocks else None
    joined, voff = meshparts.join([cp for _f, _s, cp in parts], f"{orig.name} L{level}", face_order=order)
    # the properties: those of a batch copy, then what belongs to the whole mesh
    joined["rb_original"], joined["rb_src"] = orig.name, copies.source_hash(orig)
    if checks.LAYOUT in joined:
        del joined[checks.LAYOUT]
    if lay_pairs or extra_pairs:
        joined[checks.LAYOUT] = [len(lay_pairs)] + [x for p in lay_pairs + extra_pairs for x in p]
    flat_tv = []
    for (flat, faces, nk, extra0), off in zip(tv, voff):
        for v, host in zip(flat[0::2], flat[1::2]):
            flat_tv += [int(off + v), int(faces[host]) if host < nk else n + extra0 + (host - nk)]
    joined["rb_tv"] = flat_tv
    if bevel.EDGE_FOLDS in parts[0][2]:
        joined[bevel.EDGE_FOLDS] = ",".join(str(i) for i in sorted(set(folds)))
    if gaps:
        joined[bevel.EDGE_GAP] = max(gaps)
    for key in BEVEL_COUNTS:                        # what bevel_copy counted, over all batches (a batch without a
        if any(key in cp for _f, _s, cp in parts):  # chosen edge has no counts)
            joined[key] = sum(int(cp.get(key, 0)) for _f, _s, cp in parts)
    if any(bevel.EDGE_ATTR in cp for _f, _s, cp in parts):
        joined[bevel.EDGE_ATTR] = next(cp[bevel.EDGE_ATTR] for _f, _s, cp in parts if bevel.EDGE_ATTR in cp)
    joined.use_fake_user = True
    if copies._COPY_INDEX[0] is not None:
        copies._COPY_INDEX[0].setdefault(orig.name, []).append(joined)
    return joined


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
