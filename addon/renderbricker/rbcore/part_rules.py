"""Rules for single parts (rules 3.15, docs/RULES.md S): where the general rules keep a corner the real part does not
have and no general rule can tell it apart from a brick's real corner, the part gets an entry here.

A part is known by its shape, not by its name - a renamed mesh gets its rule too (maintainer 2026-11-10: „wenn man
umbenennt, ist ungünstig“): the import's vertex and face count, and every listed point found at its place in the
import. Where Mecabricks changes the part, it no longer matches and is converted by the general rules alone.

S1 the crab 31577 / 33121 (UPDATES #60, run 298): three corners per claw are not pinned - the top of the claw tip,
   the top of the C's other end and that end's foot at the flat bottom. The part counts as mechanical (flat share
   0.261 >= MECH_FLAT), so the brick threshold (SHARP_TURN) pinned the corners where its creased seams turn; the
   real part is round there (BrickLink photos). Maintainer on run 295's sheet: three circles; „so kann das Teil
   aktuell nicht bleiben“.

Called by welding.weld at the end of stage 9 (free_corners)."""
from mathutils import Vector
from mathutils.kdtree import KDTree

TOL = 1e-3

_CRAB_RIGHT = [(8.528, 4.25, 9.708),     # top of the claw tip, end of the facet's seams to the body
               (6.4, 4.456, 8.0),        # top of the C's other end, where its seams to the inner arc meet
               (6.292, 2.1, 8.188)]      # that end's foot at the flat bottom, where the 90 deg rim turns
_CRAB = _CRAB_RIGHT + [(-x, y, z) for x, y, z in _CRAB_RIGHT]       # the left claw is the mirror

# (vertices, faces) of the import -> (rule, points not pinned)
PARTS = {(2510, 1944): ("S1 crab 31577", _CRAB),
         (2404, 1916): ("S1 crab 33121", _CRAB)}


def rule_for(orig):
    """(rule, points) when the import has a listed shape and every point is one of its vertices, else None."""
    entry = PARTS.get((len(orig.vertices), len(orig.polygons)))
    if entry is None:
        return None
    kd = KDTree(len(orig.vertices))
    for v in orig.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    if all(kd.find(Vector(p))[2] <= TOL for p in entry[1]):
        return entry
    return None


def free_corners(w):
    """End of stage 9. Reads orig, V. Takes the listed points of the part's rule out of V (not pinned). Returns how
    many were freed."""
    entry = rule_for(w.orig)
    if entry is None:
        return 0
    pts = [Vector(p) for p in entry[1]]
    freed = {v for v in w.V if any((v.co - p).length <= TOL for p in pts)}
    w.V -= freed
    return len(freed)
