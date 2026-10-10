"""Panel pieces used by the panel and the Start Guide: summary, bullets, block text, levels, Apply button."""
import re
import bpy
from . import rbcore as core
from . import hyphens, props


# ---------------------------------------------------------------- guide for new users
def draw_summary(L, s):
    """Result of the last operator and the problem list (select button per entry)."""
    if not s.summary or s.running:
        return
    import bpy as _bpy
    box = L.box()
    bullets(box, s.summary.split(", "), _bpy.context)
    if len(s.problems):
        col = box.column(align=True)
        col.scale_y = 0.9
        for p in list(s.problems)[:12]:
            r = col.row(align=True)
            r.alert = True
            r.label(text=f"•  {p.obj}: {p.info}")
            r.operator("mecsub.select", text="", icon='RESTRICT_SELECT_OFF').obj = p.obj
        if len(s.problems) > 12:
            col.label(text=f"   ... {len(s.problems) - 12} more" + (" - all in the log file" if s.use_log else ""))


def bullets(layout, items, context, prefix="•  "):
    """Explanations as bullet points, wrapped to the sidebar width."""
    import textwrap
    width = context.region.width if context.region else 300
    chars = max(20, int(width / (7.5 * context.preferences.system.ui_scale)))
    col = layout.column(align=True)
    col.scale_y = 0.8
    for text in items:
        for line in textwrap.wrap(text, chars, initial_indent=prefix, subsequent_indent=" " * len(prefix)):
            col.label(text=line)


# ---------------------------------------------------------------- block text (About, the guide's explanations)
# Blender labels are single lines without justification or hyphenation. A text is set here line by line: the
# lines as wide as the panel, the gaps between the words widened with thin and hair spaces, long words broken at
# their hyphenation points ("|" in the text). First for the legal texts of About (user, 2026-09-29), then for the
# explanations of the Start Guide (UPDATES #36, maintainer 2026-10-10: "Text wie in About.").
FILL_CHARS = (chr(0x2005), chr(0x2009), chr(0x200a))       # four-per-em, thin and hair space


ABOUT_MARGIN = 53           # panel width minus this = the width of the buttons in a panel (measured, ui scale 1)


BOX_MARGIN = 69             # the same inside a box of the panel (the guide's explanations; measured in run 255)


_WORD = re.compile(r"(?<![\w/.\\<_-])[A-Za-z]{%d,}(?![\w/\\>_-]|\.\w)" % hyphens.MIN_WORD)   # not in file names


def hyphenated(text):
    """The text with the hyphenation points of its long words (table hyphens.TABLE, made for the guide's texts)."""
    return _WORD.sub(lambda m: hyphens.TABLE.get(m.group(0), m.group(0)), text)


def _pad(width, wid, fills):
    """Blank characters as wide as `width`: spaces, the rest in thin and hair spaces."""
    space = wid(" ")
    if space <= 0:                              # no font size (no window): one blank per character will do
        return ""
    n = int(width // space)
    out, rest = " " * n, width - n * space
    for fw, ch in fills:
        while rest >= fw > 0:
            out += ch
            rest -= fw
    return out


def set_block(text, wid, avail, fills, prefix=""):
    """The lines of `text` set as a block `avail` wide. wid(text) measures, fills: (width, character) of the blank
    characters that widen the gaps, widest first. Words break at "|" (a hyphen is added) and after a hyphen they
    have. prefix (a bullet) stands in front of the first line, the others are indented by its width. The last
    line is not stretched."""
    lead = wid(prefix) if prefix else 0.0
    room = avail - lead
    indent = (_pad(lead, wid, fills) or " " * len(prefix)) if prefix else ""
    words, lines, cur = text.split(" "), [], []
    while words:
        w = words.pop(0)
        parts = [p for p in re.split(r"\||(?<=[A-Za-z]-)(?=[A-Za-z])", w) if p]
        plain = "".join(parts)
        if wid(" ".join(cur + [plain])) <= room:
            cur.append(plain)
            continue
        for k in range(len(parts) - 1, 0, -1):      # a hyphenation point that lets the line end there
            head = "".join(parts[:k])
            head += "" if head.endswith("-") else "-"
            if wid(" ".join(cur + [head])) <= room:
                cur.append(head)
                words.insert(0, "|".join(parts[k:]))
                break
        else:
            if cur:
                words.insert(0, w)                  # onto the next line
            else:
                cur.append(plain)                   # wider than a line and no point fits: alone on its line
        lines.append(cur)
        cur = []
    if cur:
        lines.append(cur)
    out = []
    for n, line in enumerate(lines):
        start = prefix if n == 0 else indent
        if n == len(lines) - 1 or len(line) < 2:
            out.append(start + " ".join(line))
            continue
        gaps = len(line) - 1
        extra = room - wid(" ".join(line))
        text_line, given = line[0], 0.0
        for i in range(gaps):
            want = extra * (i + 1) / gaps - given        # this gap's share of the room left over
            pad, rest = "", want
            for fw, ch in fills:
                while rest >= fw > 0:
                    pad += ch
                    rest -= fw
            given += want - rest
            text_line += " " + pad + line[i + 1]
        out.append(start + text_line)
    return out


def _measure(context, margin):
    """(wid, avail, fills) for set_block from the font of the panel's labels and the width of the sidebar."""
    import blf
    pref = context.preferences
    blf.size(0, pref.ui_styles[0].widget.points * pref.system.ui_scale)
    wid = lambda t: blf.dimensions(0, t)[0]
    region = context.region.width if context.region else 300
    fills = sorted(((wid(c), c) for c in FILL_CHARS if wid(c) > 0), reverse=True)
    return wid, region - margin * pref.system.ui_scale, fills


def justified(layout, text, context, margin=ABOUT_MARGIN):
    """A text as a block in the panel (About)."""
    wid, avail, fills = _measure(context, margin)
    col = layout.column(align=True)
    col.scale_y = 0.8
    for line in set_block(text, wid, avail, fills):
        col.label(text=line)


POINT_GAP = 1.2             # between two points of the guide: about half a line (chosen from pictures, 2026-10-10)


def justified_bullets(layout, items, context, prefix="•  ", margin=BOX_MARGIN, gap=POINT_GAP):
    """Explanations as bullet points set as blocks, with a small gap between two points (the guide; maintainer
    2026-10-10: "Bulletpoints mit Leerzeilen getrennt, außer die Zahlenstatistik." - the summary box keeps the plain
    bullets). gap: the separator between two points, 0 for none."""
    wid, avail, fills = _measure(context, margin)
    col = layout.column(align=True)
    col.scale_y = 0.8
    for n, text in enumerate(items):
        if n and gap:
            col.separator(factor=gap)
        for line in set_block(hyphenated(text), wid, avail, fills, prefix):
            col.label(text=line)


def status(layout, ok, text):
    row = layout.row()
    row.alert = not ok
    row.label(text=text, icon='CHECKMARK' if ok else 'INFO')


def draw_levels(L, s, context):
    """Viewport / render level with a warning above 2 (user, 2026-09-28): every level multiplies the
    faces by three to four - level 3 costs a lot of memory and time for hardly visible gain."""
    col = L.column(align=True)
    col.label(text="Subdivision levels")
    col.prop(s, "view_level")
    col.prop(s, "render_level")
    if s.view_level > 2 or s.render_level > 2:
        box = L.box()
        box.alert = True
        bullets(box, ("Levels above 2 multiply the faces again by three to four: memory, file size and "
                      "conversion time grow a lot, the visible gain is small. 2 is enough for close-ups.",),
                context, prefix="")


def scope_state(context):
    """(ok, text) for the choice of parts - cheap enough for draw(): stops at the first mesh."""
    s = context.scene.mecsub
    if s.scope == 'SELECTED':
        ok = any(o.type == 'MESH' for o in context.selected_objects)
        return ok, "Parts selected" if ok else "Select the parts to convert"
    cols = props.scope_collections(s)
    if not cols:
        return False, "Add a collection"
    ok = any(o.type == 'MESH' for c in cols for o in c.all_objects)
    return ok, (f"Parts in {', '.join(c.name for c in cols)}" if ok else "The collections have no parts")


_AFTER_SAVE = []          # the one pending "continue after the first save" handler (UPDATES #21)


def continue_after_save(context, idname, **kwargs):
    """Run the operator `idname` again once the scene has been saved for the first time - Apply, Write cache and
    Convert headless open Save As on an unsaved scene and continue by themselves afterwards (maintainer
    2026-10-06). One shot: removed after the next save; a save more than ten minutes later (the dialog was
    cancelled and the scene saved some other time) does not start it."""
    import time
    for h in _AFTER_SAVE:
        if h in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.remove(h)
    _AFTER_SAVE.clear()
    win, area, region, t0 = context.window, context.area, context.region, time.time()

    def handler(*_args):
        if handler in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.remove(handler)
        _AFTER_SAVE.clear()
        if time.time() - t0 > 600:
            return

        def run():
            op = getattr(getattr(bpy.ops, idname.split(".")[0]), idname.split(".")[1])
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    op('INVOKE_DEFAULT', **kwargs)
            except Exception:                      # the window or area went away: any 3D view
                from . import edit
                try:
                    with bpy.context.temp_override(**edit._context_override()):
                        op('INVOKE_DEFAULT', **kwargs)
                except Exception:
                    import traceback
                    traceback.print_exc()
            return None
        bpy.app.timers.register(run, first_interval=0.2)

    _AFTER_SAVE.append(handler)
    bpy.app.handlers.save_post.append(handler)


def save_as_name(context):
    """File name offered when the scene is saved the first time: the name of the imported model - the
    top collection with the most mesh objects, as a Mecabricks import brings one (user, 2026-09-29)."""
    import re
    best, n = None, 0
    for c in context.scene.collection.children:
        k = sum(1 for o in c.all_objects if o.type == 'MESH')
        if k > n:
            best, n = c, k
    name = re.sub(r'[\\/:*?"<>|]+', "_", best.name).strip(" .") if best else ""
    return (name or "untitled") + ".blend"


def draw_low_memory(L, s):
    sp = L.split(factor=0.4)                # the label in full, the three buttons beside it
    sp.active = s.use_cores
    sp.label(text="Low Memory")
    sp.row(align=True).prop(s, "low_memory", expand=True)


APPLIED_KEY = "rb_applied"      # scene: what the last Apply covered (apply_key)


def apply_key(context):
    """Settings, scope and the number of meshes and objects - when it is the same as after the last
    Apply, there is nothing to do (cheap enough for drawing; new parts change the numbers)."""
    s = context.scene.mecsub
    scope = s.scope
    if scope == 'SELECTED':
        scope += f":{len(context.selected_objects)}:{getattr(context.active_object, 'name', '')}"
    else:
        scope += ":" + ",".join(sorted(c.collection.name for c in s.collections if c.collection))
    objs = context.scene.objects
    n = len(objs) - (1 if objs.get(core.CAMERA_NAME) else 0)     # the render camera is not a part
    return f"{s.variant}|{s.view_level}|{s.render_level}|{scope}|{core.RULES_VERSION}|{len(bpy.data.meshes)}|{n}"


def apply_button(L, context, **kw):
    """Apply, or "Apply: up to date" when the last Apply covered the same (user, 2026-09-29)."""
    if context.scene.get(APPLIED_KEY) == apply_key(context):
        return L.operator("mecsub.apply", text="Apply: up to date", icon='CHECKMARK', **kw)
    return L.operator("mecsub.apply", icon='MOD_SUBSURF', **kw)
