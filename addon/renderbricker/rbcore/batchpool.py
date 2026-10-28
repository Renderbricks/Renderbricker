"""The batches of one large mesh baked in background Blenders at once (maintainer, 15.10.2026: "Die 48x48 Platte ist
der Stresstest. Die dauert immer noch zu lange ..."). A batch is a mesh of its own with every value the rules take
from the whole mesh pinned (batches.bake_steps), so each one can be baked by another Blender: its mesh is written to
a .blend, a Blender without a window (--background) bakes it with batch_worker.py under the same settings - every
upper-case value of the rbcore modules as this Blender has it - and writes the copies and the report back; this one
loads them and joins them as if it had baked them itself.
bake(subs, levels) is a step generator: yields (batches done, batches) and returns [(copies {level: mesh}, report)]."""
import json
import os
import subprocess
import sys
import tempfile
import time

import bpy

from . import config

JOBS = int(os.environ.get("RENDERBRICKER_BATCH_JOBS", config.opt("--batch-jobs", "0")))   # background Blenders
                                                 # for the batches of one mesh; 0: by the cores
MIN_BATCHES = 2                                  # fewer batches are baked here
MIN_FACES = int(config.opt("--parallel-faces", "8000"))    # nor batches of fewer faces in all: starting a Blender
                                                           # costs ~3 s (Banana Mech in batches of 300 faces: slower);
                                                           # 30,000 baked the 48 x 48 baseplate's 28,275 faces of 71
                                                           # cell shapes (Renderbricks run 111) here: 110 s, in four
                                                           # Blenders 35 s
SPLIT_MIN = 4000                                           # faces of a batch at least when they are split for the
                                                           # Blenders (a cell baked alone came out further off; 4,000
                                                           # hold several cells: 4186 in 8 Blenders 64 s against 83 s
                                                           # with 8,000, shapes within 0.095 mm - the known spread of
                                                           # the bevel at a stud's foot per cell, run 287)


def worth(faces, batches_n):
    """Whether batches of `faces` faces in all are worth background Blenders (two at least)."""
    return batches_n >= MIN_BATCHES and faces >= MIN_FACES and jobs(batches_n) >= 2


def batch_size(faces, default):
    """The batch size when `faces` are baked by the background Blenders: one batch per Blender, not below
    SPLIT_MIN, not above `default`."""
    return max(SPLIT_MIN, min(default, -(-faces // jobs(max(1, faces // SPLIT_MIN)))))
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch_worker.py")
SIMPLE = (bool, int, float, str, type(None))
LOG = bool(os.environ.get("RENDERBRICKER_POOL_LOG"))   # when each batch starts and ends (measuring)


JOB_GB = 3.0                                     # memory a background Blender with one batch takes, about


def jobs(n):
    """How many background Blenders for n batches: JOBS, else half the cores (the others for this Blender and the
    rest of the machine) - shared with the other part workers when this Blender is one of them (Apply with several
    Blender processes: --worker i of N) - at most 8, and as many as JOB_GB each fit into the free memory."""
    if JOBS > 0:
        return max(1, min(n, JOBS))
    cores = (os.cpu_count() or 2) // 2
    if "--worker" in sys.argv:
        at = sys.argv.index("--worker")
        try:
            cores //= max(1, int(sys.argv[at + 2]))
        except (IndexError, ValueError):
            pass
    want = max(1, min(8, cores))
    try:
        from . import memory
        free = memory.free_memory_gb()
        if free is not None:
            want = max(1, min(want, int(free // JOB_GB)))
    except Exception:   # noqa: BLE001 - without the memory reading by the cores alone
        pass
    return max(1, min(n, want))


def settings():
    """Every upper-case module value of rbcore that is plain data (numbers, text, lists of them) - the settings the
    add-on or the command line put there and the pins of bake_steps."""
    out = {}
    pkg = __package__
    for name, mod in list(sys.modules.items()):
        if mod is None or not (name == pkg or name.startswith(pkg + ".")):
            continue
        short = name[len(pkg) + 1:] if name != pkg else ""
        for key, value in vars(mod).items():
            if not key.isupper() or key.startswith("_"):
                continue
            if isinstance(value, SIMPLE) or (isinstance(value, (list, tuple))
                                             and all(isinstance(x, SIMPLE) for x in value)):
                out[f"{short}.{key}"] = list(value) if isinstance(value, tuple) else value
    return out


def bake(subs, levels):
    """Bake the meshes `subs` in background Blenders; yields (done, total); returns [(copies, report)] in order."""
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="rb_batches_")
    state = settings()
    jobs_n = jobs(len(subs))
    pending = list(range(len(subs)))
    running, results = {}, [None] * len(subs)
    try:
        for i, sub in enumerate(subs):
            bpy.data.libraries.write(os.path.join(tmp, f"in_{i}.blend"), {sub}, fake_user=True)
        if LOG:
            print(f"POOL {len(subs)} batches written at {time.time() - t0:.1f} s, {jobs_n} Blenders", flush=True)
        with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as fh:
            json.dump({"settings": state, "levels": sorted(levels)}, fh)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        done = 0
        while pending or running:
            while pending and len(running) < jobs_n:
                i = pending.pop(0)
                cmd = [bpy.app.binary_path, "-b", "--factory-startup", "--python", WORKER, "--",
                       os.path.join(tmp, f"in_{i}.blend"), os.path.join(tmp, f"out_{i}.blend"),
                       os.path.join(tmp, "settings.json"), subs[i].name]
                log = open(os.path.join(tmp, f"log_{i}.txt"), "w", encoding="utf-8")
                running[i] = (subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=flags), log)
                if LOG:
                    print(f"POOL start {i} of {len(subs)} ({len(subs[i].polygons)} faces) at {time.time() - t0:.1f} s",
                          flush=True)
            for i, (pr, log) in list(running.items()):
                if pr.poll() is None:
                    continue
                log.close()
                del running[i]
                out = os.path.join(tmp, f"out_{i}.blend")
                if pr.returncode != 0 or not os.path.exists(out):
                    raise RuntimeError(f"a background Blender failed on batch {i} of {len(subs)}: "
                                       + open(os.path.join(tmp, f"log_{i}.txt"), encoding="utf-8",
                                              errors="replace").read()[-2000:])
                results[i] = _load(out, os.path.join(tmp, f"out_{i}.json"))
                if LOG:
                    print(f"POOL done {i} at {time.time() - t0:.1f} s", flush=True)
                done += 1
                yield done, len(subs)
            if running:
                time.sleep(0.1)
    finally:
        for pr, log in running.values():
            pr.kill()
            log.close()
        for f in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, f))
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    return results


def _load(path, report_path):
    """The copies a worker wrote ({level: mesh}) and its report."""
    with open(report_path, encoding="utf-8") as fh:
        info = json.load(fh)
    levels = list(info["copies"])
    with bpy.data.libraries.load(path, link=False) as (_src, dst):
        dst.meshes = [info["copies"][lv] for lv in levels]
    return {int(lv): me for lv, me in zip(levels, dst.meshes, strict=True)}, info["report"]
