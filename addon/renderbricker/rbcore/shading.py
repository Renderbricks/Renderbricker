"""Geometric shading (variant B): the node groups that subdivide and shade smooth."""
import bpy
from . import config, creases


def subdiv_node_group():
    """Subdivision + smooth shading in one node modifier: one toggle, no driver
    (a driver reading the object's own modifier toggle forms a dependency cycle).
    The level lives on the Subdivision node itself (modifier inputs cannot be
    set from Python the same way in every Blender version)."""
    ng = bpy.data.node_groups.get("Mecabricks Subdiv")
    if ng is None:
        ng = bpy.data.node_groups.new("Mecabricks Subdiv", 'GeometryNodeTree')
        ng.is_modifier = True
        ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        N = ng.nodes
        gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
        sd = N.new("GeometryNodeSubdivisionSurface"); sd.name = "Subdivision"
        sd.inputs["Limit Surface"].default_value = True
        sd.inputs["Boundary Smooth"].default_value = 'All'
        sd.inputs["UV Smooth"].default_value = 'Keep Boundaries'
        ce, cv = N.new("GeometryNodeInputNamedAttribute"), N.new("GeometryNodeInputNamedAttribute")
        for node, name in ((ce, "crease_edge"), (cv, "crease_vert")):
            node.data_type = 'FLOAT'
            node.inputs["Name"].default_value = name
        ss = N.new("GeometryNodeSetShadeSmooth")
        ss.domain = 'FACE'
        ss.inputs["Shade Smooth"].default_value = True
        gi.location, ce.location, cv.location = (-500, 0), (-500, -180), (-500, -300)
        sd.location, ss.location, go.location = (-200, 0), (100, 0), (350, 0)
        L = ng.links
        L.new(gi.outputs["Geometry"], sd.inputs["Mesh"])
        L.new(ce.outputs["Attribute"], sd.inputs["Edge Crease"])
        L.new(cv.outputs["Attribute"], sd.inputs["Vertex Crease"])
        L.new(sd.outputs["Mesh"], ss.inputs[0])            # Set Shade Smooth: "Geometry" up to 4.5, "Mesh" from 5.0
        L.new(ss.outputs[0], go.inputs["Geometry"])
    bs = ng.nodes["Subdivision"].inputs["Boundary Smooth"]
    if bs.default_value != 'All':           # groups from before run 42 still say Keep Corners
        bs.default_value = 'All'
    lv = ng.nodes["Subdivision"].inputs["Level"]
    if lv.default_value != config.LEVELS:          # only on change: a touched node group
        lv.default_value = config.LEVELS           # re-evaluates every object using it
    return ng


def geometric_shading(ob, me, E):
    # creased edges become sharp too (imported sharp edges are kept); with every
    # face flat-flagged this leaves the imported custom normals untouched
    sharp = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", 'BOOLEAN', 'EDGE')
    vals = [False] * len(me.edges)
    sharp.data.foreach_get("value", vals)
    sharp.data.foreach_set("value", [v or (i in E) for i, v in enumerate(vals)])
    # run 45: the subdivision stays the Subdivision modifier (quality setting - the GN
    # Subdivision node has none, and variant B had seam gaps up to 0.018 at the freed
    # two-edge vertices); a small node group after it only shades smooth
    for name in ("Mecabricks Subdiv", "Smooth After Subdiv"):
        if ob.modifiers.get(name):
            ob.modifiers.remove(ob.modifiers[name])
    if ob.animation_data:
        for fc in list(ob.animation_data.drivers):
            ob.animation_data.drivers.remove(fc)
    creases.add_subsurf(ob)                          # custom normals off for variant B (SHADING)
    gmod = ob.modifiers.get("Mecabricks Smooth") or ob.modifiers.new("Mecabricks Smooth", 'NODES')
    gmod.node_group = smooth_node_group()


def smooth_node_group():
    """Variant B shading after the Subdivision modifier: every face smooth; sharp_edge
    (imported sharp edges + creased edges) keeps the creases crisp."""
    ng = bpy.data.node_groups.get("Mecabricks Smooth")
    if ng is None:
        ng = bpy.data.node_groups.new("Mecabricks Smooth", 'GeometryNodeTree')
        ng.is_modifier = True
        ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        gi, go = ng.nodes.new("NodeGroupInput"), ng.nodes.new("NodeGroupOutput")
        ss = ng.nodes.new("GeometryNodeSetShadeSmooth")
        ss.domain = 'FACE'
        ss.inputs["Shade Smooth"].default_value = True
        gi.location, ss.location, go.location = (-300, 0), (0, 0), (300, 0)
        # the geometry socket is the first one; it is called "Geometry" up to Blender 4.5 and
        # "Mesh" from 5.0 (CI, Blender 4.5.14: KeyError 'Mesh' in variant B)
        ng.links.new(gi.outputs[0], ss.inputs[0])
        ng.links.new(ss.outputs[0], go.inputs[0])
    return ng
