"""Size of a model for the memory estimate of the batch (run 45).

blender -b <import.blend> --python scan_model.py
Prints: SCAN max_faces <n> max_mesh <name> meshes <n> objects <n>
"""
import bpy

users = {}
for o in bpy.data.objects:
    if o.type == 'MESH' and o.data.polygons:
        users.setdefault(o.data, []).append(o)
big = max(users, key=lambda m: len(m.polygons)) if users else None
print(f"SCAN max_faces {len(big.polygons) if big else 0} max_mesh {big.name if big else '-'} "
      f"meshes {len(users)} objects {sum(len(v) for v in users.values())}")
