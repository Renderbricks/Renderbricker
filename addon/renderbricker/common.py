"""Shared helpers of the add-on: the meshes in scope, object mode, the version."""
import bpy
from . import rbcore as core
from . import props


# ---------------------------------------------------------------- helpers
def targets(context):
    s = context.scene.mecsub
    if s.scope == 'SELECTED':
        obs = context.selected_objects
    else:                                   # the collections and their child collections, objects of this scene;
        seen, obs = set(), []               # never the whole scene: other models lie in it (UPDATES #33)
        for c in props.scope_collections(s):
            for o in c.all_objects:
                if o not in seen and context.scene.objects.get(o.name) is o:
                    seen.add(o)
                    obs.append(o)
    return [o for o in obs if o.type == 'MESH' and o.data.polygons and not core.is_master(o)
            and o.name != core.WORK_NAME]


def object_mode(context):
    """Mesh data in Edit Mode is empty from Python (attributes of length 0: 'foreach_set ...
    needed 0', run 39) - leave it before working on meshes."""
    if context.mode != 'OBJECT' and context.object:
        bpy.ops.object.mode_set(mode='OBJECT')


def by_mesh(obs):
    """Objects grouped by their original mesh (links of one mesh together)."""
    out = {}
    for o in obs:
        out.setdefault(core.original_of(o.data), []).append(o)
    return out


def seam_gaps(me, ev, level):
    """Largest distance between subdivided points that must coincide: at shared boundary
    vertices and along shared boundary edges (same check as verify_part). me: original,
    ev: its subdivided copy."""
    import bmesh
    bm = bmesh.new(); bm.from_mesh(me)
    P = lambda co: tuple(round(c, 4) for c in co)
    gv = 0.0
    groups = {}
    for v in bm.verts:
        if v.is_boundary:
            groups.setdefault(P(v.co), []).append(v.index)
    for g in groups.values():
        if len(g) > 1:
            pts = [ev.vertices[i].co for i in g]
            gv = max(gv, max((a - b).length for a in pts for b in pts))
    ge = 0.0
    inner, nv = 2 ** level - 1, len(me.vertices)
    if len(ev.vertices) >= nv + inner * len(me.edges):
        pairs = {}
        for e in bm.edges:
            if e.is_boundary:
                pairs.setdefault(frozenset((P(e.verts[0].co), P(e.verts[1].co))), []).append((e.index, P(e.verts[0].co)))
        for es in pairs.values():
            if len(es) < 2:
                continue
            i0, a0 = es[0]
            ref = [ev.vertices[nv + inner * i0 + k].co for k in range(inner)]
            for i1, a1 in es[1:]:
                pts = [ev.vertices[nv + inner * i1 + k].co for k in range(inner)]
                if a1 != a0:
                    pts = pts[::-1]
                ge = max(ge, max((p - q).length for p, q in zip(ref, pts)))
    bm.free()
    return gv, ge


# ---------------------------------------------------------------- panel
VERSION = ".".join(str(x) for x in __import__("sys").modules[__package__].bl_info["version"])
