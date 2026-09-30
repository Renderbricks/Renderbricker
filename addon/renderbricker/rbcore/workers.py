"""Several Blender processes: shares and segments, the worker loop, the parent that starts and merges
them (Workers, _parallel)."""
import bpy
from . import cache as cache_mod, config, copies, memory, welding


MEMLOG = bool(__import__("os").environ.get("RENDERBRICKER_MEMLOG"))     # memory per mesh (measuring)


FLUSH_FACES = int(__import__("os").environ.get("RENDERBRICKER_FLUSH_FACES", 2_000_000))   # a worker writes its copies away after this many copy faces (run 61); the variable is for measuring (run 121)


WORKER_WAIT = 20         # seconds a worker waits for free memory (after writing its copies away) before


def _progress(i, n, done_w, total_w, t_start, name):
    import time
    el = time.time() - t_start
    left = el / done_w * (total_w - done_w) if done_w else 0
    bar = "#" * int(30 * done_w / total_w)
    return (f"PROGRESS [{bar:<30}] {i}/{n} meshes  {100 * done_w / total_w:5.1f} %  "
            f"elapsed {int(el // 60)}:{int(el % 60):02d}  left ~{int(left // 60)}:{int(left % 60):02d}  {name}")


def _assign(users, weight, n):
    """Meshes -> worker 0..n-1, largest first onto the least loaded (same in every process)."""
    load, part = [0] * n, {}
    for me in sorted(users, key=lambda m: (-weight[m], m.name)):
        k = load.index(min(load))
        part[me.name] = k
        load[k] += weight[me]
    return part


def load_share(source, names):
    """A worker's meshes from the scene file into this empty Blender (run 119): linked (reading only
    them is fast, append of a whole scene took 174 s for Dungeon), then made local so they can take
    their creases. Objects, cameras and lights stay in the file - the worker bakes meshes only; the
    materials come along linked and are taken off the copies before they are written.
    Returns (users {mesh: []}, weight, total weight) in the order of `names`."""
    want = set(names)
    with bpy.data.libraries.load(source, link=True) as (src, dst):
        dst.meshes = [n for n in src.meshes if n in want]
    for me in list(bpy.data.meshes):
        if me.library is not None and me.name in want:
            local = me.make_local()
            if local is None or local.library is not None:
                # Blender 5.3 alpha (2026-09-29): make_local() leaves a linked mesh linked - the workers
                # found none of their meshes. A copy of a linked mesh is local; it takes the name back
                name = me.name
                local = me.copy()
                bpy.data.meshes.remove(me)
                local.name = name
    by_name = {me.name: me for me in bpy.data.meshes if me.library is None}
    users = {by_name[n]: [] for n in names if n in by_name}
    weight = {me: len(me.polygons) + 50 for me in users}
    return users, weight, sum(weight.values()) or 1


def _run_meshes(users, pick, weight, total_w, show_progress, wait=0, after=None, flush=None):
    """Process the meshes in `pick` one after the other. Prints PART per mesh (the parent of a
    worker counts them), PROGRESS if show_progress. wait: a worker short of memory writes its
    copies away (flush), waits up to `wait` seconds and then retires - it prints RETIRE and
    stops, the meshes it did not do are done by the parent; without wait a mesh short of memory
    is skipped. after: called with each finished mesh. Returns (skipped, failed, reports)."""
    import time
    t_start, done_w = time.time(), 0
    skipped, failed, reps = [], [], {}
    for i, me in enumerate(pick, 1):
        obs = users[me]
        _t0 = time.time()
        deadline = time.time() + wait
        flushed = False
        while True:
            try:
                memory.check_memory(me, max(config.VIEW_LEVEL, config.RENDER_LEVEL), memory.RESERVE_GB if wait else 0.0)
                short = None
                break
            except memory.MemoryShortage as e:
                short = e
                if wait and flush and not flushed:      # give back what this worker holds first
                    flush()
                    flushed = True
                    continue
                if time.time() >= deadline:
                    break
                time.sleep(2)
        if short is not None:
            if wait:                    # a worker: stop and free all its memory for the others
                print(f"RETIRE worker short of memory at {me.name!r} ({len(pick) - i + 1} meshes left, "
                      f"done at the end): {short}", flush=True)
                break
            skipped.append(me.name)
            print(f"SKIP {me.name!r}: {short}", flush=True)
            continue
        if wait:                        # a segment process: the parent books the part it works on (run 125)
            print(f"START {me.name!r}", flush=True)
        try:
            rep = welding.process(me, obs)
        except Exception as e:      # one broken mesh must not end a long headless run
            import traceback
            traceback.print_exc()
            failed.append(me.name)
            print(f"Error in {me.name!r}: {type(e).__name__}: {e} - mesh left as imported", flush=True)
            continue
        rep['seconds'] = round(time.time() - _t0, 1)
        reps[me.name] = rep
        print(f"PART {me.name!r} objects={len(obs)} {rep}", flush=True)
        if after:
            after(me)
        if MEMLOG:                  # memory after every mesh (measuring, run 121)
            print(f"MEMLOG {me.name} faces {len(me.polygons)} need {memory.memory_need_gb(me, 2):.2f} "
                  f"now {memory.process_memory_gb() or 0:.2f} peak {memory.process_memory_gb(peak=True) or 0:.2f}", flush=True)
        done_w += weight[me]
        if show_progress:
            print(_progress(i, len(pick), done_w, total_w, t_start, me.name), flush=True)
    return skipped, failed, reps


def _run_worker_meshes(users, pick, weight, ledger, after=None, flush=None):
    """A worker's meshes with the ledger (run 121). A part needing more than LEDGER_BIG_GB is started
    only when the ledger books it; otherwise the worker bakes its small parts first and tries again.
    With only large parts left it writes its copies away and waits; after WORKER_WAIT seconds without
    room it retires (RETIRE) and a further round or the parent does the rest. Returns (skipped,
    failed, reports) like _run_meshes."""
    import time
    from collections import deque
    level = max(config.VIEW_LEVEL, config.RENDER_LEVEL)
    queue = deque(pick)
    skipped, failed, reps = [], [], {}
    waited_since = None
    while queue:
        me = queue.popleft()
        need = memory.memory_need_gb(copies.original_of(me), level)
        booked = False
        if need > memory.LEDGER_BIG_GB:
            ok, others, free = ledger.take(need, memory.RESERVE_GB)
            if not ok:
                queue.append(me)
                if any(memory.memory_need_gb(copies.original_of(m), level) <= memory.LEDGER_BIG_GB for m in queue):
                    small = next(m for m in queue if memory.memory_need_gb(copies.original_of(m), level) <= memory.LEDGER_BIG_GB)
                    queue.remove(small)
                    queue.appendleft(small)
                    continue
                if flush:                       # only large parts left: give back what this worker holds
                    flush()
                if others > 0:                  # the others' large parts end soon and give their memory back:
                    waited_since = None         # wait for them (run 122: retiring after 20 s left 22 large
                    time.sleep(1.0)             # parts to the parent alone)
                    continue
                if waited_since is None:        # nothing booked by the others and still no room: a real
                    waited_since = time.time()  # shortage - retire after WORKER_WAIT
                if time.time() - waited_since > WORKER_WAIT:
                    print(f"RETIRE worker short of memory at {me.name!r} ({len(queue)} meshes left, done at the "
                          f"end): needs about {need:.0f} GB, {free or 0:.0f} GB free, {others:.0f} GB booked "
                          f"by the others", flush=True)
                    break
                time.sleep(1.0)
                continue
            booked = True
        else:
            try:
                memory.check_memory(me, level, memory.RESERVE_GB)
            except memory.MemoryShortage as e:
                queue.append(me)
                if flush:
                    flush()
                if waited_since is None:
                    waited_since = time.time()
                if time.time() - waited_since > WORKER_WAIT:
                    print(f"RETIRE worker short of memory at {me.name!r} ({len(queue)} meshes left, done at the "
                          f"end): {e}", flush=True)
                    break
                time.sleep(1.0)
                continue
        waited_since = None
        t0 = time.time()
        try:
            rep = welding.process(me, users[me])
        except Exception as e:      # one broken mesh must not end a long headless run
            import traceback
            traceback.print_exc()
            failed.append(me.name)
            print(f"Error in {me.name!r}: {type(e).__name__}: {e} - mesh left as imported", flush=True)
            continue
        finally:
            if booked:
                ledger.give_back()
        rep['seconds'] = round(time.time() - t0, 1)
        reps[me.name] = rep
        print(f"PART {me.name!r} objects={len(users[me])} {rep}", flush=True)
        if after:
            after(me)
        if MEMLOG:
            print(f"MEMLOG {me.name} faces {len(me.polygons)} need {need:.2f} "
                  f"now {memory.process_memory_gb() or 0:.2f} peak {memory.process_memory_gb(peak=True) or 0:.2f}", flush=True)
    return skipped, failed, reps


SEGMENT_FACES = 250_000      # small parts are bundled into segments of at most about this many faces ...


SEGMENT_MIN_PER_SLOT = 2     # ... and at least twice as many segments as processes, so none waits idle


SEGMENT_BIG_GB = 6.0         # a part needing more than this is a segment of its own


SEGMENT_TRIES = 2            # a segment whose process stopped or crashed is queued again this often


class SegmentWorkers:
    """Several Blender processes (run 59/60; segments since run 124, the maintainer's idea). The meshes
    are cut into many small segments - every large part a segment of its own, the small ones bundled.
    Up to `jobs` segments run at the same time, each in a fresh Blender that loads only its meshes from
    the scene file (run 119), bakes them, writes its copies (without materials) to a part file plus a
    JSON of the reports and ends - so its memory is given back completely. This process starts the next
    segment only when the free memory, less what the running segments may still take (booked less
    measured), less the reserve, is enough for it; with nothing running it starts in any case. A segment
    whose process stopped or crashed is queued again, then the merge does the rest here. Used by the
    headless run (main) and by the add-on's Apply in the window (modal).
    start -> poll() for progress lines (and to start further segments) -> merge() the copies."""

    def __init__(self, users, jobs, opts, names=None, scene_path=None):
        import os, queue, tempfile
        self.users = users
        self.by_name = {me.name: me for me in users}
        self.weight = {me: len(me.polygons) + 50 for me in users}
        self.total_w = sum(self.weight.values()) or 1
        self.jobs = jobs                # the number of segments running at the same time at most
        self.tmp = tempfile.mkdtemp(prefix="rb_jobs_")
        self.q = queue.Queue()
        self.done, self.done_w, self.skipped, self.errors, self.retired = [], 0, [], [], 0
        self.peaks = []                 # memory peak of every segment process in GB (PEAK lines, run 117)
        self.opts, self.source = list(opts), scene_path or bpy.data.filepath
        self.todo = [me for me in users if names is None or me.name in set(names)]
        level = max(config.VIEW_LEVEL, config.RENDER_LEVEL)
        self.need = {me: memory.memory_need_gb(copies.original_of(me), level) for me in self.todo}
        self.procs, self.segs, self.booked, self.seen, self.redone = [], [], [], set(), set()
        self.current = []               # per process: the part it works on (START lines, run 125)
        self.tries = {}
        self.tries_max = 0 if os.environ.get("RENDERBRICKER_TEST_ROUND_JOBS") == "1" else SEGMENT_TRIES
        self.queue = self.segments(self.todo)
        self.n_segments = len(self.queue)
        self.schedule()

    def segments(self, meshes):
        """Large parts alone, small ones bundled - at least SEGMENT_MIN_PER_SLOT segments per process;
        the segments with the largest need first (they decide how long the run takes)."""
        big = [[me] for me in meshes if self.need[me] > SEGMENT_BIG_GB]
        small = sorted((me for me in meshes if self.need[me] <= SEGMENT_BIG_GB),
                       key=lambda m: (-self.weight[m], m.name))
        faces = sum(self.weight[m] for m in small)
        per = max(1, min(SEGMENT_FACES, faces // max(1, SEGMENT_MIN_PER_SLOT * self.jobs)))
        n = max(1, -(-faces // per)) if small else 0
        bins, load = [[] for _ in range(n)], [0] * n
        for me in small:                # largest first onto the lightest segment
            k = load.index(min(load))
            bins[k].append(me)
            load[k] += self.weight[me]
        segs = big + [b for b in bins if b]
        return sorted(segs, key=lambda s: (-max(self.need[m] for m in s), -sum(self.weight[m] for m in s)))

    def _book(self, seg):
        """Memory a segment may take: its largest part (they are baked one after the other and each gives
        its memory back) and a Blender with the segment loaded."""
        return max(self.need[m] for m in seg) + memory.SCENE_GB_BASE + memory.STEADY_GB

    def _launch(self, seg):
        import os, json, threading, subprocess
        i = len(self.procs)
        share = os.path.join(self.tmp, f"share{i}.json")
        json.dump([m.name for m in seg], open(share, "w", encoding="utf-8"))
        cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python",
               config.ENTRY, "--"] + self.opts + [
               "--source", self.source, "--share", share,
               "--worker", str(i), str(self.n_segments), self.part(i, "blend"), self.part(i, "json")]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", creationflags=flags)
        self.procs.append(pr)
        self.segs.append(seg)
        self.booked.append(self._book(seg))
        import time                     # the timeline of the segments, for the log (run 124)
        self.q.put(f"SEGSTART {i} {time.time():.1f} meshes {len(seg)} faces {sum(len(m.polygons) for m in seg)} "
                   f"book {self.booked[-1]:.1f}" + chr(10))
        self.current.append(seg[0])     # before its first START: its first part, the largest of the segment
        threading.Thread(target=self._reader, args=(pr, i), daemon=True).start()

    def _result(self, i):
        import os, json
        pj = self.part(i, "json")
        if not os.path.exists(pj):
            return None
        try:
            return json.load(open(pj, encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def schedule(self):
        """Queue again what an ended segment left undone, then start segments while there is room."""
        for i, pr in enumerate(self.procs):
            if i in self.seen or pr.poll() is None:
                continue
            self.seen.add(i)
            import time
            self.q.put(f"SEGEND {i} {time.time():.1f} exit {pr.returncode}" + chr(10))
            got = self._result(i) or {}
            left = [m for m in self.segs[i] if m.name not in got]
            if left and all(self.tries.get(m.name, 0) < self.tries_max for m in left):
                for m in left:
                    self.tries[m.name] = self.tries.get(m.name, 0) + 1
                if not got:
                    self.redone.add(i)      # no error for it at the merge: its meshes are done again
                self.queue.append(left)
                self.q.put(f"SEGMENT again: {len(left)} meshes of a stopped process\n")
        running = [i for i, pr in enumerate(self.procs) if pr.poll() is None]
        k = 0                           # from the front: the largest segment that fits starts first; one that
        free = None                     # does not fit waits, the smaller ones behind it go on (run 124: waiting
        while k < len(self.queue) and len(running) < self.jobs:     # at the front left 9 of 11 places idle)
            seg = self.queue[k]
            if running:
                if free is None:
                    free = memory.free_memory_gb()
                if free is not None:
                    taking = sum(max(0.0, self.need.get(self.current[i], 0.0) + memory.SCENE_GB_BASE + memory.STEADY_GB
                                     - (memory.process_memory_of(self.procs[i].pid) or 0.0)) for i in running)
                    if self._book(seg) + taking + memory.RESERVE_GB > free:
                        k += 1
                        continue
            self.queue.pop(k)
            self._launch(seg)
            running.append(len(self.procs) - 1)

    def pending(self):
        """Meshes no ended process has a result for (it stopped for memory or crashed)."""
        got = set()
        for i in range(len(self.procs)):
            got.update(self._result(i) or {})
        return [me for me in self.todo if me.name not in got]

    def next_round(self):
        """Kept for callers of run 120: the segments are queued again by schedule() themselves."""
        return 0

    def part(self, i, ext):
        import os
        return os.path.join(self.tmp, f"part{i}.{ext}")

    def _reader(self, pr, i=None):
        for line in pr.stdout:
            if i is not None and line.startswith("START '"):
                me = self.by_name.get(line[7:line.rindex("'")])
                if me is not None:
                    self.current[i] = me    # the part this process bakes now
                continue
            self.q.put(line)

    def running(self):
        self.schedule()
        return any(pr.poll() is None for pr in self.procs) or bool(self.queue) or not self.q.empty()

    def poll(self, timeout=0.0):
        """Read what the processes printed and start further segments; returns the lines worth showing."""
        import re, queue
        self.schedule()
        out = []
        while True:
            try:
                line = self.q.get(timeout=timeout).rstrip()
            except queue.Empty:
                return out
            timeout = 0.0
            m = re.match(r"PART '(.+?)' ", line)
            if m and m.group(1) in self.by_name and m.group(1) not in self.done:
                self.done.append(m.group(1))
                self.done_w += self.weight[self.by_name[m.group(1)]]
                out.append(("PART", m.group(1)))
            elif line.startswith("SKIP '"):
                self.skipped.append(line[6:line.index("'", 6)])
                out.append(("SKIP", line))
            elif line.startswith("RETIRE"):
                self.retired += 1
                out.append(("RETIRE", line))
            elif line.startswith("SEGMENT again"):
                out.append(("SEGMENT", line))
            elif line.startswith(("SEGSTART", "SEGEND")):
                out.append(("TIMELINE", line))
            elif line.startswith("PEAK worker"):
                m = re.search(r": ([\d.]+) GB", line)
                if m:
                    self.peaks.append(float(m.group(1)))
                out.append(("PEAK", line))
            elif line.startswith(("Error", "Traceback")):
                self.errors.append(line)
                out.append(("ERROR", line))

    def kill(self):
        import shutil
        self.queue = []
        for pr in self.procs:
            if pr.poll() is None:
                pr.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def merge_to_cache(self, path, on_mesh=None):
        return cache_mod.run_steps(self.merge_to_cache_steps(path, on_mesh))

    def merge_to_cache_steps(self, path, on_mesh=None):
        """With the cache on: the workers' part files go straight into the cache (a helper
        Blender joins them), this file only links the result - the copies are never loaded here
        (run 66: Dungeon 134 s loading + 65 s writing). Returns (reports, meshes without a
        worker result)."""
        import os, json, glob, shutil
        reps, files = {}, []
        for i in range(len(self.procs)):
            pj = self.part(i, "json")
            if not os.path.exists(pj):
                if i not in self.redone:
                    self.errors.append(f"Error: worker {i} wrote no result (exit {self.procs[i].returncode})")
                continue
            reps.update(json.load(open(pj, encoding="utf-8")))
            files += sorted(glob.glob(glob.escape(os.path.splitext(self.part(i, "blend"))[0]) + "_b*.blend"))
        levels = welding.bake_levels_wanted()
        fresh, rest = set(), []
        for k, (me, obs) in enumerate(self.users.items()):
            if k % 200 == 0:
                yield (0.05 * k / max(1, len(self.users)), "taking over the copies of the workers")
            if me.name in reps:
                orig = welding.prepare(me, obs)
                for ob in obs:              # off the old copies; the cache links the new ones
                    ob.data = orig
                old = copies.all_copies(orig)
                refs = [c.override_library.reference for c in old
                        if c.override_library is not None and c.override_library.reference is not None]
                if old or refs:
                    bpy.data.batch_remove(list({*old, *refs}))
                orig["rb_view"] = f"{orig.name} L{config.VIEW_LEVEL}" if config.VIEW_LEVEL else ""
                orig["rb_render"] = f"{orig.name} L{config.RENDER_LEVEL}" if config.RENDER_LEVEL else ""
                orig.use_fake_user = True
                for ob in obs:
                    ob.pop("rb_off", None)
                    ob["rb_show_view"] = 1          # write_cache puts them on the view copy
                fresh |= {(orig.name, lv) for lv in levels}
                if on_mesh:
                    on_mesh(me, obs, reps[me.name])
            elif me.name not in self.skipped:
                rest.append(me)
        steps = cache_mod.write_cache_steps(path, files=files, fresh=fresh)
        try:
            while True:
                st = next(steps)
                yield (0.05 + 0.95 * st[0],) + tuple(st[1:])
        except StopIteration as e:
            n = e.value
        for ob in bpy.data.objects:
            ob.pop("rb_show_view", None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return reps, rest, n

    def merge(self, on_mesh=None):
        """Load the workers' copies, give them the materials of their originals and link them
        as process() does. Returns (reports by mesh name, meshes without a worker result)."""
        import os, json, glob, shutil
        made, reps = {}, {}
        loaded = []
        for i in range(len(self.procs)):
            pj = self.part(i, "json")
            if not os.path.exists(pj):
                if i not in self.redone:
                    self.errors.append(f"Error: worker {i} wrote no result (exit {self.procs[i].returncode})")
                continue
            reps.update(json.load(open(pj, encoding="utf-8")))
            for pb in sorted(glob.glob(glob.escape(os.path.splitext(self.part(i, "blend"))[0]) + "_b*.blend")):
                with bpy.data.libraries.load(pb, link=False) as (src, dst):
                    dst.meshes = list(src.meshes)
                loaded += list(dst.meshes)
        for cp in loaded:
            if cp is None or cp.get("rb_original") not in self.by_name:
                continue
            orig = self.by_name[cp["rb_original"]]
            cp.use_fake_user = True          # not kept by the append - the render copy has no user
            for j, mt in enumerate(orig.materials):     # the worker wrote empty slots
                if j < len(cp.materials):
                    cp.materials[j] = mt
                else:
                    cp.materials.append(mt)
            made.setdefault(orig.name, {})[int(cp["rb_level"])] = cp
        rest = []
        for me, obs in self.users.items():
            if me.name in made and me.name in reps:
                orig = welding.prepare(me, obs)
                welding.finish(orig, obs, made[me.name], reps[me.name], check=False)
                if on_mesh:
                    on_mesh(me, obs, reps[me.name])
            elif me.name not in self.skipped:
                rest.append(me)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return reps, rest


class LedgerWorkers:
    """Several Blender processes with the ledger (run 59/60, 121): the saved scene is opened by `jobs` worker Blenders, each
    bakes its share of the meshes and writes only the copies (without materials) to a
    temporary .blend plus a JSON of the reports. Used by the headless run (main) and by the
    add-on's Apply in the window (modal, the window stays usable).
    start -> poll() for progress lines -> merge() the copies into this Blender."""

    def __init__(self, users, jobs, opts, names=None, scene_path=None):
        import os, json, queue, tempfile, threading, subprocess
        self.users = users
        self.by_name = {me.name: me for me in users}
        self.weight = {me: len(me.polygons) + 50 for me in users}
        self.total_w = sum(self.weight.values()) or 1
        self.jobs = jobs
        self.tmp = tempfile.mkdtemp(prefix="rb_jobs_")
        self.q = queue.Queue()
        self.done, self.done_w, self.skipped, self.errors, self.retired = [], 0, [], [], 0
        self.peaks = []                 # memory peak of every worker in GB (PEAK lines, run 117)
        # every worker gets the names of its share and loads only these meshes into an empty Blender
        # instead of opening the whole scene (run 119: Dungeon 2.9 GB per worker -> 0.6 GB for a quarter)
        self.opts, self.source = list(opts), scene_path or bpy.data.filepath
        self.todo = [me for me in users if names is None or me.name in set(names)]
        self.procs, self.rounds, self.redone = [], 0, set()
        self._start(self.todo, jobs)

    def _start(self, meshes, jobs):
        """Start `jobs` more worker Blenders for these meshes (a round); every one loads only its share."""
        import os, json, threading, subprocess
        part = _assign({me: None for me in meshes}, self.weight, jobs)
        first = len(self.procs)
        for k in range(jobs):
            i = first + k
            share = os.path.join(self.tmp, f"share{i}.json")
            json.dump(sorted(n for n, j in part.items() if j == k), open(share, "w", encoding="utf-8"))
            cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python",
                   config.ENTRY, "--"] + self.opts + [
                   "--source", self.source, "--share", share, "--ledger", os.path.join(self.tmp, "ledger.json"),
                   "--worker", str(i), str(jobs), self.part(i, "blend"), self.part(i, "json")]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace", creationflags=flags)
            self.procs.append(pr)
            threading.Thread(target=self._reader, args=(pr,), daemon=True).start()
        self.rounds += 1
        self.jobs = jobs

    def pending(self):
        """Meshes no finished worker has a result for (it stopped for memory or crashed)."""
        import os, json
        got = set()
        for i in range(len(self.procs)):
            pj = self.part(i, "json")
            if os.path.exists(pj):
                try:
                    got.update(json.load(open(pj, encoding="utf-8")))
                except (OSError, ValueError):
                    pass
        return [me for me in self.todo if me.name not in got]

    def next_round(self):
        """After a round: the meshes left get a further round of workers - as many as fit now (run 120:
        before, this Blender did them alone, 2,076 meshes of Dungeon in 1,371 s). Returns the number
        of workers started, 0 when nothing is left or one Blender is enough (the merge does the rest)."""
        import os
        left = self.pending()
        if not left or self.rounds >= 3:
            return 0
        jobs = memory.resolve_jobs("auto", len(left), left, per_process=1)   # a few large parts are worth it too
        forced = os.environ.get("RENDERBRICKER_TEST_ROUND_JOBS")     # CI: a further round on a small scene
        if forced:
            jobs = int(forced)
        if jobs < 2:
            return 0
        # workers without a result: their meshes are done again now, so no error for them at the merge
        self.redone |= {i for i in range(len(self.procs)) if not os.path.exists(self.part(i, "json"))}
        self._start(left, jobs)
        return jobs

    def part(self, i, ext):
        import os
        return os.path.join(self.tmp, f"part{i}.{ext}")

    def _reader(self, pr):
        for line in pr.stdout:
            self.q.put(line)

    def running(self):
        return any(pr.poll() is None for pr in self.procs) or not self.q.empty()

    def poll(self, timeout=0.0):
        """Read what the workers printed; returns the lines worth showing (PART counted)."""
        import re, queue
        out = []
        while True:
            try:
                line = self.q.get(timeout=timeout).rstrip()
            except queue.Empty:
                return out
            timeout = 0.0
            m = re.match(r"PART '(.+?)' ", line)
            if m and m.group(1) in self.by_name and m.group(1) not in self.done:
                self.done.append(m.group(1))
                self.done_w += self.weight[self.by_name[m.group(1)]]
                out.append(("PART", m.group(1)))
            elif line.startswith("SKIP '"):
                self.skipped.append(line[6:line.index("'", 6)])
                out.append(("SKIP", line))
            elif line.startswith("RETIRE"):
                self.retired += 1
                out.append(("RETIRE", line))
            elif line.startswith("PEAK worker"):
                m = re.search(r": ([\d.]+) GB", line)
                if m:
                    self.peaks.append(float(m.group(1)))
                out.append(("PEAK", line))
            elif line.startswith(("Error", "Traceback")):
                self.errors.append(line)
                out.append(("ERROR", line))

    def kill(self):
        import shutil
        for pr in self.procs:
            if pr.poll() is None:
                pr.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def merge_to_cache(self, path, on_mesh=None):
        return cache_mod.run_steps(self.merge_to_cache_steps(path, on_mesh))

    def merge_to_cache_steps(self, path, on_mesh=None):
        """With the cache on: the workers' part files go straight into the cache (a helper
        Blender joins them), this file only links the result - the copies are never loaded here
        (run 66: Dungeon 134 s loading + 65 s writing). Returns (reports, meshes without a
        worker result)."""
        import os, json, glob, shutil
        reps, files = {}, []
        for i in range(len(self.procs)):
            pj = self.part(i, "json")
            if not os.path.exists(pj):
                if i not in self.redone:
                    self.errors.append(f"Error: worker {i} wrote no result (exit {self.procs[i].returncode})")
                continue
            reps.update(json.load(open(pj, encoding="utf-8")))
            files += sorted(glob.glob(glob.escape(os.path.splitext(self.part(i, "blend"))[0]) + "_b*.blend"))
        levels = welding.bake_levels_wanted()
        fresh, rest = set(), []
        for k, (me, obs) in enumerate(self.users.items()):
            if k % 200 == 0:
                yield (0.05 * k / max(1, len(self.users)), "taking over the copies of the workers")
            if me.name in reps:
                orig = welding.prepare(me, obs)
                for ob in obs:              # off the old copies; the cache links the new ones
                    ob.data = orig
                old = copies.all_copies(orig)
                refs = [c.override_library.reference for c in old
                        if c.override_library is not None and c.override_library.reference is not None]
                if old or refs:
                    bpy.data.batch_remove(list({*old, *refs}))
                orig["rb_view"] = f"{orig.name} L{config.VIEW_LEVEL}" if config.VIEW_LEVEL else ""
                orig["rb_render"] = f"{orig.name} L{config.RENDER_LEVEL}" if config.RENDER_LEVEL else ""
                orig.use_fake_user = True
                for ob in obs:
                    ob.pop("rb_off", None)
                    ob["rb_show_view"] = 1          # write_cache puts them on the view copy
                fresh |= {(orig.name, lv) for lv in levels}
                if on_mesh:
                    on_mesh(me, obs, reps[me.name])
            elif me.name not in self.skipped:
                rest.append(me)
        steps = cache_mod.write_cache_steps(path, files=files, fresh=fresh)
        try:
            while True:
                st = next(steps)
                yield (0.05 + 0.95 * st[0],) + tuple(st[1:])
        except StopIteration as e:
            n = e.value
        for ob in bpy.data.objects:
            ob.pop("rb_show_view", None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return reps, rest, n

    def merge(self, on_mesh=None):
        """Load the workers' copies, give them the materials of their originals and link them
        as process() does. Returns (reports by mesh name, meshes without a worker result)."""
        import os, json, glob, shutil
        made, reps = {}, {}
        loaded = []
        for i in range(len(self.procs)):
            pj = self.part(i, "json")
            if not os.path.exists(pj):
                if i not in self.redone:
                    self.errors.append(f"Error: worker {i} wrote no result (exit {self.procs[i].returncode})")
                continue
            reps.update(json.load(open(pj, encoding="utf-8")))
            for pb in sorted(glob.glob(glob.escape(os.path.splitext(self.part(i, "blend"))[0]) + "_b*.blend")):
                with bpy.data.libraries.load(pb, link=False) as (src, dst):
                    dst.meshes = list(src.meshes)
                loaded += list(dst.meshes)
        for cp in loaded:
            if cp is None or cp.get("rb_original") not in self.by_name:
                continue
            orig = self.by_name[cp["rb_original"]]
            cp.use_fake_user = True          # not kept by the append - the render copy has no user
            for j, mt in enumerate(orig.materials):     # the worker wrote empty slots
                if j < len(cp.materials):
                    cp.materials[j] = mt
                else:
                    cp.materials.append(mt)
            made.setdefault(orig.name, {})[int(cp["rb_level"])] = cp
        rest = []
        for me, obs in self.users.items():
            if me.name in made and me.name in reps:
                orig = welding.prepare(me, obs)
                welding.finish(orig, obs, made[me.name], reps[me.name], check=False)
                if on_mesh:
                    on_mesh(me, obs, reps[me.name])
            elif me.name not in self.skipped:
                rest.append(me)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return reps, rest


def clean_for_workers(users):
    """Headless run on a converted scene (user, 2026-09-28): the links go back to the imported meshes
    and the copies and the cache library are removed - they are made again anyway. Italian Riviera
    opened with its cache took 3.9 GB instead of 1.0 GB, in the parent and in every worker. Returns
    whether anything was removed."""
    copies = [m for m in bpy.data.meshes if m.get("rb_original") and m.library is None]
    libs = [l for l in bpy.data.libraries if l.filepath.endswith("_rbcache.blend")]
    if not copies and not libs:
        return False
    for orig, obs in users.items():
        for o in obs:
            if o.data != orig:
                o.data = orig
    for m in copies:
        bpy.data.meshes.remove(m)
    for l in libs:
        bpy.data.libraries.remove(l)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    return True


def Workers(users, jobs, opts, names=None, scene_path=None):
    """The workers resolve_jobs chose (run 126): segments for a large scene, else the ledger."""
    kind = SegmentWorkers if memory.SEGMENTED[0] else LedgerWorkers
    return kind(users, jobs, opts, names, scene_path)


def _parallel(users, weight, total_w, jobs, scene_path=None):
    """Headless run on several cores (run 59): see Workers. scene_path: the file the workers open."""
    import time
    opts = list(config.args[1:]) if config.TARGET else list(config.args)
    for o in ("--jobs", "--low-memory"):     # the parent's choices, not the workers'
        if o in opts:
            k = opts.index(o)
            del opts[k:k + 2]
    w = Workers(users, jobs, opts, scene_path=scene_path)
    seg = f" in {w.n_segments} segments" if memory.SEGMENTED[0] else ""
    print(f"JOBS {jobs} Blender processes for {len(users)} meshes{seg}", flush=True)
    cache = config.opt("--cache", "")
    t_start = time.time()
    while True:
        while w.running():              # segments are started (and queued again) by poll (run 124)
            for kind, x in w.poll(timeout=0.5):
                if kind == "PART":
                    print(_progress(len(w.done), len(users), w.done_w, total_w, t_start, x), flush=True)
                else:
                    print(x, flush=True)
        more = w.next_round()           # meshes of stopped or crashed ledger workers (run 120)
        if not more:
            break
        print(f"JOBS round {w.rounds}: {more} Blender processes for the {len(w.pending())} meshes left "
              f"({memory.LAST_MEMORY_PLAN[0]})", flush=True)
    print(f"MERGE copies of the workers (bake {time.time() - t_start:.0f} s)", flush=True)
    t_m = time.time()
    if cache:                       # straight into the cache file (run 66)
        reps, rest, n = w.merge_to_cache(cache)
        cache_mod.CACHE_WRITTEN[0] = n
        print(f"CACHE {n} copies in {cache} ({time.time() - t_m:.0f} s)", flush=True)
    else:
        reps, rest = w.merge()
    for e in w.errors:
        if e.startswith("Error: worker"):
            print(e, flush=True)
    print(f"MERGE loaded and linked {time.time() - t_m:.0f} s", flush=True)
    skipped, failed = list(w.skipped), []
    if rest:        # a worker failed: its meshes are done here, one after the other
        print(f"MERGE {len(rest)} meshes without a worker result - processing them here", flush=True)
        s2, f2, _r = _run_meshes(users, rest, weight, total_w, True)
        skipped += s2
        failed += f2
    t_m = time.time()
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    print(f"MERGE cleaned {time.time() - t_m:.0f} s", flush=True)
    return skipped, failed


LOG = config.opt("--log", "")       # headless conversion with the add-on's option Log file


def say(msg):
    """A result line: to the console (the start script shows it) and, with --log, into the log file."""
    print(msg, flush=True)
    if LOG:
        try:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(f"  - {msg}\n")
        except OSError:
            pass
