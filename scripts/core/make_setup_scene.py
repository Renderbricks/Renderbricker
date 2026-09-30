"""The Renderbricks setup scene of the add-on from a render scene (render settings, Physical Sky world,
camera): an empty scene with its render, Cycles, EEVEE and colour settings, its world (renamed
Renderbricks Sky) and its camera (direction and lens of the camera "Renderbricks") - nothing else.
The render scene itself is only read.

blender -b --factory-startup --python make_setup_scene.py -- <render scene.blend> [<out.blend>]
default out: addon/renderbricker/setup/renderbricks_setup.blend"""
import bpy, sys, importlib.util
import os
A = sys.argv[sys.argv.index("--") + 1:]
HERE = os.path.dirname(os.path.abspath(__file__))
src = A[0]
out = A[1] if len(A) > 1 else os.path.join(HERE, "..", "..", "addon", "renderbricker", "setup", "renderbricks_setup.blend")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "addon", "renderbricker"))
import rbcore as core
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
with bpy.data.libraries.load(src, link=False) as (s, d):
    d.scenes = s.scenes[:1]
tpl = d.scenes[0]
for attr in core.RENDER_STRUCTS:
    core.copy_props(getattr(tpl, attr), getattr(sc, attr))
sc.render.engine = tpl.render.engine
world, cam = tpl.world, tpl.camera
keep = {world, cam, cam.data if cam else None, sc}
if world and world.node_tree:
    keep.add(world.node_tree)
sc.world = world
world.name = "Renderbricks Sky"
if cam:
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.name = cam.data.name = "Renderbricks Setup Camera"
bpy.data.scenes.remove(tpl)
for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.node_groups,
             bpy.data.collections, bpy.data.textures, bpy.data.cameras, bpy.data.lights, bpy.data.worlds,
             bpy.data.curves, bpy.data.actions):
    for idb in list(coll):
        if idb not in keep:
            coll.remove(idb)
for l in list(bpy.data.libraries):
    bpy.data.libraries.remove(l)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
print("SETUP", sc.render.engine, sc.cycles.samples, sc.render.resolution_x, sc.render.resolution_y,
      sc.view_settings.view_transform, sc.view_settings.look, "world", sc.world.name, "camera", sc.camera and sc.camera.name,
      "objects", len(bpy.data.objects), "meshes", len(bpy.data.meshes), "images", len(bpy.data.images))
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out), compress=True)
if os.path.isfile(os.path.abspath(out) + "1"):      # Blender's backup of the previous setup scene
    os.remove(os.path.abspath(out) + "1")
print("WROTE", os.path.abspath(out))
