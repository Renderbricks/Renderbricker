"""Organic surfaces shade round in variant A (rules 3.12, M2b, UPDATES #56, run 291).

Variant A lets the subdivision interpolate the imported custom normals. On hair and other organic parts Mecabricks
shades every strand as a few flat facets, so the copy is round but shades as stripes (maintainer's review video of
27.10.2026, 36037: "sehr problematisch", run 291: with the copy's own smooth normals the same copy is round). Of three
ways the maintainer chose "2. Sieht sauberer aus.": variant A stays, but on organic surfaces the imported normals
are kept only at the grooves.

Only on organic parts - less than welding.MECH_FLAT of the area in islands that are not curved, the split W15 uses
(hair: up to 0.10): run 291's library check found every brick changed at its studs (the stud's wall is a curved
island; its top edge shaded harder, a light ring at its foot).
So, on such a part, on the children of import faces in curved islands (creases.classify - flat faces and logos keep A):
  - a groove is an edge of the copy on a fully creased edge of the cage (the whole crease chain - the copy carries
    crease_edge until strip_copy), or one where the subdivided surface still bends by GROOVE_KINK or more;
  - a corner on a groove's point keeps its interpolated import normal;
  - every other corner takes the smooth normal of the subdivided surface, split at the grooves only; the faces
    between blend from one to the other.
Run 291 tried keeping every corner of a face that touches a groove: small square patches along the strands. The
first build took the bend alone: a crease chain bending by 10 to 35 deg (23186 L1: 328 of 1,704 creased edges) stayed
kinked but took one smooth normal across the kink, and along a chain the verdict changed where the bend crossed 35 deg -
soft light and dark patches at the ends of the strands (maintainer's screenshots 28.10.2026). Smooth normals on the
grooves too (no import normals kept) washed the strands' edges out."""
import bmesh
import bpy
import numpy as np

from . import checks, config, creases

GROOVE_KINK = 35.0      # degrees: an edge of the copy bending this much is a groove (run 291: 20 took soft facets too)
ORGANIC = "rb_organic"  # copy property: corners that took the smooth normal (0 when nothing was organic)


def _curved(orig):
    """Per import face: in a curved island."""
    bm = bmesh.new()
    bm.from_mesh(orig)
    bm.faces.ensure_lookup_table()
    out = np.zeros(len(orig.polygons), bool)
    for kind, comp, _n in creases.classify(bm):
        if kind == "curved":
            out[[f.index for f in comp]] = True
    bm.free()
    return out


def _flat_share(orig, curved):
    """The share of the area of `orig` in islands that are not curved - of the whole mesh for a batch of it
    (welding.FLAT_SHARE_PIN, as the rules take it)."""
    # imported here: welding imports copies, which imports this module
    from . import welding
    if welding.FLAT_SHARE_PIN[0] is not None:
        return welding.FLAT_SHARE_PIN[0]
    area = np.empty(len(orig.polygons))
    orig.polygons.foreach_get("area", area)
    return float(area[~curved].sum() / max(area.sum(), 1e-12))


def _mech_flat():
    from . import welding
    return welding.MECH_FLAT


def _grooves(cp):
    """Per edge of `cp`: fully creased (while the copy still has crease_edge), or its two faces bend by GROOVE_KINK or
    more."""
    nl, nf = len(cp.loops), len(cp.polygons)
    le = np.empty(nl, np.int64)
    cp.loops.foreach_get("edge_index", le)
    lt = np.empty(nf, np.int64)
    cp.polygons.foreach_get("loop_total", lt)
    fn = np.empty(nf * 3, np.float64)
    cp.polygons.foreach_get("normal", fn)
    fn = fn.reshape(-1, 3)
    face = np.repeat(np.arange(nf), lt)
    o = np.argsort(le, kind="stable")
    e, f = le[o], face[o]
    edge, first, count = np.unique(e, return_index=True, return_counts=True)
    two = count == 2                                    # edges between exactly two faces
    a, b = f[first[two]], f[first[two] + 1]
    out = np.zeros(len(cp.edges), bool)
    out[edge[two]] = (fn[a] * fn[b]).sum(axis=1) <= np.cos(np.radians(GROOVE_KINK))
    ce = cp.attributes.get("crease_edge")
    if ce is not None:
        crease = np.empty(len(cp.edges), np.float32)
        ce.data.foreach_get("value", crease)
        out |= crease >= 0.99
    return out


def smooth_normals(orig, cp, level):
    """Give the organic surfaces of the copy `cp` (level `level` of `orig`) the smooth normals of its own surface,
    the import's at the grooves (see above). Variant A only. Returns the number of corners that changed."""
    if config.SHADING != "mecabricks" or not len(cp.polygons):
        return 0
    sizes, owner = checks.cage_faces(orig, cp)
    kids = sizes * 4 ** (level - 1)
    if int(kids.sum()) != len(cp.polygons):            # not the subdivision of `orig` face by face: leave it
        return 0
    curved = _curved(orig)
    if _flat_share(orig, curved) >= _mech_flat():
        cp[ORGANIC] = 0
        return 0
    organic = np.repeat(curved[owner], kids)
    groove = _grooves(cp)
    nl = len(cp.loops)
    have = np.empty(nl * 3, np.float32)
    cp.corner_normals.foreach_get("vector", have)
    # the surface's own normals, split at the grooves only: a copy of the mesh without its normals and flags
    plain = cp.copy()
    try:
        for name in ("custom_normal", "sharp_face", "sharp_edge"):
            if plain.attributes.get(name):
                plain.attributes.remove(plain.attributes[name])
        plain.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE').data.foreach_set("value", groove)
        own = np.empty(nl * 3, np.float32)
        plain.corner_normals.foreach_get("vector", own)
    finally:
        bpy.data.meshes.remove(plain)
    lt = np.empty(len(cp.polygons), np.int64)
    cp.polygons.foreach_get("loop_total", lt)
    lv = np.empty(nl, np.int64)
    cp.loops.foreach_get("vertex_index", lv)
    ev = np.empty(len(cp.edges) * 2, np.int64)
    cp.edges.foreach_get("vertices", ev)
    on_groove = np.zeros(len(cp.vertices), bool)
    on_groove[ev.reshape(-1, 2)[groove].ravel()] = True
    take = np.repeat(organic, lt) & ~on_groove[lv]
    if not take.any():
        cp[ORGANIC] = 0
        return 0
    new = np.where(take[:, None], own.reshape(-1, 3), have.reshape(-1, 3))
    # every corner is set; the copy's faces stay flat-flagged (sharp_face, as variant A bakes them): each corner is
    # its own smooth fan, so Blender stores each normal as given - in a fan of several corners it averages those
    # that differ by less than 0.81 deg, and a copy with its faces reordered (maps._reversed) decodes them otherwise
    # (mesh_normals.cc 1505-1517, 1576-1594; run 291: the first build cleared the flags, smooth_maps failed)
    cp.normals_split_custom_set(new.tolist())
    cp[ORGANIC] = int(take.sum())
    return int(take.sum())
