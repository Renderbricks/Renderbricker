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


def remove_scene(sc, empty_only=False):
    """Remove a helper scene. Blender 4.5 crashes when a scene is removed in the script call that opened a file
    from a window - the context has no window yet then (run 267: plain Blender 4.5.14, no add-on needed; 5.2 and
    5.3 do not crash). In that case the scene goes a moment later, from a timer - with empty_only only if nothing
    was put into it meanwhile. Returns whether it is gone now."""
    if bpy.app.background or bpy.app.version >= (5, 0) or bpy.context.window is not None:
        bpy.data.scenes.remove(sc)
        return True
    name, tries = sc.name, [0]

    def later():
        s = bpy.data.scenes.get(name)
        if s is None or len(bpy.data.scenes) < 2 or (empty_only and s.collection.all_objects):
            return None
        if bpy.context.window is None and tries[0] < 50:
            tries[0] += 1
            return 0.1
        if bpy.context.window is not None:
            bpy.data.scenes.remove(s)
        return None

    bpy.app.timers.register(later, first_interval=0.0)
    return False


def drop_work_scene():
    sc = bpy.data.scenes.get(WORK_SCENE)
    if sc is not None and not sc.collection.all_objects:
        remove_scene(sc, empty_only=True)


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
