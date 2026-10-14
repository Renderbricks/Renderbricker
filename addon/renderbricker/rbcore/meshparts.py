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
# (the exact C types: foreach_get / foreach_set copy a buffer of the attribute's own type at once and go value by
# value otherwise - run 287, a copy of 10.3 M faces: custom normals 2.4 s as int32, 0.009 s as int16)
_DTYPE = {'FLOAT': np.float32, 'INT': np.int32, 'INT8': np.int8, 'BOOLEAN': bool, 'FLOAT_VECTOR': np.float32,
          'FLOAT2': np.float32, 'INT16_2D': np.int16, 'INT32_2D': np.int32, 'FLOAT_COLOR': np.float32,
          'BYTE_COLOR': np.float32, 'QUATERNION': np.float32, 'FLOAT4X4': np.float32}
# topology and positions are read and written as these attributes (positions: 0.011 s against 1.3 s through
# vertices.co for 10.3 M faces)
_TOPOLOGY = {'position', '.edge_verts', '.corner_vert', '.corner_edge'}


def _read(me, name, n, width, dtype):
    v = np.empty(n * width, dtype)
    if n:
        me.attributes[name].data.foreach_get("vector" if name == "position" else "value", v)
    return v


def topology(me):
    """Positions, edge vertices, corner vertices and edges, face starts and sizes as arrays."""
    nv, ne, nl, nf = len(me.vertices), len(me.edges), len(me.loops), len(me.polygons)
    co = _read(me, "position", nv, 3, np.float32)
    ev = _read(me, ".edge_verts", ne, 2, np.int32).astype(np.int64)
    lv = _read(me, ".corner_vert", nl, 1, np.int32).astype(np.int64)
    le = _read(me, ".corner_edge", nl, 1, np.int32).astype(np.int64)
    ls = np.empty(nf, np.int32); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(nf, np.int32); me.polygons.foreach_get("loop_total", lt)
    return co.reshape(-1, 3), ev.reshape(-1, 2), lv, le, ls.astype(np.int64), lt.astype(np.int64)


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


def _build(name, co, ev, lv, le, lt, source, values, attrs=None, into=None):
    """A new mesh from arrays; `values` {attribute name: array per element} for `attrs` [(name, domain, type)]
    (default: the attributes of `source`); UV roles, materials and custom properties from `source`. With `into`:
    that mesh gets the geometry instead (its own materials and custom properties stay)."""
    me = into if into is not None else bpy.data.meshes.new(name)
    me.vertices.add(len(co)); me.edges.add(len(ev)); me.loops.add(len(lv)); me.polygons.add(len(lt))
    if len(co):
        me.attributes["position"].data.foreach_set("vector", np.ascontiguousarray(co, np.float32).ravel())
    if len(ev):
        me.attributes[".edge_verts"].data.foreach_set("value", np.ascontiguousarray(ev, np.int32).ravel())
    if len(lv):
        me.attributes[".corner_vert"].data.foreach_set("value", np.ascontiguousarray(lv, np.int32))
        me.attributes[".corner_edge"].data.foreach_set("value", np.ascontiguousarray(le, np.int32))
    me.polygons.foreach_set("loop_start", np.concatenate(([0], np.cumsum(lt)[:-1])).astype(np.int32))
    me.polygons.foreach_set("loop_total", np.ascontiguousarray(lt, np.int32))
    for aname, domain, dtype in (attrs if attrs is not None else _attributes(source)):
        a = me.attributes.get(aname) or me.attributes.new(aname, dtype, domain)
        v = values[aname]
        if len(v):
            a.data.foreach_set(_KEY[dtype], np.ascontiguousarray(v, _DTYPE[dtype]).ravel())
    for i, uv in enumerate(source.uv_layers):          # which UV map is active and which renders
        if uv.active and i < len(me.uv_layers):
            me.uv_layers.active_index = i
        if uv.active_render and i < len(me.uv_layers):
            me.uv_layers[i].active_render = True
    if into is None:
        for m in source.materials:
            me.materials.append(m)
        for k in source.keys():
            me[k] = source[k]
    me.update()
    return me


def assign(dst, src):
    """The geometry of `src` - vertices, edges, faces, corners, every attribute - in the mesh `dst`, which keeps its
    name, users, materials and custom properties (bevel.bevel_copy works in place)."""
    co, ev, lv, le, ls, lt = topology(src)
    attrs = _attributes(src)
    values = {n: attribute_values(src, n) for n, _d, _t in attrs}
    dst.clear_geometry()
    for a in [a.name for a in dst.attributes if a.name not in _TOPOLOGY and not a.is_required]:
        try:
            dst.attributes.remove(dst.attributes[a])
        except (RuntimeError, KeyError):
            pass
    _build(dst.name, co, ev, lv, le, lt, src, values, attrs, into=dst)


def mesh_arrays(me):
    """A mesh as arrays: {"co", "ev", "lv", "le", "lt"; "attrs": {name: (domain, type, values)}} - what join_arrays
    builds a mesh of again."""
    co, ev, lv, le, _ls, lt = topology(me)
    return {"co": co, "ev": ev, "lv": lv, "le": le, "lt": lt,
            "attrs": {n: (d, t, attribute_values(me, n)) for n, d, t in _attributes(me)}}


def select_arrays(arr, faces):
    """The arrays of some faces of `arr` (indices, any order: they keep their order), with their vertices, edges and
    corners in the order of `arr`. Also returns (vertices, edges, faces) - the indices in `arr`."""
    lt = arr["lt"]
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    faces = np.unique(np.asarray(faces, np.int64))
    loops = face_loops(ls, lt, faces)
    verts, edges = np.unique(arr["lv"][loops]), np.unique(arr["le"][loops])
    vmap = np.full(len(arr["co"]), -1, np.int64); vmap[verts] = np.arange(len(verts))
    emap = np.full(len(arr["ev"]), -1, np.int64); emap[edges] = np.arange(len(edges))
    pick = {'POINT': verts, 'EDGE': edges, 'CORNER': loops, 'FACE': faces}
    out = {"co": arr["co"][verts], "ev": vmap[arr["ev"][edges]], "lv": vmap[arr["lv"][loops]],
           "le": emap[arr["le"][loops]], "lt": lt[faces],
           "attrs": {n: (d, t, v[pick[d]]) for n, (d, t, v) in arr["attrs"].items()}}
    return out, verts, edges, faces


def join_arrays(parts, name, source, face_order=None, drop=()):
    """One mesh of the array parts (mesh_arrays): vertices and edges part after part, the faces in `face_order`
    (indices into the faces of all parts one after another; default: as they come). Every attribute any part has
    (but those in `drop`); where a part lacks one (a batch without a bevelled edge has no selection layer of the
    bevel), its elements get zeros. UV roles, materials and custom properties from the mesh `source`.
    Returns (mesh, vertex offset of each part)."""
    nv = [len(p["co"]) for p in parts]
    voff = np.concatenate(([0], np.cumsum(nv)[:-1])).astype(np.int64)
    eoff = np.concatenate(([0], np.cumsum([len(p["ev"]) for p in parts])[:-1])).astype(np.int64)
    co = np.concatenate([p["co"] for p in parts])
    ev = np.concatenate([p["ev"] + o for p, o in zip(parts, voff)])
    lv = np.concatenate([p["lv"] + o for p, o in zip(parts, voff)])
    le = np.concatenate([p["le"] + o for p, o in zip(parts, eoff)])
    lt = np.concatenate([p["lt"] for p in parts])
    ls = np.concatenate(([0], np.cumsum(lt)[:-1]))
    order = np.arange(len(lt)) if face_order is None else np.asarray(face_order, np.int64)
    loops = face_loops(ls, lt, order)
    attrs = []
    for p in parts:
        attrs += [(n, d, t) for n, (d, t, _v) in p["attrs"].items() if n not in drop and n not in {x[0] for x in attrs}]
    values = {}
    for n, d, dtype in attrs:
        size = {'POINT': "co", 'EDGE': "ev", 'CORNER': "lv", 'FACE': "lt"}[d]
        v = np.concatenate([p["attrs"][n][2] if n in p["attrs"] else np.zeros((len(p[size]), _WIDTH[dtype]), _DTYPE[dtype])
                            for p in parts])
        values[n] = v[loops] if d == 'CORNER' else v[order] if d == 'FACE' else v
    return _build(name, co, ev, lv[loops], le[loops], lt[order], source, values, attrs), voff


def build_arrays(arr, name, source):
    """A new mesh of the arrays `arr` (UV roles, materials and custom properties from the mesh `source`)."""
    return _build(name, arr["co"], arr["ev"], arr["lv"], arr["le"], arr["lt"], source,
                  {n: v for n, (_d, _t, v) in arr["attrs"].items()}, [(n, d, t) for n, (d, t, _v) in arr["attrs"].items()])


def sub_mesh(me, faces, name):
    """A mesh of the given faces of `me` (indices, any order: they keep the order of `me`), with their vertices, edges
    and corners in the order of `me`. Returns (mesh, vertices, edges, faces) - the indices in `me`."""
    arr, verts, edges, faces = select_arrays(mesh_arrays(me), faces)
    sub = _build(name, arr["co"], arr["ev"], arr["lv"], arr["le"], arr["lt"], me,
                 {n: v for n, (_d, _t, v) in arr["attrs"].items()})
    return sub, verts, edges, faces


def join(meshes, name, face_order=None):
    """One mesh of `meshes` (see join_arrays). Returns (mesh, vertex offset of each mesh)."""
    return join_arrays([mesh_arrays(m) for m in meshes], name, meshes[0], face_order)
