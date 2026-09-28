"""Progress line in the Claude Code footer (status line, line 4).

Same file and format as library-audit (Renderbricks/library-audit-for-ldraw, progress.py):
~/.claude/job_progress.tsv, one tab separated line: title, stage no., stage name, done, total,
seconds left, time of writing, state, time of the start. The status line shows it while the file
is younger than 3 minutes and "finished" for 10 minutes, so a heartbeat rewrites it every 10 s.
"""
import os, subprocess, threading, time

FOOTER = os.path.join(os.path.expanduser("~"), ".claude", "job_progress.tsv")
PARTS = os.path.join(os.path.expanduser("~"), ".claude", "job_progress.d")    # one part file per process
HEARTBEAT = 10.0


class Progress:
    def __init__(self, title):
        self.title, self.start = title, time.time()
        self.stage_no, self.stage, self.done, self.total, self.begun = 0, "", 0, 0, self.start
        self.state = "running"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._beat, daemon=True).start()
        self.write()

    def _beat(self):
        while not self._stop.wait(HEARTBEAT):
            self.write()

    def set_stage(self, stage_no, stage, total=0):
        with self._lock:
            self.stage_no, self.stage, self.total, self.done, self.begun = stage_no, stage, total, 0, time.time()
        self.write()

    def tick(self, n=1, total=None):
        with self._lock:
            self.done += n
            if total is not None:
                self.total = total
        self.write()

    def _row(self, now):
        left = (now - self.begun) / self.done * (self.total - self.done) if self.done and self.total else 0
        return [self.title, self.stage_no, self.stage, self.done, self.total, int(left), int(now),
                self.state, int(self.start)]

    def _rows(self, now):
        return [self._row(now)]

    def write(self):
        if not os.path.isdir(os.path.dirname(FOOTER)):
            return
        with self._lock:
            rows = self._rows(time.time())
        # own rows into a part file per process, then the footer file is rebuilt from all parts
        # (run 50: two jobs wrote the one file and their bars took turns instead of showing side
        # by side); parts of ended processes drop out when stale (limits of the status line)
        text = "".join("\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n"
                       for row in rows)                  # one line = one bar in the footer
        try:
            os.makedirs(PARTS, exist_ok=True)
            part = os.path.join(PARTS, f"{os.getpid()}_{id(self)}.tsv")
            with open(part + ".tmp", "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            os.replace(part + ".tmp", part)
            merged, now = [], time.time()
            for name in sorted(os.listdir(PARTS)):
                path = os.path.join(PARTS, name)
                if not name.endswith(".tsv"):
                    continue
                try:
                    age = now - os.path.getmtime(path)
                    body = open(path, encoding="utf-8").read()
                except OSError:
                    continue
                if age > (600 if "\tfinished\t" in body else 180):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    continue
                merged.append(body)
            tmp = f"{FOOTER}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write("".join(merged))
            os.replace(tmp, FOOTER)
        except OSError:
            pass                                    # a status bar is no reason to stop a run

    def finish(self):
        self._stop.set()
        with self._lock:
            self.state, self.stage, self.done = "finished", "", self.total
        self.write()


class MultiProgress(Progress):
    """Several items (models) in parallel. The footer gets one bar for the whole batch
    (items finished / all) and one bar per running item (its stage, e.g. meshes done)."""

    def __init__(self, title, total):
        self.items = {}                      # name -> dict(stage_no, stage, done, total, begun, start)
        super().__init__(title)
        self.total = total

    def item(self, name):
        return _Item(self, name)

    def finished_item(self, name):
        with self._lock:
            self.items.pop(name, None)
            self.done += 1
        self.write()

    def _row(self, now):
        left = (now - self.start) / self.done * (self.total - self.done) if self.done and self.total else 0
        stage = f"{len(self.items)} running" if self.state == "running" else ""
        return [self.title, len(self.items), stage, self.done, self.total, int(left), int(now),
                self.state, int(self.start)]

    def _rows(self, now):
        rows = [self._row(now)]
        if self.state == "running":
            for name, it in self.items.items():
                left = (now - it["begun"]) / it["done"] * (it["total"] - it["done"]) \
                    if it["done"] and it["total"] else 0
                rows.append(["  " + name, it["stage_no"], it["stage"], it["done"], it["total"], int(left),
                             int(now), "running", int(it["start"])])
        return rows


class _Item:
    """What run_blender needs (set_stage, tick) for one item of a MultiProgress."""

    def __init__(self, parent, name):
        self.p, self.name = parent, name

    def set_stage(self, stage_no, stage, total=0):
        now = time.time()
        with self.p._lock:
            it = self.p.items.setdefault(self.name, {"start": now})
            it.update(stage_no=stage_no, stage=stage, done=0, total=total, begun=now)
        self.p.write()

    def tick(self, n=1, total=None):
        with self.p._lock:
            it = self.p.items.get(self.name)
            if it is None:
                return
            it["done"] += n
            if total is not None:
                it["total"] = total
        self.p.write()


def run_blender(cmd, log, prog=None, count=None, total=None):
    """Run Blender, write its output to `log`, return it. Every output line starting with
    `count` ticks the progress; a line "`total` <n>" sets the stage total."""
    out = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in p.stdout:
        out.append(line)
        if prog and total and line.startswith(total + " "):
            try:
                prog.tick(0, total=int(line.split()[1]))
            except ValueError:
                pass
        elif prog and count and count in line:
            prog.tick()
    p.wait()
    txt = "".join(out)
    open(log, "w", encoding="utf-8").write(txt)
    return txt
