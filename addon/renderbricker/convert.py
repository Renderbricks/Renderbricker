"""Apply, Check and Levels: operators that work part by part with a progress bar (modal)."""
import time
import bpy
from . import rbcore as core
from . import common, logfile, props, widgets


# ---------------------------------------------------------------- operators
def fmt_time(sec):
    sec = int(round(sec))
    return f"{sec // 60} min {sec % 60:02d} s" if sec >= 90 else f"{sec} s"


def redraw(context):
    """Only the sidebar (the panel) and the status bar: a redraw of the whole 3D view on every
    progress update drew all 28,000 objects of Dungeon again (run 69)."""
    for area in (context.screen.areas if context.screen else []):
        if area.type == 'STATUSBAR':
            area.tag_redraw()
        elif area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'UI':
                    region.tag_redraw()


def work_budget(op, interval=0.0):
    """Seconds of work per timer tick (run 69): Blender spends a pause between two ticks on the
    whole scene (with new data-blocks it rebuilds the relations of all objects - Dungeon about
    1.1 s per tick, so 0.1 s pieces made 'cache off' take 227 s instead of 14 s). The pause is
    measured, and each tick works nine times as long: the progress display costs at most about
    10 %, small scenes still update several times a second."""
    now = time.time()
    last = getattr(op, "_tick_end", None)
    gap = max(0.0, now - last - interval) if last else 0.0       # minus the timer interval
    op._budget = min(15.0, max(0.1, 9.0 * gap, 0.7 * getattr(op, "_budget", 0.1)))
    return op._budget


def tick_done(op):
    op._tick_end = time.time()


def step_gen(gen, budget=0.1):
    """Advance a step generator of the core (yields (fraction, text[, waiting])) for about
    `budget` seconds, or until it only waits for a helper process. Returns (done, last step or
    result)."""
    t = time.time()
    last = None
    while True:
        try:
            last = next(gen)
        except StopIteration as e:
            return True, e.value
        if (len(last) > 2 and last[2]) or time.time() - t >= budget:
            return False, last


def link_text(path):
    """'linking the cache file (about N s)' from the size and the speed of the last link (run 70)."""
    import os
    try:
        est = os.path.getsize(path) / core.LINK_RATE[0]
    except OSError:
        return "linking the cache file"
    return f"linking the cache file (about {est:.0f} s)" if est >= 3 else "linking the cache file"


def show_step(context, label, st):
    s = context.scene.mecsub
    s.progress = max(0.0, min(1.0, st[0]))
    s.progress_text = f"{st[1]} ..."
    context.workspace.status_text_set(f"Renderbricker {label}: {st[1]} ... {100 * s.progress:.0f} %")
    redraw(context)


def phase(what, t0=None):
    """One line per phase in the console (run 66: the phases after the workers were invisible)."""
    print(f"RBPHASE {time.time():.1f} {what}" + (f" {time.time() - t0:.1f} s" if t0 else ""), flush=True)


def write_cache(context):
    """Copies into the cache file next to the scene (run 62). Returns a summary part."""
    import os
    s = context.scene.mecsub
    if not s.use_cache:
        n = core.uncache()                  # a scene converted with the cache before (1.9.0/1.9.1)
        return f", materials back on the meshes of {n} objects" if n else ""
    if not bpy.data.filepath:
        return ", copies kept in the scene (save the scene to use the cache file)"
    path = core.cache_path_for(bpy.data.filepath)
    t = time.time()
    n = core.write_cache(path)
    return f", {n} copies in {os.path.basename(path)} ({time.time() - t:.0f} s)" if n else ""


class _Stepped:
    """Work in small steps. From the panel (invoke) it runs modal on a timer so
    the progress bar can redraw and Esc cancels; from scripts (execute) it runs
    straight through. Subclasses: label, prepare(), item_name(), step(), finish()."""
    label = ""
    _timer = None

    def execute(self, context):
        self.cancelled = False
        if not self.prepare(context):
            return {'CANCELLED'}
        self.cache_part = None          # scripts: the cache is written in finish()
        for i in range(len(self.items)):
            try:
                self.step(context, i)
            except core.MemoryShortage as e:        # stop cleanly, processed meshes stay (run 49)
                self.cancelled = True
                self.finish(context)
                s = context.scene.mecsub
                s.summary = f"Stopped: {e}, " + s.summary
                self.report({'ERROR'}, f"Renderbricker: stopped: {e}")
                return {'CANCELLED'}
        self.finish(context)
        props.refresh_state(context)                 # before saving: it sets a scene property
        logfile.save_after_cache(self, context)
        logfile.write_log(context, self.label)
        return {'FINISHED'}

    def invoke(self, context, event):
        self.cancelled = False
        if not self.prepare(context):
            return {'CANCELLED'}
        self.i = 0
        # time estimate weighted by mesh size (a large panel takes far longer than a plate)
        w = [len(it[0].polygons) + 50 if isinstance(it, tuple) and hasattr(it[0], "polygons") else 1
             for it in self.items]
        self.cum = [0]
        for x in w:
            self.cum.append(self.cum[-1] + x)
        self.t_start = time.time()
        s = context.scene.mecsub
        s.running, s.progress, s.progress_text = True, 0.0, f"0 / {len(self.items)}"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.cancelled = True
            return self._end(context)
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}                  # block other input while working
        n = len(self.items)
        t = time.time()
        try:
            budget = work_budget(self)       # adaptive: the pause between ticks stays <= ~10 % (run 69)
            while self.i < n and time.time() - t < budget:
                self.step(context, self.i)
                self.i += 1
        except Exception as e:
            # an exception inside modal() ends the operator but left the timer running and
            # the panel locked, Esc no longer reached it (run 39) - end cleanly instead
            import traceback
            traceback.print_exc()
            if isinstance(e, core.MemoryShortage):
                self.error = str(e)
            else:
                self.error = f"{self.item_name(self.i)}: {type(e).__name__}: {e}"
            return self._end(context)
        s = context.scene.mecsub
        done, total = self.cum[self.i], self.cum[-1]
        s.progress = done / total if total else 1.0
        name = self.item_name(self.i - 1) if self.i else ""
        elapsed = time.time() - self.t_start
        left = (elapsed / done * (total - done) if done and elapsed > 10.0 and done >= 0.03 * total
                else None)                   # no wild guesses from the first meshes (run 69)
        eta = "" if left is None else f"   about {fmt_time(left)} left"
        tick_done(self)
        s.progress_text = f"{self.i} / {n}{eta}"
        context.workspace.status_text_set(f"Renderbricker {self.label}: {self.i} / {n}   {name}{eta}   (Esc: cancel)")
        redraw(context)
        if self.i >= n:
            return self._tail(context)
        return {'RUNNING_MODAL'}

    def _tail(self, context):
        """Phases after the steps (cache file ...): each is announced in the panel and the status
        bar on one timer tick and run on the next, so the text is on screen while Blender works
        (run 66: minutes of a busy cursor without any message)."""
        tail = getattr(self, "tail", None) or []
        if getattr(self, "tail_pending", None) is not None:
            text, fn = self.tail_pending
            try:
                if getattr(self, "tail_gen", None) is None:
                    self.tail_t0 = time.time()
                    r = fn(context)
                    if hasattr(r, "__next__"):          # a step generator: progress bar
                        self.tail_gen = r
                if getattr(self, "tail_gen", None) is not None:
                    done, st = step_gen(self.tail_gen, work_budget(self))
                    if not done:
                        show_step(context, self.label, st)
                        tick_done(self)
                        return {'RUNNING_MODAL'}
                    self.tail_gen = None
                    if hasattr(self, "tail_done"):
                        self.tail_done(context, st)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.tail_gen = None
                self.error = getattr(self, "error", None) or f"{text}: {type(e).__name__}: {e}"
                tail.clear()
            phase(text, getattr(self, "tail_t0", None))
            self.tail_pending = None
        if not tail:
            return self._end(context)
        text, fn = self.tail_pending = tail.pop(0)
        s = context.scene.mecsub
        s.progress_text = f"{text} ..."
        context.workspace.status_text_set(f"Renderbricker {self.label}: {text} ...")
        redraw(context)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        phase("operator end")
        s = context.scene.mecsub
        try:
            context.window_manager.event_timer_remove(self._timer)
        finally:
            s.running = False
            context.workspace.status_text_set(None)
        err = getattr(self, "error", None)
        try:
            self.finish(context)
        except Exception as e:              # the summary must never lock the panel either
            err = err or f"{type(e).__name__}: {e}"
        if err:
            what = "Stopped: " if "free memory" in err else "Stopped by an error at "
            s.summary = f"{what}{err}, " + s.summary
            self.report({'ERROR'}, "Renderbricker: " + what + err)
        props.refresh_state(context)                 # before saving: it sets a scene property
        if not err:
            logfile.save_after_cache(self, context)
        logfile.write_log(context, self.label)
        redraw(context)
        return {'FINISHED'}


class MECSUB_OT_apply(_Stepped, bpy.types.Operator):
    bl_idname = "mecsub.apply"
    bl_label = "Apply"
    bl_description = ("Set creases on each mesh once and write the subdivision into a copy of it that all its "
                      "links use (the original mesh stays in the file, unchanged). Parts already converted with "
                      "these settings are skipped - Shift+click converts all again. Esc cancels")
    bl_options = {'REGISTER', 'UNDO'}
    label = "Apply"
    force: bpy.props.BoolProperty(name="Convert all again", default=False, options={'SKIP_SAVE'})

    def collect(self, context):
        """(to do, up to date): meshes in scope, split by whether their copies already come from the
        current settings and rules. Sets the core's settings for the run."""
        s = context.scene.mecsub
        core.LEVELS = s.render_level                    # the checks run at the render level
        core.VIEW_LEVEL, core.RENDER_LEVEL = s.view_level, s.render_level
        core.SHADING = "mecabricks" if s.variant == 'A' else "geometric"
        items = list(common.by_mesh(common.targets(context)).items())
        if self.force:
            return items, []
        core.copy_index_begin()
        try:
            todo, fresh = [], []
            for me, obs in items:
                (fresh if core.up_to_date(me, s.view_level, s.render_level) else todo).append((me, obs))
        finally:
            core.copy_index_end()
        return todo, fresh

    def prepare(self, context):
        common.object_mode(context)
        s = context.scene.mecsub
        if not common.by_mesh(common.targets(context)):
            self.report({'WARNING'}, props.scope_empty_text(context))
            return False
        self.items, fresh = self.collect(context)
        for me, obs in fresh:                  # up to date: only new or switched-off links join the copy
            for ob in obs:
                ob.pop("rb_off", None)
            core.point_links(obs, me, "view")
        self.skipped = len(fresh)
        if not self.items:
            s.summary = (f"All {self.skipped} parts are already converted with these settings, "
                         f"Shift+click on Apply converts all again")
            props.refresh_state(context)
            context.scene[widgets.APPLIED_KEY] = widgets.apply_key(context)
            self.report({'INFO'}, "Renderbricker: " + s.summary)
            if not bpy.app.background:      # at the mouse - the summary line alone was overlooked (user, 2026-09-29)
                n = self.skipped

                def draw(menu, _context):
                    menu.layout.label(text=f"All {n} parts are already converted with these settings.")
                    menu.layout.label(text="Shift+click on Apply converts all again.")
                context.window_manager.popup_menu(draw, title="Nothing to do", icon='INFO')
            return False
        self.variant, self.levels = s.variant, (s.view_level, s.render_level)
        self.t0 = time.time()
        self.fans = self.unresolved = self.folds = self.done = 0
        s.problems.clear()
        s.wt_checked = False
        self.cache_part, self.tail_pending = None, None
        self.tail = [("writing the cache file" if s.use_cache and bpy.data.filepath else "finishing the copies",
                      self._cache_phase)]
        return True

    def _cache_phase(self, context):
        import os
        s = context.scene.mecsub
        self.cache_part = ""
        if not self.done:
            return None
        if s.use_cache and bpy.data.filepath:            # with a progress bar (run 69)
            self.cache_path = core.cache_path_for(bpy.data.filepath)
            return core.write_cache_steps(self.cache_path)
        try:
            self.cache_part = write_cache(context)
        except Exception as e:              # the copies stay in the scene then
            import traceback
            traceback.print_exc()
            self.cache_part = f", cache file not written: {type(e).__name__}: {e}"
        return None

    def tail_done(self, context, n):
        import os
        if getattr(self, "cache_path", None):
            self.cache_part = f", {n} copies in {os.path.basename(self.cache_path)}"

    def item_name(self, i):
        return self.items[i][0].name

    # ---- several cores (run 60): background Blenders bake, this one loads the copies
    def invoke(self, context, event):
        s = context.scene.mecsub
        self.workers = None
        if event.shift:
            self.force = True
        if s.use_cores and not bpy.app.background:
            common.object_mode(context)
            todo = self.collect(context)[0]
            jobs = core.resolve_jobs("auto", len(todo), [me for me, _obs in todo], low_memory=s.low_memory.lower())
            if jobs > 1:
                if not bpy.data.filepath:
                    self.report({'WARNING'}, "Save the scene first: Apply with several Blender processes opens it "
                                             "from disk (or switch off 'Use several Blender processes')")
                    bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', filepath=widgets.save_as_name(context))
                    return {'CANCELLED'}
                return self._start_workers(context, jobs)
        return _Stepped.invoke(self, context, event)

    def _start_workers(self, context, jobs):
        s = context.scene.mecsub
        self.cancelled = False
        if not self.prepare(context):
            return {'CANCELLED'}
        for _me, obs in self.items:
            for ob in obs:
                ob.pop("rb_off", None)
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        opts = ["--view-level", str(s.view_level), "--render-level", str(s.render_level),
                "--shading", "mecabricks" if s.variant == 'A' else "geometric"]
        self.workers = core.Workers(dict(self.items), jobs, opts, [me.name for me, _ in self.items])
        self.jobs, self.merging, self.t_start = jobs, False, time.time()
        s.running, s.progress, s.progress_text = True, 0.0, f"0 / {len(self.items)}   starting {jobs} Blenders"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not getattr(self, "workers", None):
            return _Stepped.modal(self, context, event)
        w, s, n = self.workers, context.scene.mecsub, len(self.items)
        if event.type == 'ESC' and not self.merging:
            w.kill()
            self.cancelled, self.done = True, 0
            return self._end(context)
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if self.merging:                     # shown for one redraw, then the (blocking) merge
            return self._merge(context)
        if getattr(self, "tail_pending", None) is not None or getattr(self, "in_tail", False):
            return self._tail(context)
        w.poll()
        s.progress = w.done_w / w.total_w
        elapsed = time.time() - self.t_start
        left = (elapsed / w.done_w * (w.total_w - w.done_w)
                if w.done_w and elapsed > 10.0 and w.done_w >= 0.03 * w.total_w else None)
        eta = "" if left is None else f"   about {fmt_time(left)} left"
        short = f", {w.retired} stopped for memory" if w.retired else ""
        s.progress_text = f"{len(w.done)} / {n}   {self.jobs} processes{short}{eta}"
        context.workspace.status_text_set(
            f"Renderbricker Apply in {self.jobs} Blender processes: {len(w.done)} / {n}{eta}   (Esc: cancel)")
        if not w.running():
            more = w.next_round()           # meshes of stopped or crashed workers: another round (run 120)
            if more:
                self.jobs = more
                redraw(context)
                return {'RUNNING_MODAL'}
            phase(f"workers ({self.jobs} Blenders)", self.t_start)
            self.merging = True
            what = ("writing the cache file and linking it" if s.use_cache and bpy.data.filepath
                    else "loading the copies into the scene")
            s.progress_text = f"{len(w.done)} / {n}   {what} ..."
            context.workspace.status_text_set(f"Renderbricker Apply: {what} ...")
        redraw(context)
        return {'RUNNING_MODAL'}

    def _merge(self, context):
        import os
        s = context.scene.mecsub
        try:
            def on_mesh(me, obs, rep):          # (a new function per tick; the generator keeps the first)
                self.tpoints = getattr(self, "tpoints", 0) + rep.get("t_verts", 0)
                if rep.get("flipped"):
                    self.folds += rep["flipped"]
                    p = s.problems.add(); p.obj = obs[0].name; p.info = f"{rep['flipped']} folded faces left"
                self.done += 1
            t0 = time.time()
            if s.use_cache and bpy.data.filepath:    # straight into the cache, never loaded here (run 66)
                path = core.cache_path_for(bpy.data.filepath)
                if getattr(self, "merge_gen", None) is None:
                    self.merge_gen, self.merge_t0 = self.workers.merge_to_cache_steps(path, on_mesh), t0
                done, st = step_gen(self.merge_gen, work_budget(self, 0.25))
                if not done:
                    show_step(context, "Apply", st)
                    tick_done(self)
                    return {'RUNNING_MODAL'}
                _reps, rest, n = st
                self.merge_gen = None
                self.cache_part = f", {n} copies in {os.path.basename(path)}"
                if not rest:
                    self.tail = []
                phase("cache file written and linked", self.merge_t0)
            else:
                _reps, rest = self.workers.merge(on_mesh)
                phase("loading the copies into the scene", t0)
            items = dict(self.items)
            for me in rest:                  # a worker failed: these meshes are done here
                on_mesh(me, items[me], core.process(me, items[me]))
            if self.workers.skipped:
                sk = self.workers.skipped
                self.error = f"{len(sk)} meshes skipped for memory ({', '.join(sk[:3])})"
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.workers.kill()
            self.merge_gen = None
            self.error = f"{type(e).__name__}: {e}"
            return self._end(context)
        self.merging, self.in_tail = False, True
        return self._tail(context)

    def step(self, context, i):
        s = context.scene.mecsub
        me, obs = self.items[i]
        core.check_memory(me, max(self.levels))   # stop cleanly instead of crashing (run 49)
        for ob in obs:
            ob.pop("rb_off", None)
        rep = core.process(me, obs)
        self.fans += rep.get("t_fans_creased", 0)
        self.unresolved += rep.get("t_fans_unresolved", 0)
        self.tpoints = getattr(self, "tpoints", 0) + rep.get("t_verts", 0)
        if rep.get("flipped"):
            self.folds += rep["flipped"]
            p = s.problems.add(); p.obj = obs[0].name; p.info = f"{rep['flipped']} folded faces left"
        self.done += 1

    def finish(self, context):
        s = context.scene.mecsub
        n = len(self.items)
        objs = sum(len(o) for _, o in self.items[:self.done])
        cores = f", {self.jobs} Blender processes" if getattr(self, "workers", None) else ""
        skipped = getattr(self, "skipped", 0)
        s.summary = ((f"Cancelled after {self.done} of {n} meshes, " if self.cancelled else f"{n} mesh{'' if n == 1 else 'es'}, ")
                     + (f"{skipped} already up to date (skipped), " if skipped else "")
                     + f"{objs} objects, {time.time() - self.t0:.0f} s, variant {self.variant}, "
                     + f"viewport {self.levels[0]} / render {self.levels[1]}{cores}"
                     + (f", T points pinned {getattr(self, 'tpoints', 0)}" if core.METHOD == "weld"
                        else f", T fans creased {self.fans}")
                     + (f", unresolved {self.unresolved}" if self.unresolved else "")
                     + (f", folds left {self.folds}" if self.folds else ""))
        if self.done:
            if getattr(self, "cache_part", None) is None:     # scripts (execute): no tail phases
                try:
                    self.cache_part = write_cache(context)
                except Exception as e:              # the copies stay in the scene then
                    import traceback
                    traceback.print_exc()
                    self.cache_part = f", cache file not written: {type(e).__name__}: {e}"
            s.summary += self.cache_part
        if not self.cancelled:
            context.scene[widgets.APPLIED_KEY] = widgets.apply_key(context)
        self.report({'WARNING'} if self.cancelled else {'INFO'}, "Renderbricker: " + s.summary)


class MECSUB_OT_check(_Stepped, bpy.types.Operator):
    bl_idname = "mecsub.check"
    bl_label = "Check"
    bl_description = "Look for folded faces and seam gaps in the subdivided render copies. Esc cancels"
    label = "Check"

    def prepare(self, context):
        common.object_mode(context)
        s = context.scene.mecsub
        self.items = list(common.by_mesh(common.targets(context)).items())
        s.problems.clear()
        self.checked = self.bad = 0
        return True

    def item_name(self, i):
        return self.items[i][0].name

    def step(self, context, i):
        s = context.scene.mecsub
        me, obs = self.items[i]
        cp = core.copy_of(me, "render") or core.copy_of(me, "view")
        if cp is None:
            return
        self.checked += 1
        lv = int(cp.get("rb_level", 2))
        f = len(core.copy_folds(me, cp))
        if cp.get("rb_method") == "weld":          # rules 3.0: seams are welded, gaps only at T points
            gv = ge = core.weld_gap(core.original_of(me), cp)
        else:
            gv, ge = common.seam_gaps(me, cp, lv)
        if f or gv > 1e-3 or ge > 1e-3:
            self.bad += 1
            p = s.problems.add(); p.obj = obs[0].name
            p.info = f"folds {f}, seam gap {max(gv, ge):.3f}"

    def finish(self, context):
        s = context.scene.mecsub
        s.summary = (("Check cancelled: " if self.cancelled else "Check: ")
                     + f"{self.checked} meshes, {self.bad} with problems")
        s.wt_checked, s.wt_bad = not self.cancelled and self.checked > 0, self.bad
        self.report({'INFO'} if not self.bad else {'WARNING'}, s.summary)


class MECSUB_OT_levels(_Stepped, bpy.types.Operator):
    bl_idname = "mecsub.levels"
    bl_label = "Set levels"
    bl_description = ("Point the links to the copies of the chosen viewport / render level, computing copies "
                      "that do not exist yet (no rules run). Esc cancels")
    bl_options = {'REGISTER', 'UNDO'}
    label = "Levels"

    def prepare(self, context):
        common.object_mode(context)
        s = context.scene.mecsub
        self.items = props._processed_groups(context)         # builds the copy index (run 72)
        self.view, self.render = s.view_level, s.render_level
        self.baked = 0
        self.t0 = time.time()
        self.cache_part, self.tail_pending = None, None
        need = any(core.missing_levels(core.original_of(me), self.view, self.render) for me, _ in self.items)
        self.tail = [("writing the cache file", self._cache_phase)] if need else []   # a pure switch writes nothing
        if not self.items:
            core.copy_index_end()
        return bool(self.items)

    def _cache_phase(self, context):
        try:
            self.cache_part = write_cache(context) if self.baked else ""
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.cache_part = f", cache file not written: {type(e).__name__}: {e}"

    def item_name(self, i):
        return self.items[i][0].name

    def step(self, context, i):
        me, obs = self.items[i]
        if core.missing_levels(core.original_of(me), self.view, self.render):
            core.check_memory(me, max(self.view, self.render))
        self.baked += core.set_levels(me, self.view, self.render, obs)
        if i == len(self.items) - 1:
            core.copy_index_end()                        # the cache write builds its own

    def finish(self, context):
        core.copy_index_end()
        s = context.scene.mecsub
        s.summary = ((f"Levels cancelled after {self.i if hasattr(self, 'i') else 0} meshes, " if self.cancelled else "")
                     + f"viewport {self.view} / render {self.render}, {len(self.items)} meshes, "
                     + f"{self.baked} copies computed, {time.time() - self.t0:.0f} s")
        if self.baked and getattr(self, "cache_part", None) is None:     # scripts: no tail phases
            try:
                self.cache_part = write_cache(context)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.cache_part = f", cache file not written: {type(e).__name__}: {e}"
        s.summary += getattr(self, "cache_part", None) or ""
