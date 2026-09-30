"""Memory: estimate per part and per scene, free and process memory, the ledger of large parts and
the number of Blender processes a run can use (resolve_jobs)."""
import bpy, sys
from . import config, copies


# Memory guard (add-on 1.5.8, run 49): the quality bake of one large mesh needs about
# 0.2 MB (quality 10) or 0.085 MB (quality 6) per original face - the 286k-face baseplate
# of NINJAGO_City ~24 GB. In the window a crash lost the user's work when another program
# (a local language model, 40 GB) had taken the memory. Before each mesh the free commit
# memory (RAM + page file, what Windows reports as running out) is compared with the need.
GB_PER_FACE = {config.BAKE_QUALITY: 0.2e-3, config.BAKE_QUALITY_LARGE: 0.085e-3}


GB_MARGIN = 1.5


class MemoryShortage(Exception):
    pass


def memory_need_gb(me, level=2):
    """Measured at level 2; every further level has four times the faces."""
    return len(me.polygons) * GB_PER_FACE.get(copies.bake_quality(me), 0.2e-3) * 1.05 * 4 ** max(0, level - 2) + GB_MARGIN


FREE_OVERRIDE = [None]      # tests: a worker told it has no memory (RENDERBRICKER_TEST_SHORT_WORKER)


def free_memory_gb():
    """Memory a bake can still use, in GB; None if unknown.
    Windows: free commit memory (RAM + page file, what runs out first there).
    Linux: MemAvailable (free RAM + reclaimable cache) + free swap.
    macOS: free + inactive + speculative + purgeable pages (vm_stat) + free swap."""
    import sys
    if FREE_OVERRIDE[0] is not None:
        return FREE_OVERRIDE[0]
    if sys.platform.startswith("win"):
        try:
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullAvailPageFile / 2**30
        except (AttributeError, OSError):
            pass
        return None
    if sys.platform.startswith("linux"):
        try:
            info = {}
            for line in open("/proc/meminfo"):
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
            return (info.get("MemAvailable", info.get("MemFree", 0)) + info.get("SwapFree", 0)) / 2**30
        except (OSError, ValueError):
            return None
    if sys.platform == "darwin":
        try:
            import re, subprocess
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = int(re.search(r"page size of (\d+) bytes", out).group(1))
            pages = sum(int(n) for k, n in re.findall(r"Pages (free|inactive|speculative|purgeable):\s+(\d+)", out))
            swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"free = ([\d.]+)M", swap)
            return pages * page / 2**30 + (float(m.group(1)) / 1024 if m else 0.0)
        except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
            return None
    return None


def process_memory_gb(peak=False):
    """Memory of this Blender in GB (peak=True: the highest so far); None if unknown.
    Windows: committed memory (private bytes - what counts against the commit limit).
    Linux / macOS: resident memory (the peak from getrusage, the current from /proc)."""
    import sys
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                            ("PrivateUsage", ctypes.c_size_t)]
            c = PMC(); c.cb = ctypes.sizeof(PMC)
            k32 = ctypes.WinDLL("kernel32")
            psapi = ctypes.WinDLL("psapi")
            h = k32.GetCurrentProcess()
            h = ctypes.c_void_p(h)
            if psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                return (c.PeakPagefileUsage if peak else c.PrivateUsage) / 2**30
        except (AttributeError, OSError):
            return None
        return None
    try:
        if peak:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return r / 2**30 if sys.platform == "darwin" else r / 2**20     # bytes on macOS, KB on Linux
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 2**20
    except (OSError, ValueError, ImportError):
        return None
    return None


def _pid_alive(pid):
    """Whether a process still runs (a crashed worker's booking must not block the others)."""
    import os, sys
    if pid == os.getpid():
        return True
    if sys.platform.startswith("win"):
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        k32.OpenProcess.restype = ctypes.c_void_p            # a handle is a pointer (64 bit)
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259                # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


class MemoryLedger:
    """The memory the workers of one run have booked for the large parts they bake right now (run 121).
    A JSON file {pid: GB} next to the workers' part files, changed only under a lock file, so the
    check "enough free memory for this part" and the booking are one step for all workers together.
    Bookings of processes that no longer run are ignored."""

    def __init__(self, path):
        self.path, self.lock_path = path, path + ".lock"

    def _locked(self, fn):
        import os, sys, time
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT)
        try:
            if sys.platform.startswith("win"):
                import msvcrt
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
                try:
                    return fn()
                finally:
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                return fn()
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read(self):
        import json
        try:
            d = json.load(open(self.path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in d.items() if _pid_alive(int(k))}

    def _write(self, d):
        import json
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(d, fh)

    def take(self, need, reserve):
        """Book `need` GB for this process if the free memory, less what the others have booked and the
        reserve, is enough. Returns (booked, others' bookings in GB, free GB)."""
        import os

        def step():
            d = self._read()
            others = sum(v for k, v in d.items() if int(k) != os.getpid())
            free = free_memory_gb()
            ok = free is None or need + others + reserve <= free
            if ok:
                d[str(os.getpid())] = round(need, 2)
            self._write(d)
            return ok, others, free
        return self._locked(step)

    def give_back(self):
        import os

        def step():
            d = self._read()
            d.pop(str(os.getpid()), None)
            self._write(d)
        self._locked(step)


def check_memory(me, level=2, reserve=0.0):
    """Raise MemoryShortage before a mesh whose bake would not fit into free memory. Workers keep
    `reserve` free on top (run 120: eight workers on Dungeon passed their checks together and used up
    all memory - six of them crashed, and the other programs had none left either)."""
    need, free = memory_need_gb(copies.original_of(me), level), free_memory_gb()
    if free is not None and need + reserve > free:
        raise MemoryShortage(f"not enough free memory for {me.name} ({len(me.polygons):,} faces): needs about "
                             f"{need:.0f} GB, {free:.0f} GB free - close other programs and apply again")


                         # it retires; its remaining meshes are done by the parent at the end. Up to
                         # 2026-09-28 it waited 600 s per mesh: all workers of Italian Riviera (converted
                         # scene, commit memory full) waited for each other, the run stood still (user)
JOB_GB = 6.0             # free memory per worker Blender when nothing is known about the meshes (run 59)


# memory of the worker Blenders, measured on six scenes (run 117: peak commit of every worker):
SCENE_GB_BASE = 0.35     # a background Blender with an empty scene


SCENE_GB_PER_MLOOP = 0.10    # the scene's meshes, per million face corners


SCENE_GB_PER_IMAGE = 0.0009  # its images (Dungeon: 1270 images, 1.2 GB)


# a worker holds little between its parts - one of Dungeon's workers stayed at 1.4-1.9 GB with its share
# of the scene - but a large part needs its memory_need_gb for as long as it is baked (91405.004, 86,072
# faces: 10.5 GB). Several large parts at the same time used up all memory (run 120); since run 124 the
# parent starts a segment only when there is room for it (Workers.schedule).
STEADY_GB = 1.2              # a Blender between its parts, on top of what it has loaded


LEDGER_BIG_GB = 3.0          # parts that need more than this are booked in the ledger before they start


SLOT_GB = 1.0                # segments: a small part in the works - so a place costs about 2.5 GB (run 125)


RESERVE_GB = 4.0             # memory left free for the rest of the computer (at least, or 10 % of it)


def scene_memory_gb():
    """Memory a worker needs for the open scene alone (run 117: within +0.3 / -0.1 GB of the measured
    load of six scenes; the image term is on the safe side for scenes with few large images)."""
    loops = sum(len(m.loops) for m in bpy.data.meshes if m.library is None)
    return SCENE_GB_BASE + SCENE_GB_PER_MLOOP * loops / 1e6 + SCENE_GB_PER_IMAGE * len(bpy.data.images)


def workers_memory_gb(n, meshes, scene_gb=None):
    """Memory n worker Blenders need together for these meshes (run 121): every worker holds its share
    of the scene and STEADY_GB between its parts; the largest part comes once on top. More large parts at
    the same time only when the ledger (MemoryLedger) finds room for them - so this is what the plan has
    to fit, not the worst case."""
    meshes = list(meshes)
    if scene_gb is None:
        scene_gb = scene_memory_gb()
    scene_gb = SCENE_GB_BASE + (scene_gb - SCENE_GB_BASE) / max(1, n)     # only its share (run 119)
    largest = max((memory_need_gb(me, max(2, config.RENDER_LEVEL)) for me in meshes), default=0.0)
    return n * (scene_gb + STEADY_GB) + largest


JOBS_MAX = 12               # upper bound of worker Blenders (run 59: 8; run 117: Riviera 126 / 87 / 82 s


                            # with 4 / 8 / 10 - the memory decides, see workers_memory_gb)
LAST_MEMORY_PLAN = [""]     # the reasoning of the last resolve_jobs, for the log and the panel


SEGMENTED = [False]         # whether the last resolve_jobs chose segments (Workers, run 126)


def resolve_jobs(value, n_meshes, meshes=None, per_process=20, low_memory=None):
    """--jobs: a number, or 'auto': one Blender per 2 cores, at most JOBS_MAX, at least ~20 meshes each,
    and as many as fit into the free memory less a reserve (RESERVE_GB or 10 %) - estimated per scene
    from its meshes (run 117); without the meshes one per JOB_GB (run 59)."""
    import os
    if low_memory is None:          # "Low Memory" (run 126): auto, on (always segments) or off (never)
        low_memory = {"1": "on", "0": "off"}.get(os.environ.get("RENDERBRICKER_SEGMENTS"), config.opt("--low-memory", "auto"))
    SEGMENTED[0] = low_memory == "on"
    if value != "auto":
        return max(1, int(value))
    cores = (os.cpu_count() or 2) // 2
    top = max(1, min(JOBS_MAX, cores, n_meshes // per_process))
    free = None
    try:
        free = free_memory_gb()
    except Exception:
        pass
    if free is None:
        LAST_MEMORY_PLAN[0] = "free memory unknown: 2 Blenders"
        return max(1, min(2, top))
    if not meshes:
        n = max(1, min(top, int(free // JOB_GB)))
        LAST_MEMORY_PLAN[0] = f"{n} Blenders ({free:.0f} GB free, {JOB_GB:.0f} GB each)"
        return n
    meshes = list(meshes)
    scene_gb = scene_memory_gb()
    n = 1
    room = free - max(RESERVE_GB, 0.1 * free)
    for k in range(top, 0, -1):
        if workers_memory_gb(k, meshes, scene_gb) <= room:
            n = k
            break
    # a large scene (run 126): when its largest part leaves the ledger less than half the places, it is cut
    # into segments - NINJAGO City's 27 GB part left one Blender for 1,079 meshes (674 s; segments 229 s).
    # Otherwise the ledger: segments took Italian Riviera 162 s instead of 84 s and Dungeon 532 s, not 333 s
    places = max(1, min(top, int(room // (SCENE_GB_BASE + STEADY_GB + SLOT_GB))))
    SEGMENTED[0] = low_memory == "on" or (low_memory == "auto" and places >= 2 and 2 * n < places)
    if SEGMENTED[0]:
        largest = max((memory_need_gb(me, max(2, config.RENDER_LEVEL)) for me in meshes), default=0.0)
        LAST_MEMORY_PLAN[0] = (f"{places} places for segments ({free:.0f} GB free, the largest part needs about "
                               f"{largest:.0f} GB, so only {n} Blenders would fit it; segments start when there "
                               f"is room; at most {top} by cores and parts)")
        return places
    need = workers_memory_gb(n, meshes, scene_gb)
    LAST_MEMORY_PLAN[0] = (f"{n} Blenders: about {need:.0f} GB of {free:.0f} GB free "
                           f"(scene {scene_gb:.1f} GB, shared among them; at most {top} by cores and parts)")
    return n


def process_memory_of(pid):
    """Memory of another process in GB (Windows: committed private bytes, else resident); None if unknown.
    The parent measures its running segments with it (run 124)."""
    import sys
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                            ("PrivateUsage", ctypes.c_size_t)]
            k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
            h = k32.OpenProcess(0x1000 | 0x0010, False, int(pid))     # QUERY_LIMITED_INFORMATION | VM_READ
            if not h:
                return None
            try:
                c = PMC(); c.cb = ctypes.sizeof(PMC)
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                    return c.PrivateUsage / 2**30
            finally:
                k32.CloseHandle(h)
        except (AttributeError, OSError):
            return None
        return None
    try:
        for line in open(f"/proc/{int(pid)}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 2**20
    except (OSError, ValueError):
        return None
    return None
