"""The run without a window: blender -b scene.blend --python rbcore/run.py -- result.blend [options]."""
import bpy
from . import cache as cache_mod, camera, config, copies, memory, workers


def main():
    if "--merge-cache" in config.args:     # helper Blender of write_cache (run 62)
        cache_mod._merge_cache(config.args[config.args.index("--merge-cache") + 1])
        return
    users = {}
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data.polygons and not copies.is_master(ob):
            users.setdefault(copies.original_of(ob.data), []).append(ob)
    # progress for a console (headless run from the add-on, run 57): mesh i / n, weighted by
    # faces, time left
    weight = {me: len(me.polygons) + 50 for me in users}
    total_w = sum(weight.values()) or 1
    if "--worker" in config.args:          # one share of a parallel headless run (run 59)
        import os, json
        k = config.args.index("--worker")
        i, n, out_blend, out_json = int(config.args[k + 1]), int(config.args[k + 2]), config.args[k + 3], config.args[k + 4]
        if os.environ.get("RENDERBRICKER_TEST_SHORT_WORKER") == str(i):     # CI: this worker has no memory
            memory.FREE_OVERRIDE[0] = 0.0
        if "--share" in config.args:       # only the meshes of this worker, from the scene file (run 119)
            share = json.load(open(config.args[config.args.index("--share") + 1], encoding="utf-8"))
            users, weight, total_w = workers.load_share(config.args[config.args.index("--source") + 1], share)
            pick = list(users)
        else:                       # the whole scene was opened (before run 119)
            if "--meshes" in config.args:      # Apply on a selection: only these meshes
                keep = set(json.load(open(config.args[config.args.index("--meshes") + 1], encoding="utf-8")))
                users = {me: obs for me, obs in users.items() if me.name in keep}
            part = workers._assign(users, weight, n)
            pick = [me for me in users if part[me.name] == i]
        # the copies are written in batches and freed (run 61): kept to the end, 8 workers on
        # Dungeon (3.4 M faces) used up the memory and skipped 236 meshes
        pending, batch = [], [0]

        def flush():
            names = set(pending)
            copies = {m for m in bpy.data.meshes if m.get("rb_original") in names}
            if copies:
                for m in copies:    # written without materials: appending hundreds of materials,
                    for j in range(len(m.materials)):   # images and node groups took 479 s for
                        m.materials[j] = None           # NINJAGO (run 59); the slots stay (run 66)
                base = os.path.splitext(out_blend)[0]
                bpy.data.libraries.write(f"{base}_b{batch[0]:03d}.blend", copies, fake_user=False)
                batch[0] += 1
                for me in [m for m in users if m.name in names]:
                    for ob in users[me]:
                        ob.data = me
                for m in copies:
                    bpy.data.meshes.remove(m)
            pending.clear()

        def after(me):
            pending.append(me.name)
            if sum(len(m.polygons) for m in bpy.data.meshes if m.get("rb_original") in set(pending)) >= workers.FLUSH_FACES:
                flush()

        loaded = memory.process_memory_gb()
        if "--ledger" in config.args:      # large parts only when the ledger has room for them (run 121)
            _s, _f, reps = workers._run_worker_meshes(users, pick, weight, memory.MemoryLedger(config.args[config.args.index("--ledger") + 1]),
                                              after=after, flush=flush)
        else:                       # a segment (run 124)
            _s, _f, reps = workers._run_meshes(users, pick, weight, total_w, False, wait=workers.WORKER_WAIT, after=after,
                                       flush=flush)
        flush()
        peak = memory.process_memory_gb(peak=True)
        if peak is not None:            # for the log and the estimate of the next run
            print(f"PEAK worker {i}: {peak:.2f} GB (scene loaded {loaded or 0:.2f} GB, {len(pick)} meshes)", flush=True)
        json.dump(reps, open(out_json, "w", encoding="utf-8"), default=str)     # written last: worker done
        return
    if workers.LOG:
        import datetime
        try:
            with open(workers.LOG, "a", encoding="utf-8") as fh:
                fh.write(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  Convert headless  "
                         f"(Blender {bpy.app.version_string})\nscene: {bpy.data.filepath}\nresult: {config.TARGET}\n"
                         f"settings: viewport {config.VIEW_LEVEL}, render {config.RENDER_LEVEL}, variant "
                         f"{'A' if config.SHADING == 'mecabricks' else 'B'}\n")
        except OSError:
            pass
    workers.say(f"MESHES {len(users)}")      # for the progress line of the batch scripts
    clean = workers.clean_for_workers(users) if config.TARGET else False
    if clean:
        workers.say("CLEAN the previous conversion was removed from the working copy - it is made again")
    jobs = memory.resolve_jobs(config.opt("--jobs", "1"), len(users), list(users)) if bpy.data.filepath else 1
    if memory.LAST_MEMORY_PLAN[0] and config.opt("--jobs", "1") == "auto":
        workers.say(f"MEMORY {memory.LAST_MEMORY_PLAN[0]}")
    if jobs > 1:
        scene_path = None
        if clean:                   # the workers open the cleaned scene, not the file on disk
            import os, tempfile
            scene_path = os.path.join(tempfile.gettempdir(), f"rb_clean_{os.getpid()}.blend")
            bpy.ops.wm.save_as_mainfile(filepath=scene_path, copy=True, relative_remap=True, compress=False)
        try:
            skipped, failed = workers._parallel(users, weight, total_w, jobs, scene_path)
        finally:
            if scene_path:
                try:
                    os.remove(scene_path)
                except OSError:
                    pass
    else:
        skipped, failed, _r = workers._run_meshes(users, list(users), weight, total_w, True)
    if skipped:
        workers.say(f"SKIPPED for memory: {len(skipped)} meshes ({', '.join(skipped[:5])}) - close other programs and run again")
    if failed:
        workers.say(f"Errors in {len(failed)} meshes ({', '.join(failed)}) - left as imported")
    if "--setup" in config.args:            # headless, scene never set up: the result gets the render camera
        workers.say("CAMERA " + camera.render_camera_on(bpy.context.scene, config.opt("--setup", "")))
    cache = config.opt("--cache", "")
    pending = any(m.get("rb_original") and m.library is None and m.override_library is None for m in bpy.data.meshes)
    if cache and (cache_mod.CACHE_WRITTEN[0] is None or pending):   # not yet (all) by the workers' merge
        import time
        t_c = time.time()
        n = cache_mod.write_cache(cache)
        workers.say(f"CACHE {n} copies in {cache} ({time.time() - t_c:.0f} s)")
    if config.TARGET:
        import time
        t_s = time.time()
        bpy.ops.wm.save_as_mainfile(filepath=config.TARGET, copy=True, compress=True)   # copies are large (run 38)
        workers.say(f"SAVED {config.TARGET} ({time.time() - t_s:.0f} s)")
    if workers.LOG:
        try:
            with open(workers.LOG, "a", encoding="utf-8") as fh:
                fh.write("\n")
        except OSError:
            pass
