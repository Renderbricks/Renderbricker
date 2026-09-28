"""Test-run driver: build, verify and render a set of parts into one run folder.

Usage (system Python, not Blender):
  python run_suite.py <NN> <slug> [--parts NAME ...] [--blender PATH] [--no-render] [-- extra args for mecabricks_subdiv]

- Sources: <project>/02_Imports/<NAME>.blend. Default: every import in
  02_Imports.
- Output: _CLAUDE_/runs/runNN_<slug>/builds/<NAME>_subdiv_A.blend,
  renders/<NAME>_*.png, logs/<NAME>_{build,verify}.log, REPORT.md
- Appends one line per run to _CLAUDE_/RUNS.md (index).
Deliverables in 03_Results are NOT touched; promoting a run is a
separate, deliberate step.
"""
import os, re, subprocess, sys, time, glob, datetime

# The repository root (scripts/core/ -> ..). The models (01_Sources, 02_Imports, 03_Results, ...) and the
# local work folder _CLAUDE_ (runs, logs, journals) live beside the code and are not in the repository.
PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).replace(os.sep, "/")
CL = f"{PROJECT}/_CLAUDE_"
S = f"{PROJECT}/scripts"
ADDON = f"{PROJECT}/addon"
RULES = f"{PROJECT}/docs/RULES.md"


def _default_blender():
    """Blender for the batch: RENDERBRICKER_BLENDER, else the path in _CLAUDE_/blender_path.txt (local,
    not in the repository), else 'blender' from PATH. --blender on the command line wins over all."""
    if os.environ.get("RENDERBRICKER_BLENDER"):
        return os.environ["RENDERBRICKER_BLENDER"]
    local = f"{CL}/blender_path.txt"
    if os.path.exists(local):
        return open(local, encoding="utf-8").read().strip()
    return "blender"


DEFAULT_BLENDER = _default_blender()

def main():
    a = sys.argv[1:]
    extra = a[a.index("--") + 1:] if "--" in a else []
    a = a[:a.index("--")] if "--" in a else a
    nn, slug = int(a[0]), a[1]
    blender = a[a.index("--blender") + 1] if "--blender" in a else DEFAULT_BLENDER
    parts = a[a.index("--parts") + 1:] if "--parts" in a else None
    if parts:
        parts = [p for p in parts if not p.startswith("--")]
    render = "--no-render" not in a
    if not parts:
        parts = sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(f"{PROJECT}/02_Imports/*.blend")
                       if "_subdiv" not in f)
    run = f"{CL}/runs/run{nn:02d}_{slug}"
    for sub in ("builds", "renders", "logs"):
        os.makedirs(f"{run}/{sub}", exist_ok=True)
    rows = []
    from progress import Progress, run_blender
    prog = Progress(f"Mecabricks run {nn:02d}")
    for k, p in enumerate(parts, 1):
        src, out = f"{PROJECT}/02_Imports/{p}.blend", f"{run}/builds/{p}_subdiv_A.blend"
        t0 = time.time()
        prog.title = f"Mecabricks run {nn:02d} {k}/{len(parts)} {p}"
        prog.set_stage(1, "convert meshes")
        blog = run_blender([blender, "-b", src, "--factory-startup", "--python", f"{S}/core/mecabricks_subdiv.py",
                            "--", out] + extra, f"{run}/logs/{p}_build.log", prog, "PART '", "MESHES")
        tb = time.time() - t0
        prog.set_stage(2, "verify meshes")
        vlog = run_blender([blender, "-b", out, "--factory-startup", "--python", f"{S}/core/verify_part.py", "--", src],
                           f"{run}/logs/{p}_verify.log", prog, "original mesh untouched", "MESHES")
        if render and os.path.exists(out):
            prog.set_stage(3, "render")
            subprocess.run([blender, "-b", out, "--factory-startup", "--python", f"{S}/tools/render_generic.py",
                            "--", f"{run}/renders", p], capture_output=True, text=True, errors="replace")
        rows.append(summarize(p, blog, vlog, tb, os.path.exists(out)))
        print(rows[-1]["line"], flush=True)
    write_report(run, nn, slug, rows, extra)
    index_line(nn, slug, rows)
    prog.title = f"Mecabricks run {nn:02d} {slug}"
    prog.finish()

def summarize(p, blog, vlog, tb, ok):
    parts = re.findall(r"PART '([^']+)' objects=(\d+) (\{.*\})", blog)
    errors = [l for l in (blog + vlog).splitlines() if "Traceback" in l or "Error:" in l]
    untouched = re.findall(r"original mesh untouched: (True|False)", vlog)
    folds = [int(x) for x in re.findall(r"faces with flipped children=(\d+)", vlog)]
    gapv = [float(x) for x in re.findall(r"seam gaps: pairs=\d+ max=([\d.]+)", vlog)]
    gape = [float(x) for x in re.findall(r"seam gaps along edges: pairs=\d+ max=([\d.]+)", vlog)]
    fans = sum(int(x) for x in re.findall(r"'t_fans_creased': (\d+)", blog))
    passes = max([int(x) for x in re.findall(r"'passes': (\d+)", blog)] or [0])
    # since run 38: every object uses the subdivided viewport copy of its mesh, no modifiers
    links = re.findall(r"VERIFY links: meshes (\d+), objects on the viewport copy (\d+), on another mesh (\d+), "
                       r"with modifiers (\d+), copies (\d+)", vlog)
    inst = [(t[4], t[1]) for t in links]                      # (copies, objects on them)
    inst_bad = sum(int(t[2]) + int(t[3]) for t in links)
    status = "OK" if ok and not errors and all(u == "True" for u in untouched) and not any(folds) \
        and max(gapv + [0]) < 1e-3 and max(gape + [0]) < 1e-3 and not inst_bad else "CHECK"
    d = dict(part=p, meshes=len(parts), untouched=all(u == "True" for u in untouched) and bool(untouched),
             folds=sum(folds), gapv=max(gapv + [0]), gape=max(gape + [0]), fans=fans, passes=passes,
             time=tb, errors=errors[:3], status=status,
             masters=int(inst[0][0]) if inst else 0, instances=int(inst[0][1]) if inst else 0, inst_bad=inst_bad)
    d["line"] = (f"{status:5s} {p}: meshes {d['meshes']}, untouched {d['untouched']}, folds {d['folds']}, "
                 f"seam gaps {d['gapv']:.4f}/{d['gape']:.4f}, fans {fans}, passes {passes}, "
                 f"copies {d['masters']}, links {d['instances']}"
                 + (f" ({inst_bad} badly linked)" if inst_bad else "") + f", {tb:.0f} s"
                 + (f"  ERR {errors[0]}" if errors else ""))
    return d

def write_report(run, nn, slug, rows, extra):
    L = [f"# Run {nn:02d} – {slug}", "", f"{datetime.datetime.now():%Y-%m-%d %H:%M} · args: {' '.join(extra) or '–'}", "",
         "| Part | Status | Meshes | Original untouched | Folded faces | Seam gap vertices | Seam gap edges | T fans creased | Passes | Build time |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['part']} | {r['status']} | {r['meshes']} | {r['untouched']} | {r['folds']} | {r['gapv']:.4f} | "
                 f"{r['gape']:.4f} | {r['fans']} | {r['passes']} | {r['time']:.0f} s |")
    errs = [(r['part'], e) for r in rows for e in r['errors']]
    if errs:
        L += ["", "## Errors", ""] + [f"- {p}: `{e}`" for p, e in errs]
    L += ["", "Logs: `logs/`, builds: `builds/`, renders: `renders/`. Findings go into `JOURNAL_260924.md` and `RULES.md`."]
    open(f"{run}/REPORT.md", "w", encoding="utf-8").write("\n".join(L) + "\n")

def index_line(nn, slug, rows):
    idx = f"{CL}/RUNS.md"
    ok = sum(r["status"] == "OK" for r in rows)
    line = (f"| {nn:02d} | {datetime.date.today()} | {slug} | {', '.join(r['part'] for r in rows)} | "
            f"{ok}/{len(rows)} OK (suite) | [report](runs/run{nn:02d}_{slug}/REPORT.md) |\n")
    with open(idx, "a", encoding="utf-8") as f:
        f.write(line)

if __name__ == "__main__":
    main()
