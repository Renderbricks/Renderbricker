"""The cache file next to the scene: write, link (library overrides), move, copy, embed, remove."""
import bpy, json, os, queue, shutil, subprocess, tempfile, threading, time, types
from . import config, copies, workscene


# ---------------------------------------------------------------- cache file (run 62)
# The copies are 20x the import (Dungeon: 2.7 GB file for a 152 MB import). With the cache they
# live in a .blend next to the scene, linked as a library (relative path): the scene file stays
# about as large as the import and saves fast; render memory stays one copy per mesh.
# Linked meshes are read-only and would bring their own copies of the materials, so the copies
# are written with empty material slots and the objects carry the materials of the original
# on object level (same materials, so Off / viewport 0 look unchanged). A linked mesh nobody
# uses is not kept when the scene is saved: the original holds it by an ID property.
CACHE_KEEP = "rb_keep_L"


CACHE_DEBUG = False


LINK_RATE = [80e6]        # bytes per second linking a cache file, measured on each link (run 70)


CACHE_WRITTEN = [None]    # copies the parallel run already put into the cache (run 66)


def cache_path_for(blend, tag=None):
    """<scene>_rbcache.blend next to the scene (run 62; the version belongs in the scene name,
    a cache belongs to exactly one scene file)."""
    return os.path.splitext(blend)[0] + "_rbcache.blend"


def cache_library():
    """The library the copies are linked from (None without a cache)."""
    for m in bpy.data.meshes:
        if m.library is not None and (m.get("rb_original") or m.name.rsplit(" L", 1)[-1].isdigit()):
            return m.library
    return None


def cache_state():
    """(library, its file, the file it should be next to the scene, file exists) or None."""
    lib = cache_library()
    if lib is None:
        return None
    cur = os.path.abspath(bpy.path.abspath(lib.filepath))
    want = os.path.abspath(cache_path_for(bpy.data.filepath)) if bpy.data.filepath else cur
    if os.path.normcase(cur) == os.path.normcase(want):
        want = cur                           # the same file: compared without case (Windows)
    return lib, cur, want, os.path.exists(cur)


def relink_cache(lib, path):
    """Point the cache library to `path` (relative to the scene) and read it again."""
    lib.filepath = bpy.path.relpath(path) if bpy.data.filepath else path
    lib.reload()
    override_materials()                 # the overrides lose their materials on a reload


def move_cache():
    """The cache file next to the scene under the scene's name, the link updated (run 63: after
    Save As under another name or in another folder). Returns (old path, new path)."""
    st = cache_state()
    if st is None:
        raise RuntimeError("no cache file linked")
    lib, cur, want, exists = st
    if cur == want:
        return cur, want
    if exists:
        if os.path.exists(want):
            os.remove(want)                  # the caller confirmed replacing it
        shutil.move(cur, want)               # want keeps the case of the scene name
    elif not os.path.exists(want):
        raise RuntimeError(f"cache file not found: {cur}")
    relink_cache(lib, want)
    return cur, want


def relink_cache_on_load():
    """After loading: the linked cache file is gone, but <scene>_rbcache.blend lies next to the
    scene (both moved or renamed in the Explorer) - link that one. Returns True if relinked."""
    st = cache_state()
    if st is None or st[3] or not bpy.data.filepath:
        return False
    if os.path.exists(st[2]):
        relink_cache(st[0], st[2])
        return True
    return False


def processed_originals():
    return [m for m in bpy.data.meshes if m.library is None and not m.get("rb_original")
            and (m.get("rb_view") or m.get("rb_render") or copies.all_copies(m))]


def _users_of(orig):
    return [o for o in bpy.data.objects if o.type == 'MESH' and o.data is not None
            and (o.data == orig or o.data.get("rb_original") == orig.name)]


def object_materials(ob, orig, on=True):
    """Materials of the original on the object's slots (on) or back on the mesh (off)."""
    for i, slot in enumerate(ob.material_slots):
        if on:
            mt = orig.materials[i] if i < len(orig.materials) else None
            slot.link = 'OBJECT'
            slot.material = mt
        elif slot.link == 'OBJECT':
            slot.material = None
            slot.link = 'DATA'


def run_steps(gen, wait=0.2):
    """Run a step generator to its end (headless, scripts); it yields (fraction, text[, waiting])
    and returns its result. waiting: nothing to do but wait for a helper process."""
    try:
        while True:
            st = next(gen)
            if len(st) > 2 and st[2]:
                time.sleep(wait)
    except StopIteration as e:
        return e.value


def write_cache(path, files=(), fresh=()):
    return run_steps(write_cache_steps(path, files, fresh))


def write_cache_steps(path, files=(), fresh=()):
    """Generator of write_cache (run 69): yields (fraction, text[, waiting]) between short pieces
    of work so the add-on can show a progress bar; the helper Blender runs in the background.
    files: .blend files with new copies (the workers' parts), fresh: their (original, level)
    keys - they go into the cache without being loaded into this file (run 66: loading 5,538
    copies into the open Dungeon took 134 s, writing them again 65 s).
    All copies in use (the viewport and render level of every processed mesh) into the cache
    at `path`, then linked back as library overrides. Returns the number of copies.
    The objects keep the materials on their mesh: the override of each copy carries the
    original's materials (with object-level materials Cycles stopped sharing a mesh between
    objects - Dungeon ran out of GPU memory, run 64/65). One pass over meshes and objects; copies
    of an earlier cache that stay are carried over by a helper Blender (run 62).

    The phases, each a function below, hand their results on in one namespace `c`:
    _index (read the scene) -> _objects_to_originals -> _sort_copies (new, to drop, to carry over)
    -> _write_file_steps (the file, next to its place) -> _remove_copies -> _link_steps (the file
    at its place, linked) -> _override_steps (overrides, materials, objects back on their copies)."""
    c = types.SimpleNamespace(path=path, files=files, tmp=path + ".writing", T=[time.time()])
    yield (0.0, "preparing the cache file")
    _index(c)
    _objects_to_originals(c)
    _mark(c, "objects to originals")
    _sort_copies(c, fresh)
    yield (0.05, "writing the cache file")
    yield from _write_file_steps(c)
    _mark(c, "write")
    yield (0.76, "writing the cache file")
    _remove_copies(c)
    _mark(c, "remove")
    if not c.names:
        return 0
    os.replace(c.tmp, path)
    refs_new = yield from _link_steps(c)
    _mark(c, "link")
    yield from _override_steps(c, refs_new)
    _mark(c, "overrides")
    return len(c.names)


def _mark(c, what):
    """Time of a phase of write_cache_steps for the console (CACHE_DEBUG)."""
    if CACHE_DEBUG:
        print(f"CACHETIME {what} {time.time() - c.T[0]:.1f} s", flush=True)
    c.T[0] = time.time()


def _level_of(name):
    """The level in the name of a copy ('3001 L2' -> 2), None without one."""
    tail = name.rsplit(" L", 1)[-1] if name else ""
    return int(tail) if tail.isdigit() else None


def _index(c):
    """Phase 1 of write_cache_steps: reads the scene, changes nothing. Adds copies_of {original name: its
    copies}, origs (the processed originals), users {original name: its objects}, shown {object name: the
    level it shows now} and want {original name: {'view' / 'render': level}}."""
    # indexes: copies and objects per original (local data-blocks; linked ones are references)
    copies_of, local = {}, {}
    for m in bpy.data.meshes:
        name = m.get("rb_original")
        if name:
            copies_of.setdefault(name, []).append(m)
        elif m.library is None:
            local[m.name] = m
    origs = [m for n, m in local.items() if n in copies_of or m.get("rb_view") or m.get("rb_render")]
    users = {orig.name: [] for orig in origs}
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data is not None:
            key = ob.data.get("rb_original") or ob.data.name
            if key in users and (ob.data.get("rb_original") or ob.data == local.get(key)):
                users[key].append(ob)
    # what every object shows now: its original (0) or a copy of a level - kept as it is
    shown = {ob.name: (int(ob.data["rb_level"]) if ob.data.get("rb_original") else
                       (-1 if ob.get("rb_show_view") else 0))
             for obs in users.values() for ob in obs}
    want = {}
    for orig in origs:
        want[orig.name] = {}
        for w in ("view", "render"):
            cp = copies.copy_of(orig, w)
            lv = int(cp["rb_level"]) if cp is not None else _level_of(orig.get(f"rb_{w}", ""))
            if lv:
                want[orig.name][w] = lv
    c.copies_of, c.origs, c.users, c.shown, c.want = copies_of, origs, users, shown, want


def _objects_to_originals(c):
    """Phase 2: every object back on its original with the materials on the mesh, the holds of an earlier
    cache released - from here to _override_steps the scene shows the originals."""
    origs, users = c.origs, c.users
    for orig in origs:
        for ob in users[orig.name]:
            object_materials(ob, orig, False)    # materials on the mesh (also 1.9.0/1.9.1 scenes)
            ob.data = orig
        for k in [k for k in orig.keys() if k.startswith(CACHE_KEEP)]:
            del orig[k]


def _sort_copies(c, fresh):
    """Phase 3: which copies go where. Adds new (baked here, to write), drop (local, of a level nobody wants),
    old (overrides and links of an earlier cache), carry {earlier cache file: names of the copies to take
    over} and names (every copy the new cache file holds). The new copies get their cache name and empty
    material slots."""
    copies_of, want = c.copies_of, c.want
    fresh = set(fresh)
    # new copies (local, baked here) to write; copies of an earlier cache (overrides or linked)
    # to carry over from their file
    new, drop, old = [], [], []
    for name, cps in copies_of.items():
        levels = set(want.get(name, {}).values())
        for cp in cps:
            if cp.library is None and cp.override_library is None:
                (new if int(cp.get("rb_level", 0)) in levels else drop).append(cp)
            else:
                old.append(cp)
    have_new = {(cp["rb_original"], int(cp["rb_level"])) for cp in new} | fresh
    carry, keys = {}, set(have_new)
    for cp in old:
        ref = cp.override_library.reference if cp.override_library is not None else cp
        if ref is None or ref.library is None or getattr(ref, "is_missing", False):
            continue
        key = (cp["rb_original"], int(cp["rb_level"]))
        if key not in keys and key[1] in set(want.get(key[0], {}).values()):
            keys.add(key)
            carry.setdefault(bpy.path.abspath(ref.library.filepath), []).append(ref.name)
    for cp in new:
        cp.name = f"{cp['rb_original']} L{int(cp['rb_level'])}"
        for i in range(len(cp.materials)):
            cp.materials[i] = None           # the overrides get the materials in this file
    names = ({cp.name for cp in new} | {n for ns in carry.values() for n in ns}
             | {f"{o} L{lv}" for o, lv in fresh})
    c.new, c.drop, c.old, c.carry, c.names = new, drop, old, carry, names


def _write_file_steps(c):
    """Phase 4 (generator): the cache file at c.tmp. New copies alone are written from this Blender in one
    call; with parts of workers (c.files) or copies to carry over, a helper Blender joins them in the
    background (headless --merge-cache) while this one yields the progress."""
    new, carry, files, tmp = c.new, c.carry, c.files, c.tmp
    # the compressed write is one call without progress (Dungeon 39 s, the text is on screen).
    # Tried in run 69: uncompressed to the temp folder + the helper compressing in the
    # background - progress all the way, but 82 s instead of 65 s: the direct call stays.
    if new and not carry and not files:
        bpy.data.libraries.write(tmp, set(new), fake_user=True, compress=True)   # one call, no progress inside
    elif new or carry or files:
        part = os.path.join(tempfile.gettempdir(), f"rb_cache_new_{os.getpid()}.blend")
        if new:
            bpy.data.libraries.write(part, set(new), fake_user=True, compress=False)
        job = os.path.join(tempfile.gettempdir(), f"rb_cache_job_{os.getpid()}.json")
        sources = ([part] if new else []) + list(files)
        json.dump({"out": tmp, "new": sources, "carry": carry}, open(job, "w", encoding="utf-8"))
        # size of the result, estimated: new parts are written uncompressed (~1/4 when
        # compressed), carried copies are a share of their compressed cache file
        est = 0.25 * sum(os.path.getsize(f) for f in sources if os.path.exists(f))
        for lib_path, ns in carry.items():
            n_lib = sum(1 for m in bpy.data.meshes if m.library is not None
                        and bpy.path.abspath(m.library.filepath) == lib_path) or len(ns)
            est += os.path.getsize(lib_path) * len(ns) / n_lib if os.path.exists(lib_path) else 0
        est = max(est, 1.0)
        n_src = len(sources) + len(carry)
        proc = subprocess.Popen([bpy.app.binary_path, "-b", "--factory-startup", "--python",
                                 config.ENTRY, "--", "--merge-cache", job],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        q, tail = queue.Queue(), []
        threading.Thread(target=lambda: [q.put(x) for x in proc.stdout], daemon=True).start()
        loaded = 0
        while proc.poll() is None or not q.empty():
            while not q.empty():
                line = q.get()
                tail.append(line)
                if line.startswith("MERGELOADED"):
                    loaded += 1
            size = max((os.path.getsize(f) for f in (tmp, tmp + "@") if os.path.exists(f)), default=0)
            if size:
                yield (0.35 + 0.4 * min(0.98, size / est), f"writing the cache file {size / 1e9:.2f} GB", True)
            else:
                yield (0.05 + 0.3 * loaded / max(1, n_src), f"joining the copies ({loaded}/{n_src} files)", True)
        for f in (part, job):
            if os.path.exists(f):
                os.remove(f)
        if not os.path.exists(tmp):
            raise RuntimeError("cache merge failed: " + "".join(tail)[-500:])


def _remove_copies(c):
    """Phase 5: the copies leave this file - they are in the cache file now, or nobody wants them - and with
    them the references and libraries of an earlier cache."""
    new, drop, old = c.new, c.drop, c.old
    refs = [cp.override_library.reference for cp in old if cp.override_library is not None
            and cp.override_library.reference is not None]
    gone = list({*drop, *new, *old, *refs})
    if gone:
        bpy.data.batch_remove(gone)
    cleanup_libraries()


def _link_steps(c):
    """Phase 6 (generator): the copies of the cache file at c.path linked into this file. Returns the linked
    meshes."""
    path, names = c.path, c.names
    # one call without progress: in portions every call reads the file again (Dungeon: all at
    # once 36 s, 12 portions 63 s, run 70) - instead an estimate from the size and the speed of
    # the last link on this computer
    size = os.path.getsize(path)
    est = size / LINK_RATE[0]
    yield (0.78, f"linking the cache file (about {est:.0f} s)" if est >= 3 else "linking the cache file")
    t_link = time.time()
    with bpy.data.libraries.load(path, link=True, relative=bpy.data.filepath != "") as (src, dst):
        dst.meshes = [n for n in src.meshes if n in names]
    if size > 50e6:
        LINK_RATE[0] = size / max(0.5, time.time() - t_link)
    return [r for r in dst.meshes if r is not None]


def _override_steps(c, refs_new):
    """Phase 7 (generator): a library override per linked copy; every original gets the materials on its
    copies, the hold on them (CACHE_KEEP) and their names (rb_view / rb_render), and its objects show
    again what they showed before (c.shown)."""
    origs, users, shown, want = c.origs, c.users, c.shown, c.want
    by_orig = {}
    for i, ref in enumerate(refs_new):
        ov = ref.override_create(remap_local_usages=False)     # one by one with remap: 192 s (run 65)
        if ov is None:          # 5.3: a linked mesh without a user counts as indirect - a user first (run 71)
            ref.use_fake_user = True
            ov = ref.override_create(remap_local_usages=False)
            ref.use_fake_user = False
        if ov is None:
            raise RuntimeError(f"Blender {bpy.app.version_string} made no override of {ref.name}")
        by_orig.setdefault(ov["rb_original"], {})[int(ov["rb_level"])] = ov
        if i % 200 == 0:
            yield (0.9 + 0.05 * i / len(refs_new), "linking the copies")
    for k, orig in enumerate(origs):
        if k % 200 == 0:
            yield (0.95 + 0.05 * k / max(1, len(origs)), "linking the copies")
        have = by_orig.get(orig.name, {})
        for lv, cp in have.items():
            for i, mt in enumerate(orig.materials):
                if i < len(cp.materials):
                    cp.materials[i] = mt
            orig[f"{CACHE_KEEP}{lv}"] = cp           # keeps the copy nobody shows in the file
        for w, lv in want[orig.name].items():
            if lv in have:
                orig[f"rb_{w}"] = have[lv].name
        view = have.get(want[orig.name].get("view"))
        for ob in users[orig.name]:
            lv = shown[ob.name]              # -1: new copies from the workers - the view copy
            ob.data = (have.get(lv) or view or orig) if lv else orig


def override_materials():
    """After loading: the overrides of the cache copies get the materials of their original on
    the mesh again (Blender records the change but does not apply it when loading, run 65).
    Returns the number of copies."""
    n = 0
    for me in bpy.data.meshes:
        if me.override_library is None or not me.get("rb_original"):
            continue
        orig = bpy.data.meshes.get((me["rb_original"], None))
        if orig is None:
            continue
        for i, mt in enumerate(orig.materials):
            if i < len(me.materials) and me.materials[i] != mt:
                me.materials[i] = mt
        n += 1
    return n


def _merge_cache(job):
    """Helper Blender of write_cache: new copies + the copies carried over from earlier cache
    files -> one cache file (in an empty file appending is fast)."""
    j = json.load(open(job, encoding="utf-8"))
    ids = []
    for f in ([j["new"]] if isinstance(j["new"], str) and j["new"] else j["new"] or []):
        with bpy.data.libraries.load(f, link=False) as (src, dst):
            dst.meshes = list(src.meshes)
        ids += [m for m in dst.meshes if m is not None]
        print("MERGELOADED", f, flush=True)
    for lib_path, names in j["carry"].items():
        with bpy.data.libraries.load(lib_path, link=False) as (src, dst):
            dst.meshes = [n for n in src.meshes if n in set(names)]
        ids += [m for m in dst.meshes if m is not None]
        print("MERGELOADED", lib_path, flush=True)
    bpy.data.libraries.write(j["out"], set(ids), fake_user=True, compress=True)
    print("MERGED", len(ids), flush=True)


def drop_cache_links(orig):
    """Remove: the objects take the materials from the mesh again, the cache hold is released."""
    for ob in _users_of(orig):
        object_materials(ob, orig, False)
    for k in [k for k in orig.keys() if k.startswith(CACHE_KEEP)]:
        del orig[k]


def uncache():
    """Cache off (run 64): objects whose mesh has only local copies take the materials from the
    mesh again (object-level materials stop Cycles from sharing meshes), the cache hold is
    released, unused cache libraries removed. Returns the number of objects changed."""
    cleanup_libraries()                  # references of copies an Apply replaced go first
    copies_of = {}
    for m in bpy.data.meshes:
        if m.get("rb_original"):
            copies_of.setdefault(m["rb_original"], []).append(m)
    n = 0
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.data is None or not any(sl.link == 'OBJECT' for sl in ob.material_slots):
            continue
        name = ob.data.get("rb_original") or ob.data.name
        orig = bpy.data.meshes.get((name, None))
        if orig is None or any(c.library or c.override_library for c in copies_of.get(name, [])):
            continue
        object_materials(ob, orig, False)
        n += 1
    for orig in [bpy.data.meshes.get((k, None)) for k in copies_of]:
        if orig is not None and not any(c.library or c.override_library for c in copies_of[orig.name]):
            for k in [k for k in orig.keys() if k.startswith(CACHE_KEEP)]:
                del orig[k]
    cleanup_libraries()
    return n


def embed_cache():
    return run_steps(embed_cache_steps())


def embed_cache_steps():
    """Generator of embed_cache (run 69): yields (fraction, text) after each copy.
    Cache off (run 68): the copies of the cache become ordinary data of this file again -
    each is written into a new mesh by a temporary object in a scene of its own (Dungeon's
    5,538: 14 s; make_local one by one took 310 s, and copy() of an override is an override
    again). Objects and materials as before, references and library removed. Returns the
    number of copies."""
    cached = [m for m in bpy.data.meshes if m.get("rb_original") and (m.override_library is not None or m.library is not None)
              and not getattr(m, "is_missing", False)]
    refs = {m.override_library.reference for m in cached if m.override_library is not None} - {None}
    cached = [m for m in cached if m not in refs]       # the overrides stand for their references
    if not cached:
        uncache()
        return 0
    work = workscene.work_object(cached[0])
    dg = workscene.depsgraph_of(work)
    new = {}
    try:
        for i, cm in enumerate(cached):
            yield (0.95 * i / len(cached), f"taking the copies into the scene {i}/{len(cached)}")
            work.data = cm
            dg.update()
            cp = bpy.data.meshes.new_from_object(work.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            for k in cm.keys():
                cp[k] = cm[k]
            orig = bpy.data.meshes.get((cm["rb_original"], None))
            if orig is not None:
                for i, mt in enumerate(orig.materials):
                    if i < len(cp.materials):
                        cp.materials[i] = mt
            cp.use_fake_user = True          # a copy no object shows (the render copy) is kept
            new[cm] = (cp, cm.name)
    finally:
        bpy.data.objects.remove(work)
        workscene.drop_work_scene()
    yield (0.95, "taking the copies into the scene")
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and ob.data in new:
            orig = bpy.data.meshes.get((ob.data["rb_original"], None))
            ob.data = new[ob.data][0]
            if orig is not None:
                object_materials(ob, orig, False)      # 1.9.0/1.9.1 scenes: materials back on the mesh
    for me in [m for m in bpy.data.meshes if m.library is None and not m.get("rb_original")]:
        for k in [k for k in me.keys() if k.startswith(CACHE_KEEP)]:
            del me[k]
    bpy.data.batch_remove(list(new) + list(refs))
    cleanup_libraries()
    for cp, name in new.values():
        cp.name = name
    return len(new)


def cleanup_libraries():
    """Remove linked copies nothing uses and the libraries nothing is linked from any more (the
    user count of a library is not reliable for this, run 64)."""
    orphans = [m for m in bpy.data.meshes if m.library is not None and m.users == 0]
    if orphans:
        bpy.data.batch_remove(orphans)
    used = set()
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.objects, bpy.data.node_groups,
                 bpy.data.images, bpy.data.collections, bpy.data.textures):
        used |= {i.library for i in coll if i.library is not None}
    gone = [lib for lib in bpy.data.libraries if lib not in used]
    if gone:
        bpy.data.batch_remove(gone)


def cache_missing_fix():
    """After loading: objects whose linked copy is missing (cache deleted or moved) show their
    original. Returns the number of objects switched back."""
    n = 0
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.data is None:
            continue
        ovr = ob.data.override_library
        ref_missing = ovr is not None and (ovr.reference is None or getattr(ovr.reference, "is_missing", False))
        if not (getattr(ob.data, "is_missing", False) or ref_missing):
            continue
        base = ob.data.get("rb_original") or ob.data.name.rsplit(" L", 1)[0]
        orig = bpy.data.meshes.get((base, None))
        if orig is not None and orig.library is None:
            ob.data = orig
            n += 1
    return n
