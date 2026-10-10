"""The temporary work object in a scene of its own, and the dependency graph an object is evaluated in.

The lowest step of the conversion beside config: the checks, the crease rules, the copies and the welding all
evaluate a work object - none of them has to import another one for it."""
import bpy


WORK_NAME = "RB work"


WORK_SCENE = "RB work scene"


def work_scene():
    """A scene of its own for the temporary work object (run 52): evaluating it in the user's
    scene re-evaluated the whole dependency graph each time - 96 ms per evaluation with the
    4,966 objects of NINJAGO_City, 1 ms in a scene of its own."""
    sc = bpy.data.scenes.get(WORK_SCENE)
    if sc is None:
        sc = bpy.data.scenes.new(WORK_SCENE)
    return sc


def drop_work_scene():
    sc = bpy.data.scenes.get(WORK_SCENE)
    if sc is not None and not sc.collection.all_objects:
        bpy.data.scenes.remove(sc)


def link_work(ob):
    work_scene().collection.objects.link(ob)
    return ob


def depsgraph_of(ob):
    """Evaluated dependency graph of the scene the object lives in."""
    sc = ob.users_scene[0] if ob.users_scene else bpy.context.scene
    if sc == bpy.context.scene:
        return bpy.context.evaluated_depsgraph_get()
    with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
        return bpy.context.evaluated_depsgraph_get()


def work_object(me):
    """Temporary object in a scene of its own: the only thing that ever carries a modifier."""
    return link_work(bpy.data.objects.new(WORK_NAME, me))
