"""Collection lists (+ / - / trash): which collections a list may take - the same rules in every add-on."""


# ---------------------------------------------------------------- the rules (maintainer, 2026-10-10)
# Briefed for Gaussian Render Capture and valid for all add-ons with a collection list:
#   1. + with an object selected (one is enough) adds the collection of that object - what was clicked in
#      the viewport counts, not the collection that happens to be active in the Outliner.
#   2. + with nothing selected offers the collections that hold meshes; not the Scene Collection, not the
#      collections the add-on made itself, not those already in the list.
#   3. - with no entry selected asks which collection to take out.
#   4. The Scene Collection is left out everywhere: it is a part of the scene, not a data-block of its own,
#      and cannot be stored in a pointer property ("cannot assign an embedded ID to an IDProperty").
#   5. The trash empties the list.
# This module holds the part that does not depend on the add-on (no operator, no property): copy it as it
# is; the operators and the menu around it belong to the add-on (props.py here).
def scene_collections(scene):
    """Every collection of the scene below the Scene Collection - the ones a list can take (rule 4)."""
    return list(scene.collection.children_recursive)


def of_objects(scene, objects, own=()):
    """Rule 1: (collections, loose) - the collections of the scene the objects lie in, each once, sorted by name
    (an object in several collections brings all of them); loose: the objects that lie only in the Scene
    Collection or in a collection of the add-on (`own`: their names)."""
    inside = {c for c in scene_collections(scene) if c.name not in own}
    cols, loose = [], []
    for ob in objects:
        mine = sorted((c for c in ob.users_collection if c in inside), key=lambda c: c.name)
        if not mine:
            loose.append(ob)
        cols += [c for c in mine if c not in cols]
    return cols, loose


def offered(scene, listed=(), own=()):
    """Rule 2: the collections + offers with nothing selected - those that hold a mesh (in a child collection
    counts), without the listed ones and the add-on's own."""
    return [c for c in scene_collections(scene) if c not in listed and c.name not in own
            and any(o.type == 'MESH' for o in c.all_objects)]


def loose_meshes(scene):
    """Whether mesh objects lie directly in the Scene Collection - they cannot be reached through a list."""
    return any(o.type == 'MESH' for o in scene.collection.objects)
