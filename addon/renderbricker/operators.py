"""Subdivision ON/OFF, Remove, the cache file (move, copy, switch), select, Convert headless."""
import time
import bpy
from bpy.props import EnumProperty, StringProperty
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
    bl_options = {'REGISTER', 'UNDO'}
    # Remove All (UPDATES #33; up to 1.2.7 the scope All): the whole file, after a question - it reaches every
    # model in it
    whole: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.whole:
            return ("Every converted part of the file back to its import - all models, in every scene; copies of "
                    "parts deleted meanwhile go too and the cache file is released")
        return ("The parts in scope back to their import: links on the original meshes, copies and crease "
                "attributes removed")

    def invoke(self, context, event):
        if self.whole:
            return context.window_manager.invoke_confirm(
                self, event, title="Remove All",
                message="Take every converted part of this file back to its import - all models, in every scene?",
                confirm_text="Remove All", icon='WARNING')
        return self.execute(context)

    def execute(self, context):
        common.object_mode(context)
        # the whole file (UPDATES #15, run 220): objects of every scene, and the copies of parts whose objects were
        # deleted - before, they stayed with a fake user and kept the cache file linked
        whole = self.whole
        if whole:
            obs = [o for o in bpy.data.objects if o.type == 'MESH' and o.data is not None and o.library is None
                   and not core.is_master(o) and o.name != core.WORK_NAME]
        else:
            obs = common.targets(context)
        groups = common.by_mesh(obs)
        for me, gobs in groups.items():
            for o in gobs:
                core.unlink_instance(o)
                o.pop("rb_off", None)
                o.pop("rb_on", None)
                o.data = me
        originals = set(groups)
        if whole:
            for m in bpy.data.meshes:
                if m.library is not None:
                    continue
                if m.get("rb_original"):
                    o = bpy.data.meshes.get((m["rb_original"], None))
                    if o is not None:
                        originals.add(o)
                elif any(k.startswith("rb_") for k in m.keys()):
                    originals.add(m)
        removed = 0
        for me in originals:
            copies = core.all_copies(me)
            if not whole and any(o.data in copies for o in bpy.data.objects if o.type == 'MESH'):
                continue            # still used by objects outside the scope
            core.drop_cache_links(me)      # object materials back to the mesh, cache hold released
            core.restore_shader_radius(me)         # the importer's own Bevel value again (UPDATES #43)
            for c in copies:
                bpy.data.meshes.remove(c)
                removed += 1
            core.remove_master(me)
            for a in ("crease_edge", "crease_vert"):
                if me.attributes.get(a):
                    me.attributes.remove(me.attributes[a])
            for k in [k for k in me.keys() if k.startswith("rb_")]:
                me.pop(k, None)
            me.use_fake_user = False
        if whole:                          # copies whose original is gone, and the work scene
            for m in [m for m in bpy.data.meshes if m.library is None and m.get("rb_original") and m.users <= int(m.use_fake_user)]:
                bpy.data.meshes.remove(m)
                removed += 1
            ws = bpy.data.scenes.get(core.WORK_SCENE)
            if ws is not None and ws != context.scene:
                core.remove_scene(ws)
        core.drop_unused_maps()            # bevel maps baked for copies that are gone now (UPDATES #40)
        core.drop_unused_switches()        # ... and the switches of bevelled copies (UPDATES #43)
        core.cleanup_libraries()
        left = sum(1 for m in bpy.data.meshes if m.get("rb_original"))
        context.scene.mecsub.summary = (f"Removed from {len(obs)} objects" + (" in the whole file" if whole else "")
                                        + f", {removed} copies deleted"
                                        + (f"; {left} copies stay (used outside the scope)" if left else ""))
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


# ---------------------------------------------------------------- the cache after Save As (UPDATES #41)
# Save As under another name or in another folder leaves the cache file with the old scene. The panel has shown
# "Cache of another scene" with Move / Copy since run 63 - but only to those who look there. Now the add-on asks
# right after such a save (maintainer 2026-10-11: "Wenn der User selbst Save as über das offizielle Menü
# ausführt, kann man das auch abfangen, sobald er einen anderen Ort wählt?" - "so bauen, mit Frage nach Save As").
# It asks and does not choose: Move leaves the old scene without its cache, Copy takes the disk space twice.
# Save Copy does not change the open scene and asks nothing. Asked once per scene file and session; "Not now"
# leaves the box in the panel.
_CACHE_ASKED = set()        # (cache file, where it should lie) the question was shown for


def cache_question_due():
    """(cache file, where it should lie) when the scene links a cache file that exists and belongs to another
    scene file; None otherwise."""
    if not bpy.data.filepath:
        return None
    st = core.cache_state()
    if st is None or not st[3] or st[1] == st[2]:
        return None
    return st[1], st[2]


@bpy.app.handlers.persistent
def cache_after_save(*_args):
    """save_post: ask about the cache when the scene was saved somewhere else. A handler cannot open a dialog, a
    timer right after it can. Not while a run of the add-on saves, not in the background."""
    if bpy.app.background:
        return
    due = cache_question_due()
    if due is None or due in _CACHE_ASKED:
        return
    if any(getattr(sc, "mecsub", None) is not None and sc.mecsub.running for sc in bpy.data.scenes):
        return
    _CACHE_ASKED.add(due)
    bpy.app.timers.register(_ask_cache, first_interval=0.3)


def _ask_cache():
    from . import edit
    if cache_question_due() is not None:
        try:
            with bpy.context.temp_override(**edit._context_override()):
                bpy.ops.mecsub.cache_after_save('INVOKE_DEFAULT')
        except Exception:
            import traceback
            traceback.print_exc()
    return None


class MECSUB_OT_cache_after_save(bpy.types.Operator):
    bl_idname = "mecsub.cache_after_save"
    bl_label = "Cache file"
    bl_description = ("The scene was saved under another name or in another folder: move or copy the cache file "
                      "to it, or decide later")
    bl_options = {'INTERNAL'}
    choice: EnumProperty(
        name="Cache",
        items=[('MOVE', "Move cache here", "The cache file goes to this scene; the scene file it belonged to "
                                           "before then shows its original meshes"),
               ('COPY', "Copy cache here", "Both scene files keep a cache of their own - needs the disk space "
                                           "of a second cache"),
               ('LATER', "Not now", "Nothing happens; the panel keeps offering Move cache here and Copy cache "
                                    "here")],
        default='LATER', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return cache_question_due() is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=440, title="Renderbricker: the cache file")

    def draw(self, context):
        import os
        due = cache_question_due()
        L = self.layout
        col = L.column(align=True)
        col.label(text=f"The scene was saved as {os.path.basename(bpy.data.filepath)}.")
        if due:                             # the names on lines of their own: long ones are not cut short
            col.label(text="Its smoothed parts are still in the cache file of the scene it was before:")
            col.label(text=os.path.basename(due[0]))
        L.column(align=True).prop(self, "choice", expand=True)
        col = L.column(align=True)
        col.scale_y = 0.8
        col.label(text="Move: the scene it was before then shows its original meshes.")
        col.label(text="Copy: both scenes keep a cache - twice the disk space.")

    def execute(self, context):
        if self.choice == 'MOVE':
            bpy.ops.mecsub.move_cache('INVOKE_DEFAULT')
        elif self.choice == 'COPY':         # its own question only when a file would be replaced
            import os
            due = cache_question_due()
            bpy.ops.mecsub.copy_cache('INVOKE_DEFAULT' if due and os.path.exists(due[1]) else 'EXEC_DEFAULT')
        else:
            context.scene.mecsub.summary = ("The cache file still belongs to the scene this one was saved from - "
                                            "the panel offers Move cache here and Copy cache here")
            convert.redraw(context)
        return {'FINISHED'}


class MECSUB_OT_cache_switch(bpy.types.Operator):
    bl_idname = "mecsub.cache_switch"
    bl_label = "Switch the cache"
    bl_description = ("Cache on: write the copies into <scene>_rbcache.blend and link them. Cache off: take the "
                      "copies from the cache into the scene file")
    target: bpy.props.BoolProperty()
    save_after: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})    # automatic update after a save (#18)
    _timer = None

    def invoke(self, context, event):
        import os
        n = len([m for m in bpy.data.meshes if m.get("rb_original") and m.library is None])
        if self.target:
            if not bpy.data.filepath:
                self.report({'INFO'}, "Save the scene first: the cache file lies next to it - continues after saving")
                widgets.continue_after_save(context, "mecsub.cache_switch", target=True)
                bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', filepath=widgets.save_as_name(context))
                return {'CANCELLED'}
            from . import edit
            left = edit.uncached(context) if core.cache_state() is not None else []
            if left:                            # "Update cache" after editing parts (UPDATES #18)
                msg = (f"Write the {len(left)} edited part{'s' if len(left) != 1 else ''} into "
                       f"{os.path.basename(core.cache_path_for(bpy.data.filepath))}? The other copies are carried "
                       f"over unchanged, nothing is converted again")
            else:
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
        if self.save_after:                    # the automatic update after a save: save the linked state too
            from . import edit
            try:
                if err is None and bpy.data.filepath:
                    s.summary = "Edited parts written into the cache, scene saved - " + s.summary
                    bpy.ops.wm.save_mainfile()
            finally:
                edit._CACHING[0] = False
        self.report({'ERROR'} if err else {'INFO'}, "Renderbricker: " + s.summary)
        convert.redraw(context)
        return {'FINISHED'}


class MECSUB_OT_render_scene(bpy.types.Operator):
    bl_idname = "mecsub.render_scene"
    bl_label = "Save render scene"
    bl_description = ("Write <scene>_render.blend next to the scene, for rendering on a computer without Renderbricker "
                      "(a render farm): every converted part at the render level, the parts and their materials inside "
                      "the file - it needs neither the add-on nor the cache file. This scene stays as it is; click "
                      "again after changes. Esc cancels")
    _timer = None

    @classmethod
    def poll(cls, context):
        if not bpy.data.filepath:
            cls.poll_message_set("Save the scene first - the render scene is written next to it")
            return False
        return True

    def invoke(self, context, event):
        import os
        if not self._converted():
            return self.execute(context)
        out = core.render_scene_path(bpy.data.filepath)
        st = core.cache_state()
        size = os.path.getsize(st[1]) / 1e9 if st is not None and st[3] else 0
        msg = (f"Write {os.path.basename(out)} with all parts at the render level inside"
               + (f" (about {size:.1f} GB)" if size >= 0.1 else "") + "? It renders without Renderbricker; this "
               "scene stays as it is" + (". The existing file is replaced" if os.path.exists(out) else "")
               + (". Edges changed since the last Apply: the file would show the old edges - Apply first"
                  if widgets.edges_pending(context) == "convert" else ""))
        return context.window_manager.invoke_confirm(self, event, title="Render scene", message=msg)

    @staticmethod
    def _converted():
        return any(m.get("rb_original") for m in bpy.data.meshes)

    def execute(self, context):
        from . import edit
        if not self._converted():
            self.report({'WARNING'}, "Nothing converted yet - Apply first")
            return {'CANCELLED'}
        common.object_mode(context)
        s = context.scene.mecsub
        self.t0, self.fail, self.result = time.time(), None, None
        edit._CACHING[0] = True                 # the copy written for the helper Blender is no save of the scene
        self.gen = core.render_scene_steps()
        if bpy.app.background or context.window is None:     # scripts: no timer, straight through
            try:
                self.result = core.run_steps(self.gen)
            except Exception as e:
                self.fail = e
            return self._end(context)
        s.running, s.progress, s.progress_text = True, 0.0, "preparing the render scene"
        context.workspace.status_text_set(f"Renderbricker: {s.progress_text} ...")
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        convert.redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'ESC':
            self.gen.close()                    # stops the helper Blender, removes its working files
            self.fail = "stopped"
            return self._end(context)
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        try:
            done, st = convert.step_gen(self.gen, convert.work_budget(self, 0.1))
        except Exception as e:
            import traceback
            traceback.print_exc()
            done, st, self.fail = True, None, e
        if not done:
            convert.show_step(context, "render scene", st)
            convert.tick_done(self)
            return {'RUNNING_MODAL'}
        self.result = st
        return self._end(context)

    def _end(self, context):
        import os
        from . import edit
        edit._CACHING[0] = False
        s = context.scene.mecsub
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
        s.running = False
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        if self.fail is not None:
            s.summary = ("Render scene stopped - nothing written" if self.fail == "stopped"
                         else f"Render scene failed: {self.fail}")
        else:
            r = self.result
            size = f"{r['size'] / 1e9:.2f} GB" if r['size'] >= 1e8 else f"{r['size'] / 1e6:.1f} MB"
            s.summary = (f"Render scene written: {os.path.basename(r['path'])} ({size}), {r['objects']} objects at the "
                         f"render level, parts and materials inside - renders without Renderbricker and without "
                         f"the cache file ({convert.fmt_time(time.time() - self.t0)})")
        convert.phase("render scene", self.t0)
        self.report({'ERROR'} if self.fail not in (None, "stopped") else {'INFO'}, "Renderbricker: " + s.summary)
        convert.redraw(context)
        return {'CANCELLED'} if self.fail is not None else {'FINISHED'}


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
    bl_description = (" ".join(common.HEADLESS_ABOUT) + " The scene is saved first; the new file is "
                      "<scene>_subdiv_<add-on version>.blend next to it. The start script written beside it (.bat on "
                      "Windows, .command on macOS, .sh on Linux) can be run again by hand")

    def invoke(self, context, event):
        if not bpy.data.filepath:
            self.report({'INFO'}, "Save the scene first - Convert headless continues after saving")
            widgets.continue_after_save(context, "mecsub.headless")
            return bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', filepath=widgets.save_as_name(context))
        # a dialog of its own: the question of invoke_confirm is one line, and with the sentence about what
        # Convert headless does it grew wider than the Blender window (seen in the tutorial pictures, run 271)
        return context.window_manager.invoke_props_dialog(self, width=460, title="Convert headless",
                                                          confirm_text="Continue")

    def draw(self, context):
        import textwrap
        col = self.layout.column(align=True)
        col.scale_y = 0.85
        for sentence in common.HEADLESS_ABOUT:
            for line in textwrap.wrap(sentence, 62):
                col.label(text=line)
        self.layout.label(text="The scene is saved now. Continue?")

    def execute(self, context):
        import os
        common.object_mode(context)
        if not common.targets(context):
            self.report({'WARNING'}, props.scope_empty_text(context))
            return {'CANCELLED'}
        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()
        blend = bpy.data.filepath
        folder, stem = os.path.dirname(blend), os.path.splitext(os.path.basename(blend))[0]
        tag = common.VERSION.replace(".", "-")
        name, k = f"{stem}_subdiv_{tag}", 1
        while os.path.exists(os.path.join(folder, name + ".blend")):   # never overwrite an earlier result
            k += 1
            name = f"{stem}_subdiv_{tag}_{k}"
        out = os.path.join(folder, name + ".blend")
        s = context.scene.mecsub
        args = headless_args(context, out)
        script = write_headless_script(os.path.join(folder, name), stem, blend, out, args)
        how = start_script(script)
        s.summary = (f"Headless conversion started in a terminal: {os.path.basename(script)}, result: {os.path.basename(out)}"
                     if how else f"Start script written, run it in a terminal: {script}")
        self.report({'INFO'}, "Renderbricker: " + s.summary)
        return {'FINISHED'}


def headless_args(context, out):
    """Blender's arguments for the headless conversion of the saved scene into `out`. The objects in scope go to
    <out>_objects.json (--objects): only they are converted, everything else stays as it is (UPDATES #24,
    maintainer 2026-10-10; always, since the scope All is gone - #33)."""
    import os, json
    s = context.scene.mecsub
    args = ["-b", "--factory-startup", bpy.data.filepath, "--python",
            os.path.join(os.path.dirname(__file__), "rbcore", "run.py"),
            "--", out, "--view-level", str(s.view_level), "--render-level", str(s.render_level),
            "--shading", "mecabricks" if s.variant == 'A' else "geometric", "--jobs", "auto",
            "--low-memory", s.low_memory.lower(),
            "--smooth-maps", "1" if s.smooth_maps and s.edges != 'BEVEL' else "0",
            "--edges", "bevel" if s.edges == 'BEVEL' else "shader", "--edge-radius", f"{s.edge_radius:.3f}",
            "--bevel-segments", str(s.bevel_segments),
            "--bevel-shader", "1" if s.edges == 'BEVEL' and s.edge_shader_too else "0"]
    listing = os.path.splitext(out)[0] + "_objects.json"
    with open(listing, "w", encoding="utf-8") as fh:
        json.dump(sorted(o.name for o in common.targets(context)), fh, ensure_ascii=False)
    args += ["--objects", listing]
    if s.use_cache:
        args += ["--cache", core.cache_path_for(out)]
    if s.use_log:
        args += ["--log", logfile.log_path()]
    return args


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
        lines = ["@echo off", "chcp 65001 >nul", f"title Renderbricker {common.VERSION} headless: {stem}"]
        lines += [f"echo {line}" for line in common.HEADLESS_ABOUT] + ["echo."]
        lines += [f"echo {head} {q(blend)}", f"echo Result: {q(out)}", "echo.",
                 " ".join([q(blender)] + [q(a) if (" " in a or os.sep in a) else a for a in args])
                 + " 2>&1 | findstr /B " + " ".join(f'/C:"{w}"' for w in HEADLESS_SHOW),
                 "echo.", f"if exist {q(out)} (echo Done: {q(out)}) else (echo FAILED - no result written)", "pause"]
        path = base + ".bat"
        with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(lines) + "\n")
        return path
    path = base + (".command" if sys.platform == "darwin" else ".sh")
    lines = ["#!/bin/sh", f"# Renderbricker {common.VERSION} headless conversion of {stem}"]
    lines += [f"echo {shlex.quote(line)}" for line in common.HEADLESS_ABOUT] + ["echo"]
    lines += [f"echo {shlex.quote(head + ' ' + blend)}", f"echo {shlex.quote('Result: ' + out)}", "echo",
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
