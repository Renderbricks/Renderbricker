"""The log file next to the scene and saving after the cache was written."""
import bpy
from . import common, importer, props


LOG_SUFFIX = "_Renderbricker.log"       # capital R (user, 2026-09-28; before: _renderbricker.log)


def log_path():
    """<scene>_Renderbricker.log next to the scene; a log of the old name is renamed to it (on Windows
    both names are the same file, elsewhere the log would be split in two)."""
    import os
    if not bpy.data.filepath:
        return ""
    base = os.path.splitext(bpy.data.filepath)[0]
    new = base + LOG_SUFFIX
    folder, name = os.path.split(new)
    try:
        old = next((f for f in os.listdir(folder or ".") if f.lower() == name.lower() and f != name), None)
        if old:
            os.rename(os.path.join(folder, old), new)
    except OSError:
        pass
    return new


def open_file(path):
    """Open a file with the system's default program (Windows, macOS, Linux)."""
    import os, sys, subprocess
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], start_new_session=True)


class MECSUB_OT_open_log(bpy.types.Operator):
    bl_idname = "mecsub.open_log"
    bl_label = "Open log file"
    bl_description = "Open <scene>_Renderbricker.log next to the scene in the system's text editor"

    @classmethod
    def poll(cls, context):
        import os
        return bool(bpy.data.filepath) and os.path.isfile(os.path.splitext(bpy.data.filepath)[0] + LOG_SUFFIX)

    def execute(self, context):
        path = log_path()
        try:
            open_file(path)
        except OSError as e:
            self.report({'ERROR'}, f"Renderbricker: log file not opened: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_log(L, s):
    row = L.row(align=True)
    row.prop(s, "use_log")
    row.operator("mecsub.open_log", text="", icon='TEXT')


def write_log(context, label):
    """Append the result of an operator to <scene>_Renderbricker.log (option Log file, user 2026-09-28):
    date, add-on and Blender version, scene, settings, the summary and the full problem list."""
    s = context.scene.mecsub
    path = log_path()
    if not s.use_log or not path or not s.summary:
        return
    import datetime
    scope = ("selected parts" if s.scope == 'SELECTED' else
             "collections " + (", ".join(c.name for c in props.scope_collections(s)) or "-"))
    lines = [f"=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {label}  "
             f"(Renderbricker {common.VERSION}, Blender {bpy.app.version_string})",
             f"scene: {bpy.data.filepath}",
             importer.importer_log(),
             f"settings: {scope}, variant {s.variant}, viewport {s.view_level}, render {s.render_level}, "
             f"several Blender processes {'on' if s.use_cores else 'off'} (Low Memory {s.low_memory.lower()}), cache file {'on' if s.use_cache else 'off'}"]
    lines += [f"  - {part}" for part in s.summary.split(", ")]
    if len(s.problems):
        lines.append(f"problems ({len(s.problems)}):")
        lines += [f"  - {p.obj}: {p.info}" for p in s.problems]
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n\n")
    except OSError as e:
        s.summary += f", log not written: {e}"


def save_after_cache(op, context):
    """After Apply / Levels wrote the cache file the scene is saved (user, run 74): the file
    on disk must link the copies that are now in the cache - an unsaved scene pointed to
    overrides the new cache no longer has."""
    part = getattr(op, "cache_part", None) or ""
    if not bpy.data.filepath or "copies in" not in part:
        return
    s = context.scene.mecsub
    if bpy.app.background:
        try:
            bpy.ops.wm.save_mainfile()
            s.summary += ", scene saved"
        except Exception as e:
            s.summary += f", scene not saved: {e}"
        return
    # in a window after the operator has ended: its undo step marks the file changed again
    s.summary += ", scene saved"
    def later():
        try:
            bpy.ops.wm.save_mainfile()
        except Exception as e:
            sc = bpy.context.scene
            if getattr(sc, "mecsub", None):
                sc.mecsub.summary = sc.mecsub.summary.replace(", scene saved", f", scene not saved: {e}")
        return None
    bpy.app.timers.register(later, first_interval=0.2)
