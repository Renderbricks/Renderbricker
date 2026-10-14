"""Parts of a mesh (UPDATES #54, run 287): a mesh of some of its faces and meshes put back together - exactly: the same
vertices, edges, faces and corners in their relative order, every attribute with its values (custom normals, UVs,
creases, sharp edges, ...), the material slots and the custom properties. The bake of a large mesh goes through it in
batches of islands (rbcore/batches.py)."""
import bpy
import numpy as np

# the generic attribute data: key of foreach_get and values per element
_KEY = {'FLOAT': 'value', 'INT': 'value', 'INT8': 'value', 'BOOLEAN': 'value', 'FLOAT_VECTOR': 'vector',
        'FLOAT2': 'vector', 'INT16_2D': 'value', 'INT32_2D': 'value', 'FLOAT_COLOR': 'color', 'BYTE_COLOR': 'color',
        'QUATERNION': 'value', 'FLOAT4X4': 'value'}
_WIDTH = {'FLOAT': 1, 'INT': 1, 'INT8': 1, 'BOOLEAN': 1, 'FLOAT_VECTOR': 3, 'FLOAT2': 2, 'INT16_2D': 2,
          'INT32_2D': 2, 'FLOAT_COLOR': 4, 'BYTE_COLOR': 4, 'QUATERNION': 4, 'FLOAT4X4': 16}
_DTYPE = {'FLOAT': np.float32, 'INT': np.int32, 'INT8': np.int32, 'BOOLEAN': bool, 'FLOAT_VECTOR': np.float32,
          'FLOAT2': np.float32, 'INT16_2D': np.int32, 'INT32_2D': np.int32, 'FLOAT_COLOR': np.float32,
          'BYTE_COLOR': np.float32, 'QUATERNION': np.float32, 'FLOAT4X4': np.float32}
# topology and positions are written through vertices / edges / loops / polygons
_TOPOLOGY = {'position', '.edge_verts', '.corner_vert', '.corner_edge'}


def topology(me):
    """Positions, edge vertices, corner vertices and edges, face starts and sizes as arrays."""
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    ev = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", ev)
    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
    le = np.empty(len(me.loops), np.int64); me.loops.foreach_get("edge_index", le)
    ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_total", lt)
    return co.reshape(-1, 3), ev.reshape(-1, 2), lv, le, ls, lt


def point_islands(me, links=None):
    """The island of every vertex of `me` (joined by edges, and by the vertex pairs `links`): the smallest vertex
    index in it. Label propagation with pointer jumping - a few passes of numpy over the edges."""
    ev = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
    if links is not None and len(links):
        ev = np.concatenate([ev, np.asarray(links, np.int64).reshape(-1, 2)])
    lab = np.arange(len(me.vertices))
    while True:
        m = np.minimum(lab[ev[:, 0]], lab[ev[:, 1]])
        new = lab.copy()
        np.minimum.at(new, ev[:, 0], m)
        np.minimum.at(new, ev[:, 1], m)
        new = new[new]
        if np.array_equal(new, lab):
            return lab
        lab = new


def island_faces(me, faces):
    """All faces of `me` in the islands of `faces`."""
    lab = point_islands(me)
    ls = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get("loop_start", ls)
    lv = np.empty(len(me.loops), np.int64); me.loops.foreach_get("vertex_index", lv)
    flab = lab[lv[ls]]
    return np.nonzero(np.isin(flab, flab[np.asarray(sorted(faces), np.int64)]))[0]


def face_loops(ls, lt, faces):
    """The corners of `faces`, face by face."""
    sizes = lt[faces]
    first = np.repeat(ls[faces] - np.concatenate(([0], np.cumsum(sizes)[:-1])), sizes)
    return first + np.arange(int(sizes.sum()))


def attribute_values(me, name):
    a = me.attributes[name]
    v = np.empty(len(a.data) * _WIDTH[a.data_type], _DTYPE[a.data_type])
    if len(a.data):
        a.data.foreach_get(_KEY[a.data_type], v)
    return v.reshape(len(a.data), -1)


def _attributes(me):
    """(name, domain, type) of the attributes that are copied as values."""
    return [(a.name, a.domain, a.data_type) for a in me.attributes
            if a.name not in _TOPOLOGY and a.data_type in _KEY and a.domain in ('POINT', 'EDGE', 'CORNER', 'FACE')]


def _build(name, co, ev, lv, le, lt, source, values):
    """A new mesh from arrays; `values` {attribute name: array per element} with the types of `source`."""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(co)); me.edges.add(len(ev)); me.loops.add(len(lv)); me.polygons.add(len(lt))
    me.vertices.foreach_set("co", np.ascontiguousarray(co, np.float32).ravel())
    me.edges.foreach_set("vertices", np.ascontiguousarray(ev, np.int32).ravel())
    me.loops.foreach_set("vertex_index", np.ascontiguousarray(lv, np.int32))
    me.loops.foreach_set("edge_index", np.ascontiguousarray(le, np.int32))
    me.polygons.foreach_set("loop_start", np.concatenate(([0], np.cumsum(lt)[:-1])).astype(np.int32))
    me.polygons.foreach_set("loop_total", np.ascontiguousarray(lt, np.int32))
    for aname, domain, dtype in _attributes(source):
        a = me.attributes.get(aname) or me.attributes.new(aname, dtype, domain)
        v = values[aname]
        if len(v):
            a.data.foreach_set(_KEY[dtype], np.ascontiguousarray(v, _DTYPE[dtype]).ravel())
    for i, uv in enumerate(source.uv_layers):          # which UV map is active and which renders
        if uv.active and i < len(me.uv_layers):
            me.uv_layers.active_index = i
        if uv.active_render and i < len(me.uv_layers):
            me.uv_layers[i].active_render = True
    for m in source.materials:
        me.materials.append(m)
    for k in source.keys():
        me[k] = source[k]
    me.update()
    return me


def sub_mesh(me, faces, name):
    """A mesh of the given faces of `me` (indices, any order: they keep the order of `me`), with their vertices, edges
    and corners in the order of `me`. Returns (mesh, vertices, edges, faces) - the indices in `me`."""
    co, ev, lv, le, ls, lt = topology(me)
    faces = np.unique(np.asarray(faces, np.int64))
    loops = face_loops(ls, lt, faces)
    verts, edges = np.unique(lv[loops]), np.unique(le[loops])
    vmap = np.full(len(co), -1, np.int64); vmap[verts] = np.arange(len(verts))
    emap = np.full(len(ev), -1, np.int64); emap[edges] = np.arange(len(edges))
    pick = {'POINT': verts, 'EDGE': edges, 'CORNER': loops, 'FACE': faces}
    values = {n: attribute_values(me, n)[pick[d]] for n, d, _ in _attributes(me)}
    sub = _build(name, co[verts], vmap[ev[edges]], vmap[lv[loops]], emap[le[loops]], lt[faces], me, values)
    return sub, verts, edges, faces


def join(meshes, name, face_order=None):
    """One mesh of `meshes` (the attributes of the first, the same in all): vertices and edges mesh after mesh, the
    faces in `face_order` (indices into the faces of all meshes one after another; default: as they come).
    Returns (mesh, vertex offset of each mesh)."""
    tops = [topology(m) for m in meshes]
    voff = np.concatenate(([0], np.cumsum([len(t[0]) for t in tops])[:-1]))
    eoff = np.concatenate(([0], np.cumsum([len(t[1]) for t in tops])[:-1]))
    co = np.concatenate([t[0] for t in tops])
    ev = np.concatenate([t[1] + o for t, o in zip(tops, voff)])
    lv = np.concatenate([t[2] + o for t, o in zip(tops, voff)])
    le = np.concatenate([t[3] + o for t, o in zip(tops, eoff)])
    loff = np.concatenate(([0], np.cumsum([len(t[2]) for t in tops])[:-1]))
    ls = np.concatenate([t[4] + o for t, o in zip(tops, loff)])
    lt = np.concatenate([t[5] for t in tops])
    order = np.arange(len(lt)) if face_order is None else np.asarray(face_order, np.int64)
    loops = face_loops(ls, lt, order)
    values = {}
    for n, d, _ in _attributes(meshes[0]):
        v = np.concatenate([attribute_values(m, n) for m in meshes])
        values[n] = v[loops] if d == 'CORNER' else v[order] if d == 'FACE' else v
    return _build(name, co, ev, lv[loops], le[loops], lt[order], meshes[0], values), voff
