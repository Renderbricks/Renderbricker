"""Batch conversion of Mecabricks models: import, convert, verify, update the curation list.

Usage (system Python, not Blender):
  python convert_models.py [--models NAME ...] [--force] [--stale] [--verify-only] [--jobs N] [--blender PATH]

For every <NAME>.zmbx in 01_Sources (or only --models):
  1. import   -> 02_Imports/<NAME>.blend        (only if missing; imports are never overwritten)
  2. convert  -> 03_Results/<NAME>_subdiv_A_mecabricks_<add-on version>.blend (older versions stay)
                 (only if missing, or --force, or --stale and built with older rules)
  3. verify   -> original untouched, folded faces, seam gaps
     --verify-only: check existing results again (after a change to verify_part.py)
  4. update the models table in 04_Curation/00_Curation.md (verdict and notes columns are kept)
Logs: _CLAUDE_/logs/convert/<NAME>_{import,build,verify}.log
--jobs N: models converted at the same time, each in its own Blender (default: one per
3 cores, one per 8 GB RAM, at most 8). Largest models start first. A memory budget
(75 % of the RAM, estimate per model from its largest mesh) holds models back until they fit
(run 45); a model too large on its own runs alone.
Rule development runs stay in run_suite.py (runs/runNN_*); this script is for production.
"""
import os, re, sys, time, datetime, glob, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_suite import PROJECT, CL, S, ADDON, RULES, DEFAULT_BLENDER, summarize
from progress import MultiProgress, run_blender
from concurrent.futures import ThreadPoolExecutor, as_completed

SOURCES, IMPORTS, RESULTS, CURATION = (f"{PROJECT}/{d}" for d in ("01_Sources", "02_Imports", "03_Results", "04_Curation"))
LOGS = f"{CL}/logs/convert"
TABLE = f"{CURATION}/00_Curation.md"
BEGIN, END = "<!-- models:begin (written by convert_models.py) -->", "<!-- models:end -->"
COLS = ["Model", "Objects", "Meshes", "Rules", "Converted", "Auto check", "Folds", "Seam gap", "Build", "Verdict", "Notes"]


# ---------------------------------------------------------------- memory budget (run 45)
# Up to 8 models ran at once regardless of size; NINJAGO_City's 32x32 baseplate alone needs
# 24 GB to bake. Each model gets an estimate; a model starts only while the estimates of the
# running ones plus its own fit into MEMORY_SHARE of the RAM (a model that is too large on its
# own still runs - alone). Estimate = base for loading the model + bake of its largest mesh.
MEMORY_SHARE = 0.75
GB_BASE, GB_PER_IMPORT_MB = 2.0, 0.15          # Porsche: 25 MB import -> ~6 GB measured
GB_PER_FACE_Q10, GB_PER_FACE_Q6 = 0.2e-3, 0.085e-3   # bake measurements run 45 (86k: 18 GB, 286k q6: 24 GB)


def total_ram_gb():
    """Installed RAM in GB: Windows GlobalMemoryStatusEx, Linux/macOS sysconf; 16 if unknown."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong)] + [(f"x{i}", ctypes.c_ulonglong) for i in range(5)]
            m = MS(); m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.total / 2 ** 30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except Exception:
        return 16.0


def estimate_gb(blender, imp):
    """Estimated peak memory of converting and verifying one model (cached per import file)."""
    import json
    cache_file = f"{LOGS}/memory_estimates.json"
    try:
        cache = json.load(open(cache_file, encoding="utf-8"))
    except Exception:
        cache = {}
    st = os.stat(imp)
    key = f"{os.path.basename(imp)}|{st.st_size}|{int(st.st_mtime)}"
    if key not in cache:
        out = run(blender, ["-b", imp, "--factory-startup", "--python", f"{S}/core/scan_model.py"],
                  f"{LOGS}/{os.path.basename(imp)[:-6]}_scan.log")
        m = re.search(r"SCAN max_faces (\d+)", out)
        faces = int(m.group(1)) if m else 0
        per_face = GB_PER_FACE_Q10 if faces <= 50000 else GB_PER_FACE_Q6
        cache[key] = {"max_faces": faces,
                      "gb": round(GB_BASE + GB_PER_IMPORT_MB * st.st_size / 2 ** 20 + per_face * faces, 1)}
        entry = cache[key]
        with BUDGET.cond:              # parallel jobs: re-read and merge, else the last writer wins
            try:
                disk = json.load(open(cache_file, encoding="utf-8"))
            except Exception:
                disk = {}
            disk[key] = entry
            json.dump(disk, open(cache_file, "w", encoding="utf-8"), indent=1)
    return cache[key]["gb"]


class Budget:
    def __init__(self, limit_gb):
        self.limit, self.used, self.running = limit_gb, 0.0, 0
        self.cond = threading.Condition()

    def acquire(self, gb):
        with self.cond:
            while self.running and self.used + gb > self.limit:
                self.cond.wait()
            self.used += gb; self.running += 1

    def release(self, gb):
        with self.cond:
            self.used -= gb; self.running -= 1
            self.cond.notify_all()


BUDGET = Budget(MEMORY_SHARE * total_ram_gb())


def rules_version():
    m = re.search(r"Version (\d+\.\d+)", open(RULES, encoding="utf-8").read())
    return m.group(1) if m else "?"


def addon_version():
    """Version of the add-on source (bl_info), e.g. '1-6-5' - results carry it in their name
    so versions can be compared side by side (user, 2026-09-26)."""
    m = re.search(r'"version": \((\d+), (\d+), (\d+)\)', open(f"{ADDON}/renderbricker/__init__.py",
                                                             encoding="utf-8").read())
    return "-".join(m.groups()) if m else "0-0-0"


def result_path(name):
    return f"{RESULTS}/{name}_subdiv_A_mecabricks_{addon_version()}.blend"


def read_table():
    """Rows of the models table by model name (dict of column -> text)."""
    if not os.path.exists(TABLE):
        return {}
    txt = open(TABLE, encoding="utf-8").read()
    if BEGIN not in txt:
        return {}
    rows = {}
    for line in txt.split(BEGIN, 1)[1].split(END, 1)[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == len(COLS) and cells[0] not in ("Model", "") and not set(cells[0]) <= set("-"):
            rows[cells[0]] = dict(zip(COLS, cells))
    return rows


def write_table(rows):
    txt = open(TABLE, encoding="utf-8").read()
    head, rest = txt.split(BEGIN, 1)
    tail = rest.split(END, 1)[1]
    L = ["| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)]
    for name in sorted(rows, key=str.lower):
        L.append("| " + " | ".join(rows[name].get(c, "") for c in COLS) + " |")
    open(TABLE, "w", encoding="utf-8").write(head + BEGIN + "\n" + "\n".join(L) + "\n" + END + tail)


def run(blender, args, log, prog=None, count=None):
    return run_blender([blender] + args, log, prog, count, "MESHES")


# Mecabricks Advanced writes each texture into its own add-on folder, loads it and deletes
# it again, under the texture's name (11214_1.png ...): two imports at once could delete
# each other's files. Imports therefore run one at a time; convert and verify in parallel.
IMPORT_LOCK = threading.Lock()


def replace_retry(src, dst, wait=120):
    """Synology Drive holds large files briefly while it uploads them: 'access denied' when
    replacing a result (run 42). Retry for up to `wait` seconds before giving up."""
    t0 = time.time()
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.time() - t0 > wait:
                raise
            time.sleep(5)


def convert_one(name, row, blender, rv, force, stale, vonly, prog):
    """Import, convert and verify one model; returns (row, report line). Runs in a worker thread."""
    src, imp, out = f"{SOURCES}/{name}.zmbx", f"{IMPORTS}/{name}.blend", result_path(name)
    lines = []
    if not os.path.exists(imp):
        if not os.path.exists(src):
            return row, f"SKIP  {name}: neither {src} nor {imp}"
        prog.set_stage(1, "waiting to import")
        with IMPORT_LOCK:
            t0 = time.time()
            prog.set_stage(1, "import")
            log = run(blender, ["-b", "--factory-startup", "--python", f"{S}/core/import_zmbx.py", "--", src, imp],
                      f"{LOGS}/{name}_import.log")
        if not os.path.exists(imp):
            row.update({"Auto check": "IMPORT FAILED", "Converted": str(datetime.date.today())})
            return row, f"FAIL  {name}: import failed, see logs/convert/{name}_import.log"
        lines.append(f"      {name}: imported, {log.count(chr(10) + 'OBJ ')} objects, {time.time() - t0:.0f} s")
    if not (vonly and os.path.exists(out)) and \
            not (force or not os.path.exists(out) or (stale and row.get("Rules") != rv)):
        return row, "\n".join(lines + [f"KEEP  {name}: result exists (rules {row.get('Rules') or '?'})"])
    prog.set_stage(2, "estimating memory")
    gb = estimate_gb(blender, imp)
    prog.set_stage(2, f"waiting for memory (~{gb:.0f} GB)")
    BUDGET.acquire(gb)
    try:
        return convert_steps(name, row, blender, rv, force, stale, vonly, prog, imp, out, lines)
    finally:
        BUDGET.release(gb)


def convert_steps(name, row, blender, rv, force, stale, vonly, prog, imp, out, lines):
    if vonly and os.path.exists(out):
        prog.set_stage(3, "verify")
        vlog = run(blender, ["-b", out, "--factory-startup", "--python", f"{S}/core/verify_part.py", "--", imp],
                   f"{LOGS}/{name}_verify.log", prog, "original mesh untouched")
        blog_path = f"{LOGS}/{name}_build.log"
        blog = open(blog_path, encoding="utf-8", errors="replace").read() if os.path.exists(blog_path) else ""
        d = summarize(name, blog, vlog, 0, True)
        row.update({"Auto check": d["status"] if d["untouched"] else "CHECK: original changed",
                    "Folds": str(d["folds"]), "Seam gap": f"{max(d['gapv'], d['gape']):.3f}"})
        return row, "\n".join(lines + [d["line"].replace(", 0 s", "")])
    if not (force or not os.path.exists(out) or (stale and row.get("Rules") != rv)):
        return row, "\n".join(lines + [f"KEEP  {name}: result exists (rules {row.get('Rules') or '?'})"])
    t0 = time.time()
    prog.set_stage(2, "convert")
    tmp = f"{RESULTS}/_building_{name}.blend"   # replace the result only when the build succeeded (no .blend1)
    blog = run(blender, ["-b", imp, "--factory-startup", "--python", f"{S}/core/mecabricks_subdiv.py", "--", tmp],
               f"{LOGS}/{name}_build.log", prog, "PART '")
    tb = time.time() - t0
    if os.path.exists(tmp):
        prog.set_stage(2, "replacing the result")
        replace_retry(tmp, out)
    prog.set_stage(3, "verify")
    vlog = run(blender, ["-b", out, "--factory-startup", "--python", f"{S}/core/verify_part.py", "--", imp],
               f"{LOGS}/{name}_verify.log", prog, "original mesh untouched")
    d = summarize(name, blog, vlog, tb, os.path.exists(out))
    objs = sum(int(n) for n in re.findall(r"PART '[^']+' objects=(\d+)", blog))
    check = d["status"]
    if not d["untouched"]:
        check = "CHECK: original changed"
    elif d["errors"]:
        check = "CHECK: error"
    row.update({"Objects": str(objs), "Meshes": str(d["meshes"]), "Rules": rv,
                "Converted": str(datetime.date.today()), "Auto check": check, "Folds": str(d["folds"]),
                "Seam gap": f"{max(d['gapv'], d['gape']):.3f}", "Build": f"{tb:.0f} s"})
    return row, "\n".join(lines + [d["line"]])


def default_jobs():
    """One Blender per 3 cores, at most one per 8 GB of RAM (a car needs a few GB), at most 8."""
    return max(1, min(8, (os.cpu_count() or 3) // 3, int(total_ram_gb() // 8)))


def main():
    a = sys.argv[1:]
    blender = a[a.index("--blender") + 1] if "--blender" in a else DEFAULT_BLENDER
    jobs = int(a[a.index("--jobs") + 1]) if "--jobs" in a else default_jobs()
    names = None
    if "--models" in a:       # names up to the next option (run 57: "--jobs 1" was read as a model)
        rest = a[a.index("--models") + 1:]
        names = rest[:next((i for i, x in enumerate(rest) if x.startswith("--")), len(rest))]
    if names:
        names = [n for n in names if not n.startswith("--")]
    force, stale, vonly = "--force" in a, "--stale" in a, "--verify-only" in a
    os.makedirs(LOGS, exist_ok=True)
    rv = rules_version()
    table = read_table()
    if not names:
        names = [os.path.splitext(os.path.basename(f))[0] for f in glob.glob(f"{SOURCES}/*.zmbx")]
    # largest first, so the long ones do not end up running alone at the end
    size = lambda n: max((os.path.getsize(f) for f in (f"{SOURCES}/{n}.zmbx", f"{IMPORTS}/{n}.blend")
                          if os.path.exists(f)), default=0)
    names = sorted(set(names), key=size, reverse=True)
    jobs = max(1, min(jobs, len(names)))
    print(f"      {len(names)} models, {jobs} in parallel", flush=True)
    prog = MultiProgress(f"Mecabricks convert ×{jobs}", len(names))
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {}
        for name in names:
            row = table.get(name, {c: "" for c in COLS})
            row["Model"] = name
            futures[pool.submit(convert_one, name, row, blender, rv, force, stale, vonly, prog.item(name))] = name
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                row, line = fut.result()
                table[name] = row
            except Exception as e:                   # one broken model must not stop the batch
                table.setdefault(name, {c: "" for c in COLS}).update({"Model": name, "Auto check": f"CHECK: error {e}"})
                line = f"FAIL  {name}: {e!r}"
            prog.finished_item(name)
            print(line, flush=True)
            write_table(table)                       # after every model, so a long batch can be followed
    write_table(table)
    print(f"      done: {len(names)} models in {time.time() - t0:.0f} s with {jobs} in parallel", flush=True)
    prog.title = f"Mecabricks convert {len(names)} models"
    prog.finish()


if __name__ == "__main__":
    main()
