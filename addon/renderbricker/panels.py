"""The sidebar panel Renderbricker and its sub-panel About (logo, links, legal text)."""
import bpy
from . import rbcore as core
from . import camera_ui, common, guide, logfile, props, widgets


_icons = {}                     # the Renderbricks logo (bpy.utils.previews), loaded in register()


def logo_icon(name="logo"):
    pc = _icons.get("main")
    return pc[name].icon_id if pc and name in pc else 0


class MECSUB_PT_panel(bpy.types.Panel):
    bl_label = ""                           # the name is drawn in draw_header, beside the logo; version in the header (runs 41/42); the rules version stays internal (user, 2026-09-28)
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Renderbricker"

    def draw_header(self, context):         # the Renderbricks logo in front of the name (user, 2026-09-29)
        # 15 % larger than an icon (user, 2026-09-29). Its top hangs at the top of the header row - it
        # cannot be moved up; a larger logo only reaches further below the baseline of the name
        icon = logo_icon()
        row = self.layout.row(align=True)   # align: the name close to the logo (user, 2026-09-29)
        if icon:
            row.template_icon(icon_value=icon, scale=HEADER_LOGO_SCALE)
        # the name drawn here, not by Blender: a taller label box sets its baseline on the foot of the logo
        col = row.column()
        col.scale_y = NAME_DROP
        col.label(text=f"Renderbricker {common.VERSION}")

    def draw(self, context):
        s = context.scene.mecsub
        L = self.layout
        if s.running:
            box = L.box()
            if hasattr(box, "progress"):
                box.progress(factor=s.progress, type='BAR', text=s.progress_text)
            else:
                box.label(text=f"{s.progress * 100:.0f} %  {s.progress_text}")
            box.label(text="Esc: cancel", icon='CANCEL')
        if s.wt_active:
            guide.draw_guide(L, context)
            return
        row = L.row()
        row.scale_y = 1.3
        row.operator("mecsub.guide_start", icon='HELP')
        body = L.column()
        body.enabled = not s.running
        props.draw_scope(body, s)
        body.prop(s, "variant", text="")
        widgets.draw_levels(body, s, context)
        widgets.apply_button(body, context)
        body.prop(s, "use_cores")
        widgets.draw_low_memory(body, s)
        body.prop(s, "use_cache")
        logfile.draw_log(body, s)
        camera_ui.draw_render_camera(body, context)
        st = core.cache_state()
        if st is not None:
            import os
            box = body.box()
            col = box.column(align=True)        # two lines: at the default sidebar width one line was cut
            name = os.path.basename(st[1])      # (tutorial pictures, 2026-09-29)
            if not st[3]:
                col.label(text="Cache missing:", icon='ERROR')
                col.label(text=name, icon='BLANK1')
            elif st[1] != st[2]:
                col.label(text="Cache of another scene:", icon='ERROR')
                col.label(text=name, icon='BLANK1')
                sub = box.column(align=True)
                sub.operator("mecsub.move_cache", icon='FILE_FOLDER', text="Move cache here")
                sub.operator("mecsub.copy_cache", icon='DUPLICATE', text="Copy cache here")
            else:
                col.label(text="Cache file:", icon='FILE_BLEND')
                col.label(text=name, icon='BLANK1')
        row = body.row(align=True)
        row.operator("mecsub.check", icon='VIEWZOOM')
        state = s.subdiv_state
        label, icon = {"ON": ("Subdivision: ON", 'CHECKBOX_HLT'), "OFF": ("Subdivision: OFF", 'CHECKBOX_DEHLT'),
                       "MIXED": ("Subdivision: partly on", 'CHECKBOX_HLT')}.get(state, ("Subdivision: -", 'CHECKBOX_DEHLT'))
        row.operator("mecsub.toggle", icon=icon, text=label, depress=(state == "ON"))
        body.operator("mecsub.remove", icon='X')
        body.separator()
        body.operator("mecsub.headless", icon='CONSOLE')
        body.operator("wm.url_open", text="Documentation", icon='HELP').url = DOCUMENTATION_URL
        widgets.draw_summary(L, s)
        wrapped(L, COPYRIGHT, context, center=True)     # centred under Documentation (user, 2026-09-29)


COPYRIGHT = "© 2026 Renderbricks®"                     # centred under Documentation (user, 2026-09-29)


DOCUMENTATION_URL = "https://github.com/Renderbricks/Renderbricker#documentation"


NAME_DROP = 1.15                        # header: height of the name's box - the logo's B between cap line and baseline (user's mock-up)


HEADER_LOGO_SCALE = 1.15               # header: the logo 15 % larger than an icon


LOGO_SCALE = 4.37                       # About: the logo as wide as "Renderbricks®" below it (icon units)


TRADEMARK = ("Renderbricks®", "is a registered word mark in Germany.")   # the name alone under the logo (user)


DISCLAIMER = ("Au|thor: Prof. Mi|chael Klein—Me|di|a|de|sign Uni|ver|si|ty of Ap|plied Sci|ences. "
              "Ren|der|bricks is about ren|der|ing dig|i|tal LEGO®. LEGO® is a trade|mark of the LEGO Group of "
              "com|pa|nies which does not spon|sor, au|tho|rize or en|dorse this add-on.")   # | = hyphenation point


LINKS = (("www.renderbricks.com", "https://www.renderbricks.com", 'URL'),
         ("Facebook", "https://www.facebook.com/renderbricks", 'COMMUNITY'),
         ("YouTube", "https://www.youtube.com/@renderbricks", 'PLAY'),
         ("Renderbricker on GitHub", "https://github.com/Renderbricks/Renderbricker", 'HELP'),
         ("Digital Film Design—Animation/VFX",
          "https://www.mediadesign.de/de/bachelor/digital-film-design-animation-vfx-ba",
          'FILE_MOVIE'))                    # the film strip: the study programme Digital Film Design


def justified(layout, text, context):
    """Text in a block: lines as wide as the panel, the space between the words widened with thin and hair
    spaces (Blender labels have no justification), long words broken at their hyphenation points ("|" in
    the text) - the legal texts of About (user, 2026-09-29)."""
    import blf
    pref = context.preferences
    size = pref.ui_styles[0].widget.points * pref.system.ui_scale
    blf.size(0, size)
    wid = lambda t: blf.dimensions(0, t)[0]
    region = context.region.width if context.region else 300
    avail = region - 53 * pref.system.ui_scale            # the width of the buttons above (measured)
    space = wid(" ")
    fills = sorted(((wid(c), c) for c in (chr(0x2005), chr(0x2009), chr(0x200a)) if wid(c) > 0), reverse=True)   # 4/6, thin, hair space
    words = text.split(" ")
    lines, cur = [], []
    while words:
        w = words.pop(0)
        parts = w.split("|")
        plain = "".join(parts)
        if not cur or wid(" ".join(cur + [plain])) <= avail:
            if wid(" ".join(cur + [plain])) <= avail:
                cur.append(plain)
                continue
        broke = False
        for k in range(len(parts) - 1, 0, -1):      # a hyphenation point that lets the line end there
            head = "".join(parts[:k]) + "-"
            if cur and wid(" ".join(cur + [head])) <= avail:
                cur.append(head)
                words.insert(0, "|".join(parts[k:]))
                broke = True
                break
        lines.append(cur)
        cur = [] if broke else [plain]
    if cur:
        lines.append(cur)
    col = layout.column(align=True)
    col.scale_y = 0.8
    for n, line in enumerate(lines):
        last = n == len(lines) - 1
        if last or len(line) < 2:
            col.label(text=" ".join(line))
            continue
        gaps = len(line) - 1
        extra = avail - wid(" ".join(line))
        out = line[0]
        given = 0.0
        for i in range(gaps):
            want = extra * (i + 1) / gaps - given            # this gap's share of the room left over
            pad = ""
            rest = want
            for fw, ch in fills:
                while rest >= fw and fw > 0:
                    pad += ch
                    rest -= fw
            given += want - rest
            out += " " + pad + line[i + 1]
        col.label(text=out)


def wrapped(layout, text, context, center=False):
    """Label lines that fit the sidebar width (a label does not wrap by itself). text: a string, or a
    tuple of strings that each start a new line; center: every line centred."""
    import textwrap
    width = context.region.width if context.region else 300
    chars = max(20, int(width / (7.5 * context.preferences.system.ui_scale)))
    col = layout.column(align=True)
    col.scale_y = 0.8
    for part in ((text,) if isinstance(text, str) else text):
        for line in textwrap.wrap(part, chars):
            row = col.row()
            if center:
                row.alignment = 'CENTER'
            row.label(text=line)


class MECSUB_PT_about(bpy.types.Panel):
    bl_label = "About"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Renderbricker"
    bl_parent_id = "MECSUB_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        L = self.layout
        icon = logo_icon()
        if icon:
            row = L.row()                   # flush with "Renderbricks®" below it (user, 2026-09-29)
            row.alignment = 'CENTER'
            row.template_icon(icon_value=icon, scale=LOGO_SCALE)
        wrapped(L, TRADEMARK, context, center=True)
        col = L.column(align=True)
        for text, url, icon in LINKS:
            col.operator("wm.url_open", text=text, icon=icon).url = url
        justified(L, DISCLAIMER, context)
