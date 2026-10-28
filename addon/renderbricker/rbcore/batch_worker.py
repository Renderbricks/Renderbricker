"""One batch baked in a background Blender (batchpool.py): the settings of the Blender that sent it, the batch mesh,
welding._bake_weld, the copies and the report written back.
blender -b --factory-startup --python batch_worker.py -- <in.blend> <out.blend> <settings.json> <mesh name>"""
import importlib
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
PKG = os.path.basename(HERE)


def plain(value):
    """A report value as JSON (numpy numbers and arrays included)."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    return value


def main():
    src, out, settings_path, name = sys.argv[sys.argv.index("--") + 1:][:4]
    with open(settings_path, encoding="utf-8") as fh:
        info = json.load(fh)
    for key, value in info["settings"].items():          # the sending Blender's settings and pins
        short, attr = key.rsplit(".", 1)
        mod = importlib.import_module(PKG + ("." + short if short else ""))
        old = getattr(mod, attr, None)
        if isinstance(old, list) and isinstance(value, list):
            old[:] = value                               # pins are lists other modules hold on to
        elif not isinstance(old, tuple) or not isinstance(value, list):
            setattr(mod, attr, value)
        else:
            setattr(mod, attr, tuple(value))
    welding = importlib.import_module(PKG + ".welding")
    with bpy.data.libraries.load(src, link=False) as (_s, dst):
        dst.meshes = [name]
    sub = dst.meshes[0]
    made, rep = welding._bake_weld(sub, set(info["levels"]))
    names = {str(lv): cp.name for lv, cp in made.items()}
    bpy.data.libraries.write(out, set(made.values()), fake_user=True)
    with open(out[:-len(".blend")] + ".json", "w", encoding="utf-8") as fh:
        json.dump({"copies": names, "report": plain(rep)}, fh)
    print("BATCH DONE", name, names, flush=True)


main()
