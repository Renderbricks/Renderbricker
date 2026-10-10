"""The subdivided copies of a part: baking a level, UVs, links pointing to the copy of a level, masters."""
import bpy
import numpy as np
from . import config, creases, reparam, workscene


def original_of(me):
    """The imported mesh behind a (possibly subdivided) mesh."""
    name = me.get("rb_original")
    return bpy.data.meshes.get((name, None), me) if name else me     # the local one (run 65)


def source_hash(me):
    """Fingerprint of an import's geometry (UPDATES #18): positions, corners and UVs. Stored on every copy as
    rb_src when it is baked; Apply converts a mesh again when its import no longer matches - an edit in Edit Mode
    (or with Subdivision OFF) was kept as the old copy before."""
    import hashlib
    h = hashlib.blake2b(digest_size=12)
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    lv = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", lv)
    lt = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_total", lt)
    h.update(np.round(co, 5).tobytes()); h.update(lv.tobytes()); h.update(lt.tobytes())
    for u in me.uv_layers:
        uv = np.empty(len(me.loops) * 2, np.float32); u.data.foreach_get("uv", uv)
        h.update(np.round(uv, 5).tobytes())
    return h.hexdigest()


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


def bake_copy(orig, work, level):
    """Evaluate `work` (the original with the finished creases) at `level` and store the
    result as a mesh of its own - positions and custom normals identical to the modifier
    (run 38: max. difference 0.0 on all 254 Porsche meshes)."""
    pass
    keep = config.LEVELS
    config.LEVELS = level
    try:
        mod = work.modifiers.get("Subdivision")
        if mod:
            creases.add_subsurf(work)                   # level and custom normals for this copy
            # the limit surface near free two-edge boundary vertices is only approximated at
            # the default quality 3: seams opened by up to 0.018 (run 42). Quality 10 is exact
            # there (0.0); used only for the copies, the checks keep the fast default.
            mod.quality = bake_quality(orig)
            if config.REPARAM:
                mod.uv_smooth = 'NONE'                  # W14c: linear UVs, the points slide back below
                reparam.mark(work)
        dg = workscene.depsgraph_of(work)
        oe = work.evaluated_get(dg)
        cp = bpy.data.meshes.new_from_object(oe, preserve_all_data_layers=True, depsgraph=dg)
        if mod and config.REPARAM:
            try:
                par = reparam.param_positions(cp)
                if par is not None:
                    reparam.slide(cp, *par, orig=orig, level=level)
            except Exception as e:                      # never leave linear UVs on unslid points: W14's smoothed UVs
                print(f"Renderbricker: reparametrisation failed for {orig.name} ({type(e).__name__}: {e}) - smoothed UVs")
                bpy.data.meshes.remove(cp)
                mod.uv_smooth = config.UV_SMOOTH
                dg = workscene.depsgraph_of(work); dg.update()
                cp = bpy.data.meshes.new_from_object(work.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    finally:
        config.LEVELS = keep
    cp.name = f"{orig.name} L{level}"
    cp["rb_original"], cp["rb_level"], cp["rb_variant"] = orig.name, level, config.SHADING
    cp["rb_rules"] = config.RULES_VERSION          # Apply skips meshes whose copies are up to date (user, 2026-09-28)
    cp["rb_src"] = source_hash(orig)                # ... and whose import was not edited since (UPDATES #18)
    if _COPY_INDEX[0] is not None:
        _COPY_INDEX[0].setdefault(orig.name, []).append(cp)
    cp.use_fake_user = True      # a copy no link uses right now (L1, the render copy) is saved too (run 40)
    if config.UV_PROJECT:
        project_uvs(orig, cp, level)
    strip_copy(cp)
    return cp


def discard_copy(orig, cp):
    """Remove a copy baked in this run again (baked anew after a late fold repair, W10b)."""
    idx = _COPY_INDEX[0]
    if idx is not None and cp in idx.get(orig.name, []):
        idx[orig.name].remove(cp)
    bpy.data.meshes.remove(cp)


# Data of the welded work mesh that the finished copies do not need (run 61: 11 % of an L2
# copy of Ratatouille): creases (already in the geometry), island and face numbers of the
# rules, the selection flags of the import (a copy is never edited).
COPY_DROP = ("crease_edge", "crease_vert", "rb_island", "rb_fi", "rb_param", "rb_rim", "rb_shell")


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
        for c0 in range(0, n, config.UV_CHUNK):          # chunks: a 4.5 M-face copy has 18 M corners
            idx = np.nonzero(tcount[owner[c0:c0 + config.UV_CHUNK]] > k)[0] + c0
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
    """Let the objects use the viewport (or render) copy of their original. They are marked as converted (rb_on): at
    viewport level 0 they show the original like an object of the same mesh outside the scope, and only the marked
    ones go to the render copy for F12 (UPDATES #24)."""
    target = copy_of(orig, which) or orig
    converted = target is not orig or copy_of(orig, "render") is not None
    for ob in obs:
        if ob.data != target:
            ob.data = target
        if converted and not ob.get("rb_on"):
            ob["rb_on"] = 1


def render_targets(obs):
    """(object, render copy) for every object of `obs` that a render shows on the render copy: those on the view
    copy, and those on the original that Apply marked (rb_on, viewport level 0) - an object of the same mesh outside
    the scope stays on the original (UPDATES #24). Meshes converted before 1.2.8 have no mark at all: all their
    objects on the original go, as before. Switched-off objects (rb_off) stay."""
    obs = [ob for ob in obs if ob.type == 'MESH' and ob.data is not None and not ob.get("rb_off")]
    marked = {original_of(ob.data) for ob in obs if ob.get("rb_on")}
    out = []
    for ob in obs:
        orig = original_of(ob.data)
        rc = copy_of(orig, "render")
        if rc is None or ob.data == rc:
            continue
        if ob.data == copy_of(orig, "view") or (ob.data == orig and (ob.get("rb_on") or orig not in marked)):
            out.append((ob, rc))
    return out


def drop_copies(orig, keep=()):
    """Remove the copies of a mesh that nothing uses any more (keep: the copies to keep)."""
    for m in all_copies(orig):
        if m not in keep and real_users(m) == 0:
            bpy.data.meshes.remove(m)


def bake_quality(me):
    return config.BAKE_QUALITY if len(me.polygons) <= config.QUALITY_FACE_LIMIT else config.BAKE_QUALITY_LARGE


def copies_by_level(orig):
    return {int(m.get("rb_level", 0)): m for m in all_copies(orig)}


def missing_levels(orig, view, render):
    have = copies_by_level(orig)
    return sorted(lv for lv in {view, render} - {0} if lv not in have)


def up_to_date(orig, view, render):
    """The copies of this mesh for the viewport and render level exist and come from the current rules,
    variant and method and the import was not edited since (rb_src) - Apply can skip the mesh (user, 2026-09-28).
    Copies made before 1.0.0 carry no rules version, before 1.2.6 no source fingerprint: converted again."""
    have = copies_by_level(orig)
    need = {lv for lv in (view, render) if lv}
    if not need or any(lv not in have for lv in need):
        return False
    src = source_hash(orig)
    return all(have[lv].get("rb_rules") == config.RULES_VERSION and have[lv].get("rb_variant") == config.SHADING
               and (have[lv].get("rb_method") == "weld") == (config.METHOD == "weld")
               and have[lv].get("rb_src") == src for lv in need)


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
