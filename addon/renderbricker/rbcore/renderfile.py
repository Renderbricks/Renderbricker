"""The render scene: <scene>_render.blend, complete without the add-on and without the cache file."""
import bpy
from . import cache, config, copies


# ---------------------------------------------------------------- render scene (UPDATES #25)
# A scene with a cache file needs the add-on to look right: the copies in the cache have empty
# material slots (the add-on puts the materials on them after loading), and only the add-on
# switches the parts to the render level for a render. On a computer without it - a render farm -
# the scene opened without materials and rendered the viewport level (run 251). The render scene
# is a second file for such computers: every converted part on its render copy, the copies taken
# into the file with the materials on the mesh, nothing linked. It is built by a helper Blender
# from a copy of the open scene, so the open scene, its file and its cache stay as they are.
RENDER_SCENE_MARK = "rb_render_scene"        # on the scenes of a render scene: the name of the file it was made from


def render_scene_path(blend):
    """<scene>_render.blend next to the scene."""
    import os
    return os.path.splitext(blend)[0] + "_render.blend"


def render_scene_steps():
    """Generator (as write_cache_steps): yields (fraction, text[, waiting]) and returns
    {"path", "size", "objects", "copies"}. Writes a copy of the open scene as it is now (unsaved
    changes included), lets a helper Blender turn it into the render scene and removes the copy.
    Closing the generator (Esc) stops the helper and leaves no working files."""
    import json, os, queue, subprocess, threading
    blend = bpy.data.filepath
    if not blend:
        raise RuntimeError("save the scene first - the render scene is written next to it")
    st = cache.cache_state()
    if st is not None and not st[3]:
        raise RuntimeError(f"the cache file {os.path.basename(st[1])} is missing - Apply again to rebuild it")
    out = render_scene_path(blend)
    tmp = os.path.splitext(out)[0] + ".writing.blend"
    leftovers = (tmp, tmp + "1")

    def clean(files):
        for f in files:
            try:
                os.remove(f)
            except OSError:
                pass

    yield (0.0, "preparing the render scene")
    clean(leftovers)                       # of a run that crashed: no .blend1 of it either
    proc = None
    try:
        bpy.ops.wm.save_as_mainfile(filepath=tmp, copy=True, relative_remap=True, compress=False)
        # size of the result, estimated: about the cache file (both levels, compressed), without a
        # cache a quarter of the uncompressed copy
        est = max(1.0, os.path.getsize(st[1]) if st is not None else 0.25 * os.path.getsize(tmp))
        proc = subprocess.Popen([bpy.app.binary_path, "-b", "--factory-startup", tmp, "--python", config.ENTRY, "--",
                                 "--render-scene", out, os.path.basename(blend)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        q, tail, state = queue.Queue(), [], {"frac": 0.0, "text": "opening a copy of the scene"}
        reader = threading.Thread(target=lambda: [q.put(x) for x in proc.stdout], daemon=True)
        reader.start()

        def drain():
            while not q.empty():
                line = q.get()
                tail.append(line)
                del tail[:-40]
                if line.startswith("RENDERSCENE DONE "):
                    state["done"] = json.loads(line[17:])
                elif line.startswith("RENDERSCENE FAILED "):
                    state["fail"] = line[19:].strip()
                elif line.startswith("RENDERSCENE "):
                    _tag, frac, text = line.rstrip().split(" ", 2)
                    state["frac"], state["text"] = float(frac), text

        while proc.poll() is None:
            drain()
            size = os.path.getsize(out + "@") if os.path.exists(out + "@") else 0     # Blender writes <file>@ first
            if size:
                yield (0.7 + 0.3 * min(0.98, size / est), f"writing the render scene {size / 1e9:.2f} GB", True)
            else:
                yield (0.02 + 0.68 * state["frac"], state["text"], True)
        reader.join(10)
        drain()
        if "done" not in state:
            raise RuntimeError(state.get("fail") or "the render scene was not written: " + "".join(tail)[-400:].strip())
        return dict(state["done"], path=out, size=os.path.getsize(out))
    finally:
        if proc is not None and proc.poll() is None:        # stopped (Esc): the helper ends, nothing half-written stays
            proc.kill()
            proc.wait()
            clean((out + "@",))
        clean(leftovers)


def _build_render_scene(out, source):
    """Helper Blender of render_scene_steps: the opened copy of the scene becomes the render scene and is
    saved as `out`. Prints 'RENDERSCENE <fraction> <text>' lines, at the end 'RENDERSCENE DONE {json}' or
    'RENDERSCENE FAILED <reason>'. No add-on runs here: the copies of the cache have no materials until
    embed_cache_steps gives the new meshes those of their originals."""
    import json, time

    def say(frac, text):
        print(f"RENDERSCENE {frac:.3f} {text}", flush=True)

    def gone(me):
        ovr = me.override_library
        return getattr(me, "is_missing", False) or (ovr is not None and (
            ovr.reference is None or getattr(ovr.reference, "is_missing", False)))

    obs = [o for o in bpy.data.objects if o.library is None and o.type == 'MESH' and o.data is not None]
    if any(gone(m) for m in bpy.data.meshes if m.get("rb_original")):
        print("RENDERSCENE FAILED the cache file was not found next to the scene", flush=True)
        return
    for ob, rc in copies.render_targets(obs):
        ob.data = rc
    say(0.05, "taking the parts into the render scene")
    gen, last = cache.embed_cache_steps(), time.time()
    try:
        while True:
            frac, text = next(gen)[:2]
            if time.time() - last >= 0.5:
                say(0.05 + 0.85 * frac, text.replace("into the scene", "into the render scene"))
                last = time.time()
    except StopIteration:
        pass
    # only what the render shows stays: the viewport copies nothing uses any more go, the render copy
    # is the copy of both levels (as with viewport level = render level)
    used = {o.data for o in bpy.data.objects if o.type == 'MESH' and o.data is not None}
    n_copies = 0
    for orig in [m for m in bpy.data.meshes if m.library is None and not m.get("rb_original")]:
        cps = copies.all_copies(orig)
        if not cps:
            continue
        rc = copies.copy_of(orig, "render")
        for cp in cps:
            if cp != rc and cp not in used:
                bpy.data.meshes.remove(cp)
            else:
                n_copies += 1
        if rc is not None and copies.copy_of(orig, "view") is None:
            orig["rb_view"] = rc.name
    for sc in bpy.data.scenes:
        sc[RENDER_SCENE_MARK] = source
    say(1.0, "writing the render scene")
    bpy.context.preferences.filepaths.save_version = 0          # no .blend1 of an earlier render scene
    bpy.ops.wm.save_as_mainfile(filepath=out, copy=True, compress=True)      # copies are large (run 38)
    n_obs = sum(1 for o in obs if o.data is not None and o.data.get("rb_original"))
    print("RENDERSCENE DONE " + json.dumps({"objects": n_obs, "copies": n_copies}), flush=True)
