"""Subdivision ON/OFF, Remove, the cache file (move, copy, switch), select, Convert headless."""
import time
import bpy
from bpy.props import StringProperty
from . import rbcore as core
from . import common, convert, logfile, props, widgets


class MECSUB_OT_toggle(bpy.types.Operator):
    bl_idname = "mecsub.toggle"
    bl_label = "Subdivision on/off"
    bl_description = "Switch the links between the subdivided copy and the original mesh (viewport and render)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        common.object_mode(context)
        groups = [(me, obs) for me, obs in common.by_mesh(common.targets(context)).items() if core.all_copies(me)]
        if not groups:
            self.report({'WARNING'}, "No subdivided meshes in scope")
            return {'CANCELLED'}
        on = any(o.get("rb_off") for _, obs in groups for o in obs)      # something is off: switch all on
        for me, obs in groups:
            for o in obs:
                if on:
                    o.pop("rb_off", None)
                    core.point_links([o], me, "view")
                    context.scene.mecsub.wt_compared = True
                else:
                    o["rb_off"] = True
                    o.data = me
        st = props.refresh_state(context)
        self.report({'INFO'}, f"Renderbricker: subdivision {'on' if on else 'off'}"
                              + (" (other objects outside the scope differ)" if st == "MIXED" else ""))
        convert.redraw(context)
        return {'FINISHED'}


class MECSUB_OT_remove(bpy.types.Operator):
    bl_idname = "mecsub.remove"
    bl_label = "Remove"
    bl_description = "Links back to the original meshes; copies and crease attributes removed (plain import)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        common.object_mode(context)
        obs = common.targets(context)
        groups = common.by_mesh(obs)
        for me, gobs in groups.items():
            for o in gobs:
                core.unlink_instance(o)
                o.pop("rb_off", None)
                o.data = me
        for me in groups:
            copies = core.all_copies(me)
            if any(o.data in copies for o in bpy.data.objects if o.type == 'MESH'):
                continue            # still used by objects outside the scope
            core.drop_cache_links(me)      # object materials back to the mesh, cache hold released
            for c in copies:
                bpy.data.meshes.remove(c)
            core.remove_master(me)
            for a in ("crease_edge", "crease_vert"):
                if me.attributes.get(a):
                    me.attributes.remove(me.attributes[a])
            for k in ("rb_view", "rb_render"):
                me.pop(k, None)
            me.use_fake_user = False
        core.cleanup_libraries()
        context.scene.mecsub.summary = f"Removed from {len(obs)} objects"
        context.scene.mecsub.problems.clear()
        props.refresh_state(context)
        return {'FINISHED'}


class MECSUB_OT_move_cache(bpy.types.Operator):
    bl_idname = "mecsub.move_cache"
    bl_label = "Move cache to this scene"
    bl_description = ("Move the cache file next to this scene and rename it <scene>_rbcache.blend, update the "
                      "link and save the scene (after Save As under another name or in another folder). The "
                      "scene file the cache belonged to before then shows its original meshes")

    @classmethod
    def poll(cls, context):
        st = core.cache_state()
        return bool(bpy.data.filepath) and st is not None and st[1] != st[2]

    def invoke(self, context, event):
        import os
        st = core.cache_state()
        if os.path.exists(st[2]):
            return context.window_manager.invoke_confirm(
                self, event, title="Move cache",
                message=f"{os.path.basename(st[2])} exists already and will be replaced. Continue?")
        return self.execute(context)

    def execute(self, context):
        s = context.scene.mecsub
        if bpy.app.background or context.window is None:     # scripts: no timer, straight through
            self.ticks = 1
            self._timer = None
            return self.modal(context, type("E", (), {"type": 'TIMER'})())
        st = core.cache_state()
        s.running, s.progress = True, 0.5
        s.progress_text = f"moving the cache, {convert.link_text(st[1] if st[3] else st[2])} ..."
        context.workspace.status_text_set(f"Renderbricker: {s.progress_text}")
        convert.redraw(context)
        self.ticks = 0
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        import os
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        self.ticks += 1
        if self.ticks < 2:                     # the text is on screen first
            return {'RUNNING_MODAL'}
        s = context.scene.mecsub
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
        try:
            old, new = core.move_cache()
            bpy.ops.wm.save_mainfile()
            s.summary = f"Cache moved: {os.path.basename(old)} -> {os.path.basename(new)}, scene saved"
            err = False
        except Exception as e:
            s.summary, err = f"Moving the cache failed: {e}", True
        s.running = False
        context.workspace.status_text_set(None)
        self.report({'ERROR'} if err else {'INFO'}, "Renderbricker: " + s.summary)
        convert.redraw(context)
        return {'CANCELLED'} if err else {'FINISHED'}


class MECSUB_OT_cache_switch(bpy.types.Operator):
    bl_idname = "mecsub.cache_switch"
    bl_label = "Switch the cache"
    bl_description = ("Cache on: write the copies into <scene>_rbcache.blend and link them. Cache off: take the "
                      "copies from the cache into the scene file")
    target: bpy.props.BoolProperty()
    _timer = None

    def invoke(self, context, event):
        import os
        n = len([m for m in bpy.data.meshes if m.get("rb_original") and m.library is None])
        if self.target:
            if not bpy.data.filepath:
                self.report({'WARNING'}, "Save the scene first: the cache file lies next to it")
                bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', filepath=widgets.save_as_name(context))
                return {'CANCELLED'}
            msg = (f"Write the {n} subdivided copies into {os.path.basename(core.cache_path_for(bpy.data.filepath))} "
                   f"and link them? The scene file gets about as small as the import")
        else:
            st = core.cache_state()
            if st is None:                     # no cache linked: only the setting
                return self.execute(context)
            size = os.path.getsize(st[1]) / 1e9 if st[3] else 0
            msg = (f"Take the subdivided copies from {os.path.basename(st[1])} into the scene file? "
                   f"The scene file grows by about {size:.1f} GB (compressed); the cache file stays on disk")
        return context.window_manager.invoke_confirm(self, event, title="Cache file", message=msg)

    def execute(self, context):
        s = context.scene.mecsub
        self.phase = 0
        s.running, s.progress, s.progress_text = True, 0.0, ("writing the cache file" if self.target
                                                             else "taking the copies into the scene")
        context.workspace.status_text_set(f"Renderbricker: {s.progress_text} ...")
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        convert.redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if self.phase == 0:                    # the text is on screen now
            self.phase = 1
            return {'RUNNING_MODAL'}
        s = context.scene.mecsub
        if self.phase == 1:                    # stepped, with a progress bar (run 69)
            if not hasattr(self, "gen"):
                self.t0 = time.time()
                try:
                    if self.target:
                        props._SWITCHING[0] = True
                        try:
                            s.use_cache = True          # write_cache follows the setting
                        finally:
                            props._SWITCHING[0] = False
                        self.path = core.cache_path_for(bpy.data.filepath)
                        self.gen = core.write_cache_steps(self.path)
                    else:
                        self.gen = core.embed_cache_steps()
                except Exception as e:
                    self.gen, self.fail = None, e
            if getattr(self, "gen", None) is not None:
                try:
                    done, st = convert.step_gen(self.gen, convert.work_budget(self, 0.1))
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    done, st, self.fail = True, None, e
                if not done:
                    convert.show_step(context, "cache", st)
                    convert.tick_done(self)
                    return {'RUNNING_MODAL'}
                self.result = st
            self.phase = 2
        t0 = self.t0
        err = None
        def setting(value):
            props._SWITCHING[0] = True
            try:
                s.use_cache = value
            finally:
                props._SWITCHING[0] = False
        import os
        if getattr(self, "fail", None) is not None:
            err = f"{type(self.fail).__name__}: {self.fail}"
            text = f"Cache switch failed: {err}"
        elif self.target:
            text = f"Cache on, {self.result} copies in {os.path.basename(self.path)} ({time.time() - t0:.0f} s)"
        else:
            text = f"Cache off: {self.result} copies taken into the scene - save the scene to keep them"
        convert.phase("cache on" if self.target else "cache off", t0)
        context.window_manager.event_timer_remove(self._timer)
        setting(self.target if err is None else not self.target)
        s.running = False
        s.summary = text if self.target else text + f" ({time.time() - t0:.0f} s)"
        context.workspace.status_text_set(None)
        self.report({'ERROR'} if err else {'INFO'}, "Renderbricker: " + s.summary)
        convert.redraw(context)
        return {'FINISHED'}


class MECSUB_OT_copy_cache(bpy.types.Operator):
    bl_idname = "mecsub.copy_cache"
    bl_label = "Copy cache to this scene"
    bl_description = ("Copy the cache file next to this scene as <scene>_rbcache.blend, link the copy and save "
                      "the scene - both scene files keep a cache of their own (needs the disk space of a "
                      "second cache). Esc cancels")
    _timer = None

    @classmethod
    def poll(cls, context):
        st = core.cache_state()
        return bool(bpy.data.filepath) and st is not None and st[1] != st[2] and st[3]

    def invoke(self, context, event):
        import os
        st = core.cache_state()
        size = os.path.getsize(st[1]) / 1e9
        extra = (f" {os.path.basename(st[2])} exists already and will be replaced." if os.path.exists(st[2]) else "")
        return context.window_manager.invoke_confirm(
            self, event, title="Copy cache",
            message=f"Copy {os.path.basename(st[1])} ({size:.1f} GB) next to this scene?{extra}")

    def execute(self, context):
        import threading
        st = core.cache_state()
        self.lib, self.src, self.dst = st[0], st[1], st[2]
        self.tmp = self.dst + ".copying"
        self.total = max(1, __import__("os").path.getsize(self.src))
        self.done_bytes, self.failed, self.stop = 0, None, False

        def copy():                              # plain file copy in a thread, no Blender data
            try:
                with open(self.src, "rb") as fi, open(self.tmp, "wb") as fo:
                    while not self.stop:
                        b = fi.read(16 << 20)
                        if not b:
                            break
                        fo.write(b)
                        self.done_bytes += len(b)
            except Exception as e:
                self.failed = e

        self.thread = threading.Thread(target=copy, daemon=True)
        self.thread.start()
        s = context.scene.mecsub
        s.running, s.progress, s.progress_text = True, 0.0, "copying the cache file"
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.25, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        import os
        s = context.scene.mecsub
        if event.type == 'ESC':
            self.stop = True
            self.thread.join()
            if os.path.exists(self.tmp):
                os.remove(self.tmp)
            return self._end(context, "Copy of the cache cancelled")
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        if not getattr(self, "linking", False):      # the link text stays for its tick
            s.progress = self.done_bytes / self.total
            s.progress_text = f"copying the cache file {self.done_bytes / 1e9:.1f} / {self.total / 1e9:.1f} GB"
            context.workspace.status_text_set(f"Renderbricker: {s.progress_text}   (Esc: cancel)")
            convert.redraw(context)
        if self.thread.is_alive():
            return {'RUNNING_MODAL'}
        if self.failed is not None:
            if os.path.exists(self.tmp):
                os.remove(self.tmp)
            return self._end(context, f"Copy of the cache failed: {self.failed}", error=True)
        if not getattr(self, "linking", False):      # one tick with the text on screen first
            self.linking = True
            s.progress = 0.99
            s.progress_text = convert.link_text(self.tmp) + " ..."
            context.workspace.status_text_set(f"Renderbricker: {s.progress_text}")
            convert.redraw(context)
            return {'RUNNING_MODAL'}
        os.replace(self.tmp, self.dst)
        core.relink_cache(self.lib, self.dst)
        bpy.ops.wm.save_mainfile()
        return self._end(context, f"Cache copied: {os.path.basename(self.src)} -> {os.path.basename(self.dst)}, "
                                  f"scene saved (the other scene keeps {os.path.basename(self.src)})")

    def _end(self, context, text, error=False):
        s = context.scene.mecsub
        context.window_manager.event_timer_remove(self._timer)
        s.running = False
        context.workspace.status_text_set(None)
        s.summary = text
        self.report({'ERROR'} if error else {'INFO'}, "Renderbricker: " + text)
        convert.redraw(context)
        return {'CANCELLED'} if error else {'FINISHED'}


class MECSUB_OT_select(bpy.types.Operator):
    bl_idname = "mecsub.select"
    bl_label = "Select"
    bl_description = "Select and frame this object"
    obj: StringProperty()

    def execute(self, context):
        ob = context.scene.objects.get(self.obj)
        if not ob:
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True); context.view_layer.objects.active = ob
        try:
            bpy.ops.view3d.view_selected()
        except RuntimeError:
            pass
        return {'FINISHED'}


class MECSUB_OT_headless(bpy.types.Operator):
    bl_idname = "mecsub.headless"
    bl_label = "Convert headless"
    bl_description = ("Save the scene, write a start script next to it (.bat on Windows, .command on macOS, .sh on "
                      "Linux) and run it in a terminal: Blender converts the whole scene in the background with several "
                      "Blender processes and saves the result as <scene>_subdiv_<add-on version>.blend. The open scene is not changed")

    def invoke(self, context, event):
        if not bpy.data.filepath:
            self.report({'WARNING'}, "Save the scene first, then press Convert headless again")
            return bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', filepath=widgets.save_as_name(context))
        return context.window_manager.invoke_confirm(
            self, event, title="Convert headless",
            message="The scene is saved now and converted in a console window. Continue?")

    def execute(self, context):
        import os
        common.object_mode(context)
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        s = context.scene.mecsub
        blend = bpy.data.filepath
        folder, stem = os.path.dirname(blend), os.path.splitext(os.path.basename(blend))[0]
        tag = common.VERSION.replace(".", "-")
        name, k = f"{stem}_subdiv_{tag}", 1
        while os.path.exists(os.path.join(folder, name + ".blend")):   # never overwrite an earlier result
            k += 1
            name = f"{stem}_subdiv_{tag}_{k}"
        out = os.path.join(folder, name + ".blend")
        args = ["-b", "--factory-startup", blend, "--python", os.path.join(os.path.dirname(__file__), "rbcore", "run.py"),
                "--", out, "--view-level", str(s.view_level), "--render-level", str(s.render_level),
                "--shading", "mecabricks" if s.variant == 'A' else "geometric", "--jobs", "auto",
                "--low-memory", s.low_memory.lower()]
        if s.use_cache:
            args += ["--cache", core.cache_path_for(out)]
        if s.use_log:
            args += ["--log", logfile.log_path()]
        script = write_headless_script(os.path.join(folder, name), stem, blend, out, args)
        how = start_script(script)
        s.summary = (f"Headless conversion started in a terminal: {os.path.basename(script)}, result: {os.path.basename(out)}"
                     if how else f"Start script written, run it in a terminal: {script}")
        self.report({'INFO'}, "Renderbricker: " + s.summary)
        return {'FINISHED'}


# lines of the conversion worth showing in the terminal (the rest is Blender's own output)
HEADLESS_SHOW = ("PROGRESS", "SKIP", "SAVED", "Error", "Traceback", "MESHES", "JOBS", "MERGE", "CACHE", "CAMERA",
                 "RETIRE", "CLEAN", "PEAK", "MEMORY", "SEGMENT")


def write_headless_script(base, stem, blend, out, args):
    """Start script for the headless conversion: <base>.bat (Windows), .command (macOS), .sh (Linux)."""
    import os, sys, shlex
    blender = bpy.app.binary_path
    head = f"Renderbricker {common.VERSION}: converting"
    if sys.platform.startswith("win"):
        q = lambda x: '"' + x.replace("%", "%%") + '"'
        lines = ["@echo off", "chcp 65001 >nul", f"title Renderbricker {common.VERSION} headless: {stem}",
                 f"echo {head} {q(blend)}", f"echo Result: {q(out)}", "echo.",
                 " ".join([q(blender)] + [q(a) if (" " in a or os.sep in a) else a for a in args])
                 + " 2>&1 | findstr /B " + " ".join(f'/C:"{w}"' for w in HEADLESS_SHOW),
                 "echo.", f"if exist {q(out)} (echo Done: {q(out)}) else (echo FAILED - no result written)", "pause"]
        path = base + ".bat"
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")
        return path
    path = base + (".command" if sys.platform == "darwin" else ".sh")
    lines = ["#!/bin/sh", f"# Renderbricker {common.VERSION} headless conversion of {stem}",
             f"echo {shlex.quote(head + ' ' + blend)}", f"echo {shlex.quote('Result: ' + out)}", "echo",
             " ".join(shlex.quote(a) for a in [blender] + args)
             + " 2>&1 | grep -E " + shlex.quote("^(" + "|".join(HEADLESS_SHOW) + ")"),
             "echo", f"if [ -f {shlex.quote(out)} ]; then echo {shlex.quote('Done: ' + out)}; "
             "else echo 'FAILED - no result written'; fi",
             "printf 'Press Enter to close. '", "read _"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o755)
    return path


def start_script(path):
    """Run a start script in a terminal window. Windows: its own console; macOS: Terminal; Linux: the
    first terminal found. Returns how it was started, or None when no terminal was found (the user
    runs it by hand)."""
    import os, sys, shutil, subprocess
    if sys.platform.startswith("win"):
        os.startfile(path)
        return "console"
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Terminal", path])
        return "Terminal"
    for term, pre in (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
                      ("xfce4-terminal", ["-x"]), ("kitty", []), ("alacritty", ["-e"]), ("xterm", ["-e"])):
        exe = shutil.which(term)
        if exe:
            subprocess.Popen([exe] + pre + [path], start_new_session=True)
            return term
    return None
