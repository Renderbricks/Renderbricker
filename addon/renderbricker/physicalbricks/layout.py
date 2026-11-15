# SPDX-License-Identifier: GPL-3.0-or-later
"""Placing the physical network below the Mecabricks nodes by the node-tree rule: one outer frame, inside it one
numbered frame per step with its note (STEPS), the nodes of every step by the order of order.py (its columns and
rows, the gaps 40 / 40 / 40) on Blender's grid; the links run straight, no room is kept for them.

    network_columns(tree)  every node of the network (not the frames) in its step - the one place that sorts nodes
                           into steps: 1 values, 2 decoration, 3 physical shaders, 4 mix, 5 Eevee, 6 outputs
    layout(tree, made)     the outer frame for a network just built, its unused sockets hidden (hide_unused);
                           place(); the layout version (constants.LAYOUT = LAYOUT_VERSION) once both succeeded
    hide_unused(made)      unlinked outputs hidden, and the unlinked inputs of group nodes that show nothing
    width_for(node)        a node's width for its header and its value fields
    grid_up(value), grid_down(value)   a value up / down to the grid (GRID 20)
    text_head(text, width) the room a frame's text takes above its columns (ruling G3b)
    title_caps(title)      a frame's drawn title line in capitals, formulas, units and identifiers as written (G3c)
    kept_token(word)       a word title_caps leaves in its case
    step_text(number, nodes)   a step's title and note, step 2's naming only the parts it holds (G5a)
    decoration_part(label) the part of step 2 (print, yellowing, colour variation) a node stands for
    column_width(widths)   the width of every node of a column: the widest, up to the grid
    frame_width(content, need)   a frame's width on the grid around columns `content` wide, and their offset
    place(tree)            the step frames sized and placed anew, every node of the network in its step's frame, in
                           the columns and rows of order.columns / order.rows; never raises (an error is printed)
    current(tree)          the network's outer frame carries the current layout version

The design grid (part 4c, task 7g, 12.11.2026 - the maintainer: „Im Grafik Design achtet man auf ein ordentliches
Gestaltungsraster mit ausgerichteten Flächen und Schriften“), the same rules in the library's groups (Renderbricks R&D,
scripts/build_physical_blend.py):
- G1, the grid: GRID 20 is Blender's snap grid (NODE_GRID_UNIT, ED_node_c.hh:31; BKE_node.hh:243-244: node widths
  are generally multiples of it). On it: every column's left edge, every node width of ours (up to the grid, the cap
  WIDTH_MAX 340), every edge of a step frame, the row's top below the Mecabricks nodes and the columns' top. The nodes
  of a column stay exactly NODE_GAP apart: a node is as high as its socket rows of 22 make it.
- G2, one width per column: every node of ours in a column as wide as column_width of their width_for. A host's node
  (a step no rule knows, host.AFTER_NETWORK) keeps its width; Nicolas' nodes are never touched.
- G3, one type axis per frame: no frame of ours carries a label. Blender centres a frame's label
  (node_draw.cc:3837) and draws its text flush left at the frame's margin (:3852), both at label_size; so a step
  frame's title '<n>  <title>' is the first line of its text, the note follows. The band above the nodes is
  text_head (ruling G3b): with a label Blender drew the text from label_height + line_spacing + margin below the
  frame's top (node_draw.cc:3853-3854), without one from label_height; the title line takes one line_spacing of that,
  so the text's last line now ends MARGIN (30) higher than the note's did, and the band is MARGIN + NOTE_LINE (the
  line the brief added) less than before: NOTE_TOP + NOTE_LINE a line of the text instead of MARGIN + NOTE_TOP +
  NOTE_LINE x (note lines + 1) - the air below the text's last line as it was below the note (up to the grid).
  The title is also the frame's TITLE (an ID property), not its name: renaming a node fixes the
  animation paths of the whole file and builds its driver map each time (rna_nodetree.cc:2814-2834,
  anim_data.cc:1044-1051) - 0.12 s more per switch of a model of 1000 parts (run 160, task 7g). The outer frame
  shrinks around the step frames: Blender draws a shrinking frame's text as any frame's (node_draw.cc:3847-3876,
  nothing asks for shrink), its first line's baseline label_size (16) below its top (:3853-3854), and without a label
  the frame keeps a top margin of 30 above its children (:3524-3526, the bounds :3586-3589) - room for one line of 16
  points; so its text is FRAME_LABEL alone, one line (the frame is thousands of units wide, Blender wraps at its
  width less 60, :3850).
- G3c (task 7h, the maintainer: „Großbuchstaben.“): Blender draws a frame's text at one size and weight
  (node_draw.cc:3821, label_size; no bold), so the title line is drawn in capitals (title_caps) to set it off from
  the note; formulas, units and identifiers keep their case (kept_token). TITLE keeps the title as written, the
  band counts the capitals' width (CAPS_CHAR).
- G5a (task 7i, the maintainer: „Ja, nur nennen, was drin ist.“): step 2's title and note name only the parts of the
  decoration its nodes stand for (step_text, decoration_part) - 'Decoration: print, colour variation' without a
  colour that yellows; read from the nodes, never from a material's name, so any colour that gets Yellowing nodes is
  named. TITLE holds the title as drawn for this network, before the capitals.

Positions are written and read as location_absolute: location counts from the parent frame
(rna_nodetree.cc:1020-1054), and the Shader Editor moves a frame's own location to its drawn box whenever it draws it
(node_draw.cc:3603-3606). The step frames do not shrink (a shrinking frame is the union of its children,
node_draw.cc:3578-3599: a one-node step could not end level with the others, and the note would be drawn over its top
nodes); place() writes their boxes each time, since a frame that does not shrink keeps its old rectangle. The outer
frame shrinks around them; its location is never written. The numbers of the frames follow the library's own groups
(Renderbricks R&D, scripts/build_physical_blend.py: margin 30, the note's band, a title's letter width).

place() works in whole view units, on the grid since part 4c's ruling G1: the row's left edge to the nearest grid
line, its top down to one, a column advances by its width up to the grid, a frame's width and the columns' top lie on
it. So node_size.node_rect, which reads a box in whole units (location and width rounded), finds the gaps exact.

Part of Physicalbricks (see __init__.py)."""
import functools
import math
import re

import bpy

from . import host, order
from .constants import AVAILABLE, FRAME_LABEL, LAYOUT, LAYOUT_VERSION, NET

STEP = 'rb_phys_step'          # on a step frame: the step's fixed number 1-6
TITLE = 'rb_phys_title'        # on a frame of the network: its title, the first line of its text (ruling G3)
# the frames' texts, shared by all materials of a file: rb_phys_note_<step 1-6>_<n> a step's shown as frame n (its
# title and note, ruling G3) - step 2's with the words of its parts after it (ruling G5a: rb_phys_note_2_<n>_print_
# colour_variation), so networks with other parts keep their own text -, rb_phys_note_network the outer frame's
NOTE = 'rb_phys_note_'

# ruling G5a (part 4c, task 7i, the maintainer 12.11.2026: „Ja, nur nennen, was drin ist.“): step 2's title and note
# name only the parts the network holds, in this order - (the title's word, the note's clause, the labels of the
# step-2 nodes that stand for it, the label prefixes): the print network.build_network's 'Decoration data' and
# 'Physical Decoration' (network.py:259, :277), the yellowing its 'Yellowing #<i>' (network.py:360, a record with
# 'yellowing'), the colour variation its 'Colour variation #<i>' (network.py:390). The words are STEPS[2]'s
DECORATION = ('Decoration', "Changes the record's colour before it reaches the shader")
DECORATION_PARTS = (
    ('print', 'printed decoration and stickers', ('Decoration data', 'Physical Decoration'), ()),
    ('yellowing', 'yellowing with age', (), ('Yellowing #',)),
    ('colour variation', "the colour's spread between parts", (), ('Colour variation #',)),
)


def decoration_part(label):
    """The index in DECORATION_PARTS of the part a node with this label stands for; None for any other node."""
    for index, (_word, _clause, labels, prefixes) in enumerate(DECORATION_PARTS):
        if label in labels or label.startswith(prefixes):
            return index
    return None


def _decoration(parts):
    """Step 2's (title, note) naming these parts of DECORATION_PARTS, joined as the maintainer's text."""
    return (f"{DECORATION[0]}: {', '.join(p[0] for p in parts)}", f"{DECORATION[1]}: {', '.join(p[1] for p in parts)}.")


# step -> (title, note); a frame's title is '<n>  <title>' with n counted over the steps present. The texts are the
# maintainer's (part 4b, acceptance point 2, 11.11.2026: „Vorschlag übernehmen“), word for word; step 2's names all
# three parts - a network shows only those it holds (step_text, ruling G5a)
STEPS = {
    1: ('Values: colour, roughness, panel settings',
        ("The colour's record gives colour and roughness. With Advanced and Dev the Customize nodes add the panel's "
         "wear and variation to them.")),
    2: _decoration(DECORATION_PARTS),
    3: ('Physical shaders: one measured material per colour',
        ("One class group per colour (ABS, transparent, metal …), built from the measured record. This is the "
         "Cycles reference.")),
    4: ("Mix: the part's colours by its masks",
        ("A part with several colours or a print is mixed by the part's own masks, at the same places Mecabricks "
         "mixes them.")),
    5: ('Eevee: follows Cycles',
        ("The library's Eevee shader takes the same values and comes as close to the Cycles reference as Eevee "
         "allows.")),
    6: ('Outputs: Cycles and Eevee',
        "One output per engine; the afterglow (glow-in-the-dark) is added to both."),
}

MARGIN = 30                    # a frame's least margin: 1.5 widget units (node_draw.cc:3507); on the grid the side 40
NOTE_TOP, NOTE_LINE, NOTE_CHAR = 26, 22, 9.5   # the text's band 26 + 22 a line (text_head), 9.5 px a letter
TITLE_CHAR = 14                # a frame's text at least 14 px wide per letter of its title (size 16)
# ruling G3c (task 7h): the title line in capitals counts CAPS_CHAR px a letter. Measured 12.11.2026 with blf in
# Blender 5.3 headless (font 0, the UI font Inter, at label_size 16 as a frame draws its text, node_draw.cc:3821): of
# the 71 titles of the network and the groups in capitals the widest average letter is 9.63 px ('3  RANDOM FLAKE
# ORIENTATION'), in lower case 7.9; the note's 9.5 would undercount capitals. TITLE_CHAR keeps the frames wide enough
CAPS_CHAR = 10
# the words of a title that keep their case in capitals besides formulas and identifiers (kept_token): units, and 'x'
# as the multiplication sign
KEEP_CASE = ('mm', 'um', 'µm', 'nm', 'cm', 'px', 'deg', 'x')
NOTE_LINES = 3                 # and wide enough for its note in about three lines: in a one-node step the note ran to
                               # eight lines, and every step's nodes start below the deepest note (run 158 shots)
NODE_GAP = order.NODE_GAP      # 40 between the nodes of a column
COLUMN_GAP = order.COLUMN_GAP  # 40 from the right edge of a column to the next column
FRAME_GAP = order.FRAME_GAP    # 40 between the step frames of the row (30 until ruling G1: off the grid)
GRID = 20                      # ruling G1: Blender's snap grid, NODE_GRID_UNIT (ED_node_c.hh:31)
# the row's top below the lowest drawn Mecabricks node (part 4c, decided by the plan; 160 until then). Measured
# 12.11.2026 on Red Beard's hats at part 4b (05973e6) with Blender's link curve: a link leaves and enters horizontally,
# its handles 0.5 x the horizontal distance (drawnode.cc:1818-1842, calculate_inner_link_bezier_points, curving 5):
#     BELOW   Advanced: link length over our titles and notes, flattest entry into our frame   Dev: length, flattest
#      160                 2683                                  25 deg                        1733    17 deg
#      320                 2411                                  29 deg                        1612    23 deg
#      480                 2166                                  31 deg                        1502    29 deg
#      640                 1988                                  32 deg                        1331    32 deg
#      800                 1890                                  33 deg                        1226    34 deg
#     1200                 1812                                  36 deg                        1111    37 deg
# The gain flattens beyond 640, and with 640 the whole tree keeps about the shape of the editor (his block 750-1070
# high, ours about 800, the row about 3500 wide). A weak lever by geometry: a link always ends level at our socket.
BELOW = 640

# a node's width (width_for): its header and its value fields readable (part 4b, acceptance point 5). Measured
# 11.11.2026 in Blender 5.3.0, 5.2.4 and 5.0.1 windows at interface scale 1 (Renderbricks R&D run 159, task 6,
# measure_window.py; the same in all three): the texts' widths in the UI font at 11 points (blf), against the room
# Blender leaves them. A header's label starts 1.2 widget units (NODE_MARGIN_X, 24 px) in and ends 0.35 units (7 px)
# before the node's edge (node_draw.cc:2962, 3139-3146), so a drawn header leaves its label the node's width less 31.
# Blender switches the label's text padding off for a label button without an icon (interface_widgets.cc:5834-5846,
# BUT_NO_TEXT_PADDING), as the header's is; the 0.4 units counted at first (interface.cc:6935-6938) do not apply
# (task 6 review; the shots show the label at NODE_MARGIN_X). A number field shows 'Name 0.300' in the socket row's
# width less 20, less 2 x 8 padding, 8 text padding and a clip margin of 6 (node_draw.cc:373-375;
# interface_widgets.cc:2024-2025, 4387-4392): 50 px. With the spike's 6.6 / 44 / 70 the measurement found 'SSS Own
# Radius' cut on the class group of every hat ('SSS Own Ra...') and 'Sticker Roughness' on Dev's Physical Decoration;
# with these, no measured header or field.
HEADER_CHAR = 6.7              # px a letter: the widest average letter of a measured label or field name ('IOR')
HEADER_PAD = 33                # the header's 31 px and 2 px for the last letter's bearing (maintainer 11.11.2026)
FIELD_PAD = 93                 # a number field's 50 px, 2 px, and ' 38.000' (41 px, the widest number measured)
# WIDTH_MAX 330 (part 4c, ruling C6, 12.11.2026; 260 until then): one rule for the network and the groups. The longest
# field of ours needs 327.5 ('Transmission Dispersion Abbe Number' of the Principled BSDFs in the groups: 93 + 6.7 x 35)
# and the longest header 326 by blf ('Eevee: + fine fraction over the Mecabricks Eevee shader': 293 px + 33); a header
# the model counts wider (6.7 a letter: 401.5 for that one) is cut at WIDTH_MAX and still fits as drawn. 340 since
# ruling G1 (task 7g): 330 up to the grid, as every width of ours
WIDTH_MIN, WIDTH_MAX = 140, 340

# group nodes whose input values the library sets from the record or copies from a Mecabricks node: an unlinked input
# stays visible unless Blender marks it inactive (hide_unused)
SET_VALUES = ('Physical Decoration', 'Physical Normal')


def step_of(node):
    """The step of a node the library builds (1-6), None for a node no rule knows (a host's)."""
    label, kind = node.label, node.bl_idname
    if label in ('Output Cycles', 'Output Eevee', 'Physical Afterglow') \
            or label.startswith('Physical Afterglow + '):
        return 6
    if label in ('Physical Eevee', 'Physical Eevee Normal Map', 'Physical Wall Thickness',
                 'Physical Eevee glass + decoration', 'Physical Glow', 'Physical Volume + Glow') \
            or (label.startswith('Physical ') and label.endswith(' for Eevee')):
        return 5                   # (the three labels of files before group version 37 are rebuilt when they open)
    if label == 'Physical Mix':
        return 4
    if label.startswith('Physical #'):
        return 3
    if decoration_part(label) is not None:          # print, yellowing, colour variation (DECORATION_PARTS)
        return 2
    if label in ('Physical Normal', 'Physical Surface', 'Physical Settings', 'Customize at rest') \
            or label.startswith('Customize roughness') \
            or kind in ('ShaderNodeRGB', 'ShaderNodeValue', 'ShaderNodeCombineColor') \
            or (kind == 'ShaderNodeMath' and label.startswith('Roughness #')):
        return 1
    return None


def network_columns(tree):
    """The network's nodes (not its frames) in six steps, each in the order of the tree. A node no rule knows (a
    host's, added in host.AFTER_NETWORK: Renderdraw's 'Physical print ink #n') goes into the step of the first network
    node it feeds, through other such nodes too; one that feeds none, into the highest step of the nodes that feed it
    (each found by the same rule), else into step 1. Every step is found from the rules alone, never from a step found
    before it, so the order of the tree changes no step."""
    net = [n for n in tree.nodes if n.get(NET) and n.bl_idname != 'NodeFrame']
    names = {n.name for n in net}
    feeds, fed = {n.name: [] for n in net}, {n.name: [] for n in net}
    for link in tree.links:
        a, b = link.from_node.name, link.to_node.name
        if a in names and b in names:
            feeds[a].append(link.to_node)
            fed[b].append(link.from_node)
    known = {n.name: step_of(n) for n in net}

    def forward(node, seen):
        """The step of the first node with a rule that this node feeds, along the links; None when it reaches none."""
        if known[node.name] is not None:
            return known[node.name]
        for target in feeds[node.name]:
            if target.name not in seen:
                found = forward(target, seen | {node.name})
                if found is not None:
                    return found
        return None

    def resolve(node, seen):
        found = forward(node, frozenset())
        if found is not None:
            return found
        return max((resolve(s, seen | {node.name}) for s in fed[node.name] if s.name not in seen), default=1)

    step = {n.name: resolve(n, frozenset()) for n in net}
    return [[n for n in net if step[n.name] == number] for number in STEPS]


def layout(tree, made):
    """The outer frame of a network just built (made: its nodes), their unused sockets hidden (hide_unused); then
    place(), which gives every node of ours its width (ruling G2: its column's, from width_for) and the outer frame
    its title (TITLE) and text. The layout version (constants.LAYOUT, read by current()) is written here only, so
    that place() alone never marks a network of an older layout current, and only after both succeeded: like place(),
    layout() never raises (_guarded), and a network whose layout failed is laid again on the next open."""
    frame = tree.nodes.new('NodeFrame')
    frame.label_size = 16
    frame[NET] = True
    if _guarded(tree, _lay_new, tree, made):
        frame[LAYOUT] = LAYOUT_VERSION


def _lay_new(tree, made):
    hide_unused(made)
    _place_network(tree)


def _guarded(tree, work, *args):
    """work(*args); True when it returned. A layout error never raises into a switch, an import or a file opening
    (plan part 4c, Global Constraints): on an exception one line is printed and the tree keeps its nodes, links and
    values as built (a place() stopped midway may have placed some frames and nodes; it never touches a link or a
    value) - the network still renders, with its plain links; the layout version is taken off the outer
    frame (current() False), so the file's next opening lays it again (switch.upgrade_on_load). The line names the
    material that holds the tree: a material's tree is always 'Shader Nodetree' (Blender's material.cc:95)."""
    try:
        work(*args)
    except Exception as exc:  # noqa: BLE001 any error of the layout: the network must stay usable
        name = next((m.name for m in bpy.data.materials if m.node_tree == tree), tree.name)
        print(f'Physicalbricks: layout failed for {name}: {exc}', flush=True)
        outer = _outer(tree)
        if outer is not None and LAYOUT in outer:
            del outer[LAYOUT]
        return False
    return True


def current(tree):
    """The network of this tree carries the current layout (its outer frame's LAYOUT is LAYOUT_VERSION; a frame
    without it is of layout 1, library part 4). False for a tree without an outer frame."""
    outer = _outer(tree)
    return outer is not None and outer.get(LAYOUT, 1) == LAYOUT_VERSION


def _outer(tree):
    return next((f for f in tree.nodes if f.bl_idname == 'NodeFrame' and f.get(NET) and f.get(STEP) is None
                 and f.parent is None), None)


def _sets_values(node):
    """A group node whose inputs carry values the library set from the record or copied from a Mecabricks node: the
    class groups ('Physical #<i>: <name>'), the decoration, the part's normal and an effect's Eevee instance."""
    label = node.label
    return label.startswith('Physical #') or label in SET_VALUES \
        or (label.startswith('Physical ') and label.endswith(' for Eevee'))


def hide_unused(made):
    """The sockets of a network just built that show nothing: on every node an unlinked output; on a group node whose
    values the library sets (_sets_values) an unlinked input Blender draws greyed (NodeSocket.is_inactive), on every
    other group node every unlinked input (its values are the group's defaults or the panel's). Other nodes keep their
    inputs. Spec 2026-11-11 goal 7: every value set from the record stays visible (IOR, SSS Depth, Ink Roughness ...);
    a class group's SSS Radius is inactive while SSS Own Radius is 0, since the group selects it with a Mix.

    is_inactive is computed when it is read, so it is valid right after the links are made: the getter builds the
    topology cache (rna_node_socket.cc:387-393), bNodeSocket::is_inactive asks affects_node_output
    (BKE_node_runtime.hh:1035-1042), which infers the usage of every socket of the tree once and caches it
    (node_runtime.cc:711-726); a new link or a changed value tags that cache dirty (node_tree_update.cc:93-99,
    2280-2283, 2330-2332). The inference walks into group nodes and through Mix nodes by their constant factor
    (socket_usage_inference.cc:256-263, 360-388). Hiding a socket does not tag it (rna_NodeSocket_hide_set,
    rna_node_socket.cc:461-485, an ND_DISPLAY notifier only); a node's flags are read before its sockets are hidden
    anyway. (Source: the Blender checkout of 28.10.2026.) A Blender whose sockets lack is_inactive hides nothing on
    those nodes. Hidden at build time only: a value changed later does not show or hide a socket again."""
    for node in made:
        for socket in node.outputs:
            socket.hide = not socket.is_linked
        if node.bl_idname != 'ShaderNodeGroup':
            continue
        sets = _sets_values(node)
        idle = [s for s in node.inputs if not s.is_linked and (not sets or getattr(s, 'is_inactive', False))]
        for socket in idle:
            socket.hide = True


def width_for(node):
    """The width of a node of the network: its label in the header (HEADER_PAD + HEADER_CHAR a letter) and the name of
    every visible unlinked value input beside its number (FIELD_PAD + HEADER_CHAR a letter), between WIDTH_MIN and
    WIDTH_MAX."""
    need = HEADER_PAD + HEADER_CHAR * len(node.label)
    for socket in node.inputs:
        if socket.enabled and not socket.hide and not socket.is_linked and hasattr(socket, 'default_value') \
                and not getattr(socket, 'hide_value', False):
            need = max(need, FIELD_PAD + HEADER_CHAR * len(socket.name))
    return float(min(WIDTH_MAX, max(WIDTH_MIN, need)))


def grid_up(value):
    """`value` up to the grid (GRID; ruling G1), as an int; a value within 1e-6 of a grid line is on it (float32)."""
    return GRID * math.ceil(value / GRID - 1e-6)


def grid_down(value):
    """`value` down to the grid (GRID; ruling G1), as an int; a value within 1e-6 of a grid line is on it."""
    return GRID * math.floor(value / GRID + 1e-6)


def column_width(widths):
    """Ruling G2: the width of every node of ours in a column - the widest of their widths (width_for's; in the
    groups also the pins' pin_width), up to the grid once (G1). At most WIDTH_MAX, which lies on the grid."""
    return grid_up(max(widths))


def frame_width(content, need):
    """(width, side) of a frame of ours holding columns `content` wide (a multiple of GRID) and its text `need` wide:
    the side margins at least MARGIN, the room between them at least `need`, the columns in the middle - side, their
    offset from the frame's left edge, and so the width lie on the grid (ruling G1)."""
    side = grid_up(max(0.0, need - content) / 2 + MARGIN)
    return content + 2 * side, side


def _note_lines(note, width, char=NOTE_CHAR):
    """The note's lines when wrapped to `width` at `char` px a letter (NOTE_CHAR; CAPS_CHAR for a title line)."""
    lines = 0
    for paragraph in note.split("\n"):
        line = 0
        lines += 1
        for word in paragraph.split():
            if line and (line + 1 + len(word)) * char > width:
                lines += 1
                line = len(word)
            else:
                line += len(word) + (1 if line else 0)
    return lines


def text_head(text, width):
    """Ruling G3b: the room a frame's label-less text (its title, then its note) takes above the columns of a frame
    `width` wide: NOTE_TOP + NOTE_LINE a line, wrapped where Blender wraps a frame's text, at its width less two
    margins (node_draw.cc:3850) - the first line, the title in capitals (ruling G3c), at CAPS_CHAR a letter, the note
    at NOTE_CHAR. Place it up to the grid (grid_up). Until G3b: MARGIN + NOTE_TOP + NOTE_LINE x (the note's lines + 1)
    under a label - the same air below the text's last line (see the module docstring)."""
    first, _, rest = text.partition("\n")
    room = width - 2 * MARGIN
    return NOTE_TOP + NOTE_LINE * (_note_lines(first, room, CAPS_CHAR) + (_note_lines(rest, room) if rest else 0))


def kept_token(word):
    """Ruling G3c: a word of a title that keeps its case in capitals - a formula, a number, a unit or an identifier:
    it holds a digit, an underscore or an operator (= + * / ^ < >), starts with a minus, has a bracket inside it (a
    function call: '-ln(T'), or is a unit or the multiplication sign of KEEP_CASE - each judged without the brackets
    that enclose it and the punctuation after it, so '(mm)' and 'mm,' are units and '(parallax)' a word. An empty
    word (a stray space's neighbour, a lone ':', '()') is no token: kept False, as upper() leaves it the same."""
    core = word.strip('.,;:!?')
    while len(core) > 1 and core[0] in '([' and core[-1] in ')]':     # a slice of '' is '', and '' in '([' is True
        core = core[1:-1]
    core = core.lstrip('([').rstrip(')]')
    if not core:
        return False
    return (any(c.isdigit() or c in '_=+*/^<>' for c in core) or core.startswith('-')
            or any(c in '()[]' for c in core) or core in KEEP_CASE)


@functools.lru_cache(maxsize=256)
def title_caps(title):
    """Ruling G3c (part 4c, task 7h, the maintainer 12.11.2026: „Großbuchstaben.“): the title line a frame of ours
    draws - the first line of its text - in capitals, its spacing ('<n>  ' with two spaces) as written, every
    kept_token in its own case ('-ln(T / 0.855)', 'mm', 'x', 'rb_phys_...', 'ΔE'). A frame's stored title (TITLE,
    a group frame's name) keeps the title as written. Cached: place() asks for the same few titles on every switch
    (STEPS and FRAME_LABEL are constants; about 8 ms a switch of a large model uncached, review of task 7h)."""
    return ''.join(part if part.isspace() or kept_token(part) else part.upper() for part in re.split(r'(\s+)', title))


def step_text(number, nodes):
    """(title, note, tag) of step `number` holding `nodes` (its column of network_columns): STEPS' title and note and
    no tag for every step but 2. Ruling G5a (task 7i): step 2 names only the parts its nodes stand for
    (decoration_part), in the order of DECORATION_PARTS, and tags its shared text with their words ('_print_colour_
    variation'). A step 2 always holds a part: a node no rule knows joins a step only through a node with a rule of
    it (network_columns), and step 2 is left out without nodes - a step 2 without a part raises (place()'s guard
    catches it)."""
    if number != 2:
        return (*STEPS[number], '')
    found = {decoration_part(node.label) for node in nodes}
    parts = [part for index, part in enumerate(DECORATION_PARTS) if index in found]
    if not parts:
        raise ValueError('Physicalbricks: a step 2 without a part of the decoration')
    return (*_decoration(parts), ''.join('_' + part[0].replace(' ', '_') for part in parts))


def _text(key, content):
    """The text NOTE + key holding `content`, shared by every material of the file (a text keeps a fake user,
    text.cc:289-292: switch.set_material_system removes those no frame uses)."""
    name = NOTE + key
    text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    if text.as_string() != content:
        text.from_string(content)
    return text


def place(tree):
    """Every node of the network in its step's frame, the steps in one row from the left edge of the Mecabricks
    nodes, BELOW under the lowest of them (with its drawn height, host.node_height): each step's columns by
    order.columns, then the rows of all steps by order.rows (the plan of the steps present, in the order of the
    flow); every node of ours in a column column_width wide (a host's node keeps its width); a column starts
    COLUMN_GAP right of the column before it, its nodes top to bottom NODE_GAP apart; the columns in the middle of a
    wider frame; the step frames with the same top and bottom, FRAME_GAP apart - on the grid (rulings G1, G2). The
    frames carry no label: a step frame's title is its TITLE and its text's first line, the note follows; the outer
    frame's TITLE and text are FRAME_LABEL (ruling G3). Only nodes marked NET move; another node (a host's, a user's
    shader or reroute) keeps its place and only its links count, as order.py reads them. Called after building (the
    host's AFTER_NETWORK nodes already in: network.build_network's after), and again after the carrying add-on's
    layout watcher arranged the Mecabricks nodes.
    Returns at once for a tree without a network, and below Blender 5.0. Never raises (_guarded): returns False when
    the layout failed (its line printed, the layout version taken off), else True."""
    return _guarded(tree, _place_network, tree)


def _place_network(tree):
    """place()'s work, unguarded."""
    if not AVAILABLE:
        return
    steps = network_columns(tree)
    if not any(steps):
        return
    node_height = host.node_height
    nodes = tree.nodes
    frames = [f for f in nodes if f.bl_idname == 'NodeFrame' and f.get(NET)]
    outer = _outer(tree)
    if outer is None:
        outer = nodes.new('NodeFrame')
        outer[NET] = True
        outer.label_size = 16
    outer.label = ''
    outer[TITLE] = FRAME_LABEL
    outer.text = _text('network', title_caps(FRAME_LABEL))           # ruling G3c: the drawn title in capitals
    own = {}
    for frame in frames:
        number = frame.get(STEP)
        if number is None:
            continue
        if number in own or not steps[number - 1]:
            nodes.remove(frame)                # a step without nodes now (or a second frame of one)
        else:
            own[number] = frame
    others = [n for n in nodes if not n.get(NET) and n.bl_idname not in ('NodeFrame', 'NodeReroute')]
    # the row's left edge at the left edge of his nodes, to the nearest grid line; its top (the frames' top) BELOW -
    # MARGIN under his lowest node, down to the grid (ruling G1)
    x = GRID * round(min((n.location_absolute.x for n in others), default=0.0) / GRID)
    top = grid_down(min((n.location_absolute.y - node_height(n) for n in others), default=0.0) - BELOW + MARGIN)
    links = list(tree.links)
    present = [s for s in STEPS if steps[s - 1]]
    plan = [order.columns(steps[number - 1], links) for number in present]
    order.rows(plan, links)
    plans = []
    for count, (number, columns) in enumerate(zip(present, plan, strict=True), 1):
        title, note, tag = step_text(number, steps[number - 1])         # ruling G5a: step 2 names its parts
        label = f'{count}  {title}'
        text = f'{title_caps(label)}\n{note}'               # rulings G3 / G3c: the title in capitals, the note
        widths, offsets, at = [], [], 0
        for column in columns:
            ours = [width_for(n) for n in column if step_of(n) is not None]
            width = column_width(ours) if ours else 0                         # ruling G2
            widths.append(width)
            offsets.append(at)
            at += max(width, grid_up(max((n.width for n in column if step_of(n) is None), default=0))) + COLUMN_GAP
        content = at - COLUMN_GAP
        width, side = frame_width(content, max(content, TITLE_CHAR * len(label),
                                               NOTE_CHAR * len(note) / NOTE_LINES))
        band = text_head(text, width)                     # ruling G3b
        tall = max(sum(node_height(n) + NODE_GAP for n in column) - NODE_GAP for column in columns)
        plans.append((number, count, label, text, columns, widths, offsets, width, side, band, tall, tag))
    head = grid_up(max(p[9] for p in plans))     # the nodes of every step start on one line, on the grid
    bottom = grid_down(top - head - max(p[10] for p in plans) - MARGIN)
    for number, count, label, text, columns, widths, offsets, width, side, _band, _tall, tag in plans:
        frame = own.get(number)
        if frame is None:
            frame = nodes.new('NodeFrame')
            frame[NET] = True
            frame[STEP] = number
            frame.label_size = 16
            frame.shrink = False
        frame.parent = outer
        frame.label = ''
        frame[TITLE] = label
        frame.text = _text(f'{number}_{count}{tag}', text)
        frame.location_absolute = (x, top)               # the frame first, then its nodes
        frame.width = width
        frame.height = top - bottom
        for column, column_w, offset in zip(columns, widths, offsets, strict=True):
            y = top - head
            for node in column:
                if step_of(node) is not None:
                    node.width = column_w
                node.parent = frame
                node.location_absolute = (x + side + offset, y)    # centred in a wider frame
                y -= node_height(node) + NODE_GAP
        x += width + FRAME_GAP
