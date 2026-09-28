"""Import a Mecabricks .zmbx with the installed "Mecabricks Advanced" add-on and save it.

Usage (use the Blender version the add-on is installed for, here 5.2.2):
  blender -b --factory-startup --python import_zmbx.py -- <file.zmbx> <target.blend> [--scale 0.001]
Default import settings: logos on, no bevels, scale 1 (as the earlier imports).
"""
import bpy, addon_utils, sys

A = sys.argv[sys.argv.index("--") + 1:]
src, target = A[:2]
SCALE = float(A[A.index("--scale") + 1]) if "--scale" in A else 1.0     # 0.001: metric (1 unit = 1 m)

mod = addon_utils.enable("mecabricks advanced", default_set=True)
print("ADDON", mod and mod.bl_info.get("name"), mod and mod.bl_info.get("version"))

for ob in list(bpy.data.objects):          # empty scene, like the earlier imports
    bpy.data.objects.remove(ob)

res = bpy.ops.import_mecabricks.zmbx(filepath=src, setting_logos=True, setting_local=False,
                                     setting_bevels=False, setting_scale=SCALE)
print("IMPORT", res)
for ob in bpy.data.objects:
    print("OBJ", ob.name, ob.type, ob.data.name if ob.data else None,
          len(ob.data.polygons) if ob.type == 'MESH' else "")
bpy.ops.wm.save_as_mainfile(filepath=target)
print("SAVED", target)
