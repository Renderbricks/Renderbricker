"""Command line options and the settings every part of the conversion shares (levels, shading, method).
The add-on sets some of them before a run (rbcore.RENDER_LEVEL = ... goes here through the package)."""
import sys


import os as _os
ENTRY = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "run.py")   # started by background Blenders

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


TARGET = args[0] if args and not args[0].startswith("--") else None


def opt(name, default):
    return args[args.index(name) + 1] if name in args else default


SHADING = opt("--shading", "mecabricks")


METHOD = opt("--method", "weld")      # weld (rules 3.0) | rules24 (the island rules up to 2.4)


LEVELS = int(opt("--levels", "2"))


RULES_VERSION = "3.6"          # = RULES.md; shown in the add-on panel header


ARC_END = opt("--arc-end", "0") == "1"      # pin arc ends (run 19 test: did not remove the axle-hole crossing, off)


ESCALATE = opt("--escalate", "all")      # all | curved (flat folds tolerated) | none


REPAIR_T = opt("--repair-t", "0") == "1"   # T-fan topology repair (run 15 experiment, off: the band folds anyway)


assert SHADING in ("geometric", "mecabricks"), SHADING


FLAT_MAX_ANGLE = 1.0          # planar island: all normals within this


ROUND_TURN = (5.0, 40.0)      # boundary turn of a polygonised circle (12-gon: 30)


ROUND_REGULAR = 3.0           # ... repeated by both boundary neighbours within this


SHARP_TURN = 30.0             # boundary corner, unless part of a circle


LOGO_HEIGHT = (0.05, 0.30)    # emboss height range


LOGO_MAX_SIZE = 4.0           # bbox diagonal of one letter


LOGO_CREASE_ANGLE = 50.0


MERGE_DIST = 1e-4


DEGENERATE_AREA = 1e-8       # sliver faces of the import (run 21: 54200, 3386, 4973)


MAX_PASSES = 7


REPAIR_CREASE = 0.5         # first fold-repair step: semi-sharp, keeps arcs nearly free


FAN_CREASE = 0.4            # T fan: only the diagonals (run 17: lowest value without folds AND without sub-edges crossing the corner outline; point 0.051 instead of 0.079)


PARTIAL = {}                # edge index -> crease < 1 (fold repair)


# ---------------------------------------------------------------- subdivided mesh copies
# Mecabricks and LDraw models are meshes plus their instances (objects linking one mesh;
# the material sits on the mesh). Modifiers belong to objects, not to meshes: a
# Subdivision modifier on every link made Blender subdivide every instance separately -
# the Porsche (2,710 objects) ran out of 95 GB and crashed (run 36). So only the original
# mesh is processed (creases), and the subdivision is written once into a copy of it that
# every link then uses (run 38): same objects, same links, no modifiers on the links. The
# original stays unchanged in the file (fake user) - "off" points the links back to it.
# Viewport and render level may differ: then there are two copies, and the add-on switches
# the links to the render copy for the duration of a render.
#   original["rb_view"] / ["rb_render"]  names of the copies ("" = original, level 0)
#   copy["rb_original"], copy["rb_level"], copy["rb_variant"]
VIEW_LEVEL = int(opt("--view-level", "1"))       # set by the add-on or the command line; 1: a quarter of


# the faces of level 2 to draw - NINJAGO_City opened slowly with level 2 on 4,964 objects (run 52)
RENDER_LEVEL = int(opt("--render-level", str(LEVELS)))


# Only the chosen viewport and render levels are baked (run 61; up to 1.8.0 levels 1 and 2
# always were): with viewport 0 (the originals in the viewport) no L1 copy is stored - 19 %
# of Dungeon's 12 GB of copies. A level chosen later is baked then (progress bar).
PRE_LEVELS = ()


BAKE_QUALITY = 10


# Quality 10 needs about 0.2 MB per original face; the 32x32 baseplate 3811 of NINJAGO_City
# (286k faces) crashed at 33 GB (run 45), quality 6 baked it with 24 GB. Above
# QUALITY_FACE_LIMIT faces the copies are baked at BAKE_QUALITY_LARGE (seam gaps <= 0.0003
# in run 42, below the check threshold 0.001 - the check stays the control).
BAKE_QUALITY_LARGE = 6


QUALITY_FACE_LIMIT = 50000
