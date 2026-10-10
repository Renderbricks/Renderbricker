"""The run without a window: blender -b scene.blend --python rbcore/run.py -- result.blend [options].

One entry, four roles - main() picks the role from the options:
  --merge-cache <job>             helper Blender of cache.write_cache_steps: joins the parts of a cache file
  --render-scene <out> <blend>    helper Blender of renderfile.render_scene_steps
  --worker <i> <n> <blend> <json> one share of a parallel conversion (_worker)
  none of these                   the parent (_parent): converts alone or starts workers, writes the cache file,
                                  saves the result"""
import bpy, datetime, json, os, tempfile, time
from . import cache as cache_mod, camera, config, copies, memory, renderfile, workers


def _copies_outside(users):
    """Whether copies are held outside the scope (--objects): copies of meshes not converted now, or objects outside
    showing a copy. Then the previous conversion is not removed first (workers.clean_for_workers) - they keep theirs."""
    if "--objects" not in config.args:
        return False
    inside = {o for obs in users.values() for o in obs}
    if any(m.get("rb_original") and copies.original_of(m) not in users for m in bpy.data.meshes):
        return True
    return any(o.type == 'MESH' and o.data is not None and o.data.get("rb_original") and o not in inside
               for o in bpy.data.objects)


def main():
    if "--merge-cache" in config.args:     # helper Blender of write_cache (run 62)
        cache_mod._merge_cache(config.args[config.args.index("--merge-cache") + 1])
        return
    if "--render-scene" in config.args:    # helper Blender of render_scene_steps (UPDATES #25)
        k = config.args.index("--render-scene")
        renderfile._build_render_scene(config.args[k + 1], config.args[k + 2])
        return
    users = _users_in_scope()
    # progress for a console (headless run from the add-on, run 57): mesh i / n, weighted by
    # faces, time left
    weight = {me: len(me.polygons) + 50 for me in users}
    total_w = sum(weight.values()) or 1
    if "--worker" in config.args:          # one share of a parallel headless run (run 59)
        _worker(users, weight, total_w)
        return
    _parent(users, weight, total_w)


def _users_in_scope():
    """{original mesh: its objects} of the opened scene - all parts, or the objects named by --objects."""
    users = {}
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data.polygons and not copies.is_master(ob):
            users.setdefault(copies.original_of(ob.data), []).append(ob)
    if "--objects" in config.args:         # scope Selected / Collection of the panel (UPDATES #24): only these objects
        keep = set(json.load(open(config.opt("--objects", ""), encoding="utf-8")))
        users = {me: [o for o in obs if o.name in keep] for me, obs in users.items()}
        users = {me: obs for me, obs in users.items() if obs}
    return users


def _worker(users, weight, total_w):
    """The worker role: converts the meshes of its share, writes the copies in batches next to <blend> and frees
    them, and writes the reports to <json> last - that file tells the parent the worker is done."""
    k = config.args.index("--worker")
    i, n, out_blend, out_json = int(config.args[k + 1]), int(config.args[k + 2]), config.args[k + 3], config.args[k + 4]
    if os.environ.get("RENDERBRICKER_TEST_SHORT_WORKER") == str(i):     # CI: this worker has no memory
        memory.FREE_OVERRIDE[0] = 0.0
    users, weight, total_w, pick = _worker_share(i, n, users, weight, total_w)
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


def _worker_share(i, n, users, weight, total_w):
    """What worker i of n converts: (users, weight, total weight, meshes to convert)."""
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
    return users, weight, total_w, pick


def _parent(users, weight, total_w):
    """The parent role, in the order a user reads it in the console and the log: head of the log, conversion,
    what was left out, result files."""
    _log(f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  Convert headless  "
         f"(Blender {bpy.app.version_string})\nscene: {bpy.data.filepath}\nresult: {config.TARGET}\n"
         f"settings: viewport {config.VIEW_LEVEL}, render {config.RENDER_LEVEL}, variant "
         f"{'A' if config.SHADING == 'mecabricks' else 'B'}\n")
    skipped, failed = _convert(users, weight, total_w)
    if skipped:
        workers.say(f"SKIPPED for memory: {len(skipped)} meshes ({', '.join(skipped[:5])}) - close other programs and run again")
    if failed:
        workers.say(f"Errors in {len(failed)} meshes ({', '.join(failed)}) - left as imported")
    _write_result()
    _log("\n")


def _log(text):
    """Append to the log file of the run (workers.LOG), if there is one."""
    if workers.LOG:
        try:
            with open(workers.LOG, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass


def _convert(users, weight, total_w):
    """Convert the meshes - alone or on worker Blenders, as memory.resolve_jobs decides. Returns (meshes skipped
    for memory, meshes with an error)."""
    workers.say(f"MESHES {len(users)}")      # for the progress line of the batch scripts
    clean = workers.clean_for_workers(users) if config.TARGET and not _copies_outside(users) else False
    if clean:
        workers.say("CLEAN the previous conversion was removed from the working copy - it is made again")
    jobs = memory.resolve_jobs(config.opt("--jobs", "1"), len(users), list(users)) if bpy.data.filepath else 1
    if memory.LAST_MEMORY_PLAN[0] and config.opt("--jobs", "1") == "auto":
        workers.say(f"MEMORY {memory.LAST_MEMORY_PLAN[0]}")
    if jobs > 1:
        scene_path = None
        if clean:                   # the workers open the cleaned scene, not the file on disk
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
    return skipped, failed


def _write_result():
    """After the conversion: the render camera (--setup), the cache file (--cache), the result scene (TARGET)."""
    if "--setup" in config.args:            # headless, scene never set up: the result gets the render camera
        workers.say("CAMERA " + camera.render_camera_on(bpy.context.scene, config.opt("--setup", "")))
    cache = config.opt("--cache", "")
    pending = any(m.get("rb_original") and m.library is None and m.override_library is None for m in bpy.data.meshes)
    if cache and (cache_mod.CACHE_WRITTEN[0] is None or pending):   # not yet (all) by the workers' merge
        t_c = time.time()
        n = cache_mod.write_cache(cache)
        workers.say(f"CACHE {n} copies in {cache} ({time.time() - t_c:.0f} s)")
    if config.TARGET:
        t_s = time.time()
        bpy.ops.wm.save_as_mainfile(filepath=config.TARGET, copy=True, compress=True)   # copies are large (run 38)
        workers.say(f"SAVED {config.TARGET} ({time.time() - t_s:.0f} s)")
