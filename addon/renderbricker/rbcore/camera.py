"""The render camera: camera Renderbricks, sky, the six views, the setup scene's render settings."""
import bpy, math
import numpy as np
from mathutils import Vector
from . import copies


# ---------------------------------------------------------------- render camera (user, 2026-09-28)
# "Render camera: ON" creates the camera "Renderbricks" (framing the model to fill the picture, clip
# end 1000) and a world "Renderbricks Sky" of its own (Physical Sky), makes both active and takes over
# the render settings of the Renderbricks setup scene (setup/renderbricks_setup.blend in the add-on).
# The scene's camera, world and render settings before are kept in the scene and come back with OFF -
# nothing of the user's is overwritten or lost (the old world keeps a fake user while it is unused).
# Framing: the manual way is Lock Camera to View, select all meshes, numpad 0 and period;
# camera_fit_coords is the same fit without a viewport.
CAMERA_NAME = "Renderbricks"


SKY_NAME = "Renderbricks Sky"


START_SAMPLES = 128                     # render camera ON starts on Low (user, 2026-09-28)


LAST_KEY = "rb_render_last"             # scene: the Renderbricks render settings at the last OFF


SKY_TAG = "rb_sky"                      # the world made or taken over by the add-on


CAMERA_ANGLE = (1.1093, 0.0, 0.8149)    # Blender's default camera: three-quarter view from the front right


CAMERA_MARGIN = 1.05                    # 5 % around the model


CLIP_END = 1000.0


RENDER_STRUCTS = ("render", "cycles", "eevee", "view_settings", "display_settings")


SKIP_PROPS = ("rna_type", "filepath", "name", "preview_pause")      # preview_pause: viewport only, needs a window


def _props(struct, depth=0):
    """(identifier, value or nested struct) of the settable properties - nested structs two levels
    deep, no ID data blocks, no collections."""
    if struct is None:
        return
    for p in struct.bl_rna.properties:
        k = p.identifier
        if k in SKIP_PROPS:
            continue
        if p.type == 'POINTER':
            v = getattr(struct, k, None)
            if depth < 2 and v is not None and not isinstance(v, bpy.types.ID):
                yield k, v, True
            continue
        if p.type == 'COLLECTION' or p.is_readonly:
            continue
        yield k, getattr(struct, k), False


def copy_props(src, dst, depth=0):
    """Copy the settable properties of one settings struct to another."""
    if src is None or dst is None:
        return
    for k, v, nested in _props(src, depth):
        if nested:
            copy_props(v, getattr(dst, k, None), depth + 1)
            continue
        try:
            setattr(dst, k, v)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass


def snapshot_props(struct, depth=0):
    """The settable properties as plain values (for the scene's JSON)."""
    out = {}
    for k, v, nested in _props(struct, depth):
        if nested:
            out[k] = snapshot_props(v, depth + 1)
        elif isinstance(v, (bool, int, float, str)):
            out[k] = v
        elif isinstance(v, set):
            out[k] = {"__set__": sorted(v)}
        else:
            try:
                out[k] = {"__seq__": list(v)}
            except TypeError:
                pass
    return out


def restore_props(struct, snap):
    if struct is None:
        return
    for k, v in snap.items():
        if isinstance(v, dict) and "__set__" in v:
            v = set(v["__set__"])
        elif isinstance(v, dict) and "__seq__" in v:
            v = v["__seq__"]
        elif isinstance(v, dict):
            restore_props(getattr(struct, k, None), v)
            continue
        try:
            setattr(struct, k, v)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            pass


def sky_world():
    """The world of the add-on, if there is one in the file."""
    return next((w for w in bpy.data.worlds if w.get(SKY_TAG)), None)


def make_sky():
    """A Physical Sky world of its own (when the setup scene is not there)."""
    w = bpy.data.worlds.new(SKY_NAME)
    if hasattr(w, "use_nodes") and not w.node_tree:
        w.use_nodes = True
    nt = w.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    bg = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBackground"), None)
    if bg is None:
        bg = nt.nodes.new("ShaderNodeBackground")
        out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputWorld"), None) or \
            nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(bg.outputs[0], out.inputs[0])
    nt.links.new(sky.outputs[0], bg.inputs[0])
    # the values of the setup scene's sky (user, 2026-09-29: strength 0.2, altitude 3000 m)
    for k, v in (("sky_type", 'MULTIPLE_SCATTERING'), ("sun_elevation", 1.0472), ("sun_rotation", 2.0944),
                 ("sun_size", 0.009512), ("altitude", 3000.0)):
        try:
            setattr(sky, k, v)
        except (AttributeError, TypeError, ValueError):
            pass
    bg.inputs["Strength"].default_value = 0.2
    out = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputWorld")
    x = 0
    for n in (sky, bg, out):            # side by side, left to right
        n.location = (x, 0)
        x += n.width + 60
    return w


BELOW_TAG = "rb_sky_below"              # the world of the view Bottom: the sky mirrored vertically


BELOW_NAME = "Renderbricks Sky Below"


SUN_BASE = "rb_sun_base"                # sky world: sun_rotation of its Sky Textures while the sun turns


SUN_FOLLOW = "rb_sun_follow"            # scene: the sun turns with the camera (user, 2026-09-28)


SKY_RES = 2048                          # width of the panorama of the sky (equirectangular, 2:1)


_SKY_PROPS = ("sky_type", "sun_disc", "sun_size", "sun_intensity", "sun_elevation", "altitude", "air_density",
              "aerosol_density", "ozone_density", "dust_density", "turbidity", "ground_albedo", "sun_direction")


def sky_nodes(world):
    if world is None or not world.node_tree:
        return []
    return [n for n in world.node_tree.nodes if n.bl_idname == "ShaderNodeTexSky"]


def sun_rotations(world):
    """The fixed sun_rotation of every Sky Texture: the stored one while the sun turns, else the current."""
    base = world.get(SUN_BASE) if world is not None else None
    nodes = sky_nodes(world)
    if base is not None and len(base) == len(nodes):
        return [float(b) for b in base]
    return [n.sun_rotation for n in nodes]


def _plain(v):
    if isinstance(v, str) or isinstance(v, bool):
        return v
    if hasattr(v, "__len__"):
        return [round(float(x), 5) for x in v]
    return round(float(v), 5)


def sky_signature(world):
    """What the look of the sky depends on (the sun at its fixed rotation): the panorama of the view Bottom
    is made again only when this changes."""
    import json
    parts = []
    rots = iter(sun_rotations(world))
    for n in sorted(world.node_tree.nodes, key=lambda n: n.name):
        d = {"t": n.bl_idname, "mute": n.mute}
        for p in _SKY_PROPS:
            if hasattr(n, p):
                d[p] = _plain(getattr(n, p))
        if n.bl_idname == "ShaderNodeTexSky":
            d["sun_rotation"] = round(next(rots, n.sun_rotation), 5)
        for i in n.inputs:
            v = getattr(i, "default_value", None)
            if v is not None and not i.is_linked:
                try:
                    d["in_" + i.identifier] = _plain(v)
                except (TypeError, ValueError):
                    pass
        parts.append(d)
    parts.append(sorted(f"{l.from_node.name}.{l.from_socket.identifier}>{l.to_node.name}.{l.to_socket.identifier}"
                        for l in world.node_tree.links))
    return json.dumps(parts, sort_keys=True)


_BAKE_SCRIPT = '''
import bpy, sys, math
a = sys.argv[sys.argv.index("--") + 1:]
lib, name, out, res = a[0], a[1], a[2], int(a[3])
with bpy.data.libraries.load(lib) as (src, dst):
    dst.worlds = [name]
sc = bpy.context.scene
sc.world = dst.worlds[0]
for o in list(sc.objects):
    bpy.data.objects.remove(o)
cam = bpy.data.objects.new("pano", bpy.data.cameras.new("pano"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = 'PANO'
try:
    cam.data.panorama_type = 'EQUIRECTANGULAR'
except AttributeError:
    cam.data.cycles.panorama_type = 'EQUIRECTANGULAR'
cam.rotation_euler = (math.pi / 2, 0.0, -math.pi / 2)   # the orientation of an Environment Texture
r = sc.render
r.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = 16
sc.cycles.use_denoising = False
r.resolution_x, r.resolution_y, r.resolution_percentage = res, res // 2, 100
r.film_transparent = False
r.image_settings.file_format = 'OPEN_EXR'
r.image_settings.color_depth = '32'
r.image_settings.exr_codec = 'ZIP'
r.filepath = out
bpy.ops.render.render(write_still=True)
print("SKYBAKE OK")
'''


def bake_sky_panorama(sky, res=None):
    """The sky rendered as an equirectangular panorama (linear EXR) by a Blender of its own - a render in
    this Blender would overwrite the Render Result. The image is packed into the file and remembers
    the signature of the sky it shows. Returns the image or None."""
    import os, shutil, subprocess, tempfile
    res = int(os.environ.get("RENDERBRICKER_SKY_RES", 0) or 0) or res or SKY_RES
    nodes = sky_nodes(sky)
    now = [n.sun_rotation for n in nodes]
    tmp = tempfile.mkdtemp(prefix="rb_sky_")
    lib, out, script = (os.path.join(tmp, f) for f in ("sky.blend", "sky_below.exr", "bake_sky.py"))
    try:
        try:
            for n, r in zip(nodes, sun_rotations(sky)):     # the sun at its fixed place
                n.sun_rotation = r
            bpy.data.libraries.write(lib, {sky}, fake_user=True)
        finally:
            for n, r in zip(nodes, now):
                n.sun_rotation = r
        with open(script, "w", encoding="utf-8") as f:
            f.write(_BAKE_SCRIPT)
        try:
            p = subprocess.run([bpy.app.binary_path, "-b", "--factory-startup", "--python", script, "--",
                                lib, sky.name, out, str(res)], capture_output=True, text=True, errors="replace",
                               timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as e:
            print("Renderbricker: sky panorama not made:", e)
            return None
        if "SKYBAKE OK" not in p.stdout or not os.path.isfile(out):
            print("Renderbricker: sky panorama not made:", (p.stdout + p.stderr)[-600:])
            return None
        old = bpy.data.images.get(BELOW_NAME)
        if old is not None:
            bpy.data.images.remove(old)
        img = bpy.data.images.load(out, check_existing=False)
        img.name = BELOW_NAME
        img.pack()
        img.filepath = ""
        img["rb_sig"] = sky_signature(sky)
        return img
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sky_below(sky):
    """The world of the view Bottom (user, 2026-09-28): the add-on's sky mirrored vertically, so the sun
    and the bright sky are below the model and light its underside exactly as they light the top from
    above. The Sky Texture cannot be mirrored (its Vector input is disabled for the physical skies, and
    a sun below the horizon is night), so the sky is rendered once as a panorama and shown by an
    Environment Texture behind a Mapping node (scale Z -1). Made again only when the sky changes."""
    sig = sky_signature(sky)
    img = bpy.data.images.get(BELOW_NAME)
    if img is None or img.get("rb_sig") != sig:
        img = bake_sky_panorama(sky)
        if img is None:
            return None
    w = next((w for w in bpy.data.worlds if w.get(BELOW_TAG)), None)
    if w is None:
        w = bpy.data.worlds.new(BELOW_NAME)
        w[BELOW_TAG] = True
        if hasattr(w, "use_nodes") and not w.node_tree:
            w.use_nodes = True
    nt = w.node_tree
    env = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeTexEnvironment"), None)
    if env is not None and nt.nodes.get("Mirror") is not None:
        env.image = img
        return w
    nt.nodes.clear()
    coord = nt.nodes.new("ShaderNodeTexCoord")
    m = nt.nodes.new("ShaderNodeMapping")
    m.name = m.label = "Mirror"
    m.vector_type = 'POINT'
    m.inputs["Scale"].default_value = (1.0, 1.0, -1.0)
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = img
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    for i, n in enumerate((coord, m, env, bg, out)):
        n.location = (-800 + 220 * i, 0)
    nt.links.new(coord.outputs["Generated"], m.inputs["Vector"])
    nt.links.new(m.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs[0])
    return w


def camera_turn(scene):
    """How far the camera "Renderbricks" is turned about Z from the view it was set up with (radians)."""
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None or "rb_base_rotation" not in cam:
        return 0.0
    return cam.rotation_euler[2] - float(cam["rb_base_rotation"][2])


def apply_sky(scene, view):
    """The add-on's sky for a view: the sun at its fixed place, or turned with the camera (scene
    rb_sun_follow, user 2026-09-28; sun_rotation turns the other way round than the camera: the sun's
    azimuth is 90 deg - sun_rotation); the view Bottom gets the mirrored sky. A world of the user is
    never touched. Returns a note or ""."""
    w = scene.world
    if w is None or not (w.get(SKY_TAG) or w.get(BELOW_TAG)):
        return ""
    sky = sky_world()
    if sky is None:
        return ""
    nodes = sky_nodes(sky)
    follow = bool(scene.get(SUN_FOLLOW))
    turn = camera_turn(scene) if follow else 0.0
    if follow:
        if sky.get(SUN_BASE) is None or len(sky[SUN_BASE]) != len(nodes):
            sky[SUN_BASE] = [n.sun_rotation for n in nodes]
        for n, b in zip(nodes, sky[SUN_BASE]):
            n.sun_rotation = float(b) - turn
    elif sky.get(SUN_BASE) is not None:                 # back to the fixed place
        for n, b in zip(nodes, sky[SUN_BASE]):
            n.sun_rotation = float(b)
        del sky[SUN_BASE]
    if view != "BOTTOM":
        scene.world = sky
        return ""
    below = sky_below(sky)
    if below is None:
        scene.world = sky
        return "mirrored sky not made (see the console)"
    m = below.node_tree.nodes.get("Mirror")
    if m is not None:
        m.inputs["Rotation"].default_value = (0.0, 0.0, -turn)
    scene.world = below
    return ""


def apply_template(scene, path):
    """Render settings and colour management of the first scene in the setup file; its world becomes
    the add-on's sky (tagged, kept once), its camera gives direction and lens of the camera
    "Renderbricks". Returns (sky world or None, camera settings or None)."""
    import os
    if not path or not os.path.isfile(path):
        return None, None
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.scenes = src.scenes[:1]
    if not dst.scenes or dst.scenes[0] is None:
        return None, None
    tpl = dst.scenes[0]
    cam = tpl.camera
    cam_set = None
    if cam is not None and cam.type == 'CAMERA':
        d = cam.data
        # matrix_basis: loaded objects have no evaluated matrix_world yet (it read as the identity)
        cam_set = {"rotation": tuple(cam.matrix_basis.to_euler()), "lens": d.lens, "sensor_width": d.sensor_width,
                   "sensor_fit": d.sensor_fit, "clip_start": d.clip_start}
    for attr in RENDER_STRUCTS:
        copy_props(getattr(tpl, attr, None), getattr(scene, attr, None))
    if tpl.render.engine:
        scene.render.engine = tpl.render.engine
    world = tpl.world
    objs = list(tpl.objects)
    bpy.data.scenes.remove(tpl)
    for o in objs:                      # the setup scene's own objects are not taken over
        if o.users == 0:
            bpy.data.objects.remove(o)
    if world is not None:
        world[SKY_TAG] = True
    return world, cam_set


def visible_meshes(scene):
    vl = scene.view_layers[0] if scene.view_layers else None
    out = []
    for o in scene.objects:
        if o.type == 'MESH' and o.name != copies.WORK_NAME:
            try:
                vis = o.visible_get(view_layer=vl) if vl else not o.hide_get()
            except (RuntimeError, TypeError):
                vis = True
            if vis:
                out.append(o)
    return out


def frame_camera(scene, cam, depsgraph):
    """Move the camera (keeping its direction) so that all visible meshes fill the picture, 5 % margin.
    Returns False without meshes."""
    import numpy as np
    from mathutils import Vector
    obs = visible_meshes(scene)
    if not obs:
        return False
    pts = np.empty((len(obs) * 8, 3))
    for i, o in enumerate(obs):
        m = np.array(o.matrix_world)
        bb = np.array(o.bound_box)
        pts[i * 8:i * 8 + 8] = bb @ m[:3, :3].T + m[:3, 3]
    c = (pts.min(0) + pts.max(0)) / 2
    pts = c + (pts - c) * CAMERA_MARGIN
    loc, _scale = cam.camera_fit_coords(depsgraph, pts.ravel().tolist())
    cam.location = loc
    r = float(np.linalg.norm(pts - c, axis=1).max())
    d = (Vector(loc) - Vector(c.tolist())).length
    cam.data.clip_end = max(CLIP_END, 2.0 * (d + r))     # very large scenes: nothing cut off
    # scenes at real size (NINJAGO City imported under an empty at scale 0.001 = metric like the real
    # set, 0.63 m high): the near clip stays in front of the model
    cam.data.clip_start = min(cam.data.clip_start, max(1e-4, 0.5 * (d - r)))
    return True


def render_camera(scene, create=True, setup=None):
    """The camera "Renderbricks" (made when missing and create), linked to the scene; a new one takes
    direction and lens of the setup scene's camera (setup), else Blender's default camera angle and
    50 mm. (camera, made)."""
    cam = bpy.data.objects.get(CAMERA_NAME)
    made = False
    if (cam is None or cam.type != 'CAMERA') and create:
        data = bpy.data.cameras.new(CAMERA_NAME)
        data.lens = 50.0
        cam = bpy.data.objects.new(CAMERA_NAME, data)
        cam.rotation_euler = CAMERA_ANGLE
        if setup:
            cam.rotation_euler = setup["rotation"]
            for k in ("lens", "sensor_width", "sensor_fit", "clip_start"):
                try:
                    setattr(data, k, setup[k])
                except (KeyError, TypeError, ValueError):
                    pass
        cam["rb_base_rotation"] = tuple(cam.rotation_euler)     # the Front view of the six views
        made = True
    if cam is not None and cam.name not in scene.objects:
        scene.collection.objects.link(cam)
    return cam, made


# the six views of the render camera (user, 2026-09-28): Front is the camera's direction as set up
# (from the setup scene), Right / Back / Left orbit the model by 90° steps at the same tilt, Top and
# Bottom look straight down and up; every view is framed again
CAMERA_VIEWS = (("FRONT", "Front", 0.0), ("RIGHT", "Right", 90.0), ("BACK", "Back", 180.0),
                ("LEFT", "Left", 270.0), ("TOP", "Top", None), ("BOTTOM", "Bottom", None))


TOP_ALIGNED = True      # Top / Bottom square to the model's axes, longer side across (user, 2026-09-28)


def model_extent(scene):
    """Extent of all visible parts along world X, Y and Z."""
    import numpy as np
    obs = visible_meshes(scene)
    if not obs:
        return 0.0, 0.0, 0.0
    pts = np.concatenate([np.array(o.bound_box) @ np.array(o.matrix_world)[:3, :3].T + np.array(o.matrix_world)[:3, 3]
                          for o in obs])
    ext = pts.max(0) - pts.min(0)
    return float(ext[0]), float(ext[1]), float(ext[2])


def footprint(scene):
    """Extent of all visible parts along world X and Y."""
    return model_extent(scene)[:2]


def picture_orientation(scene, view="FRONT"):
    """Landscape or portrait from the model's proportions (user, 2026-09-28): taller than its widest
    side -> portrait (9:16 from a 16:9 resolution), else landscape; Top and Bottom always landscape
    (the longer side of the footprint lies across). Turns the render resolution; True for portrait."""
    dx, dy, dz = model_extent(scene)
    portrait = view not in ("TOP", "BOTTOM") and dz > max(dx, dy)
    r = scene.render
    long_side, short_side = max(r.resolution_x, r.resolution_y), min(r.resolution_x, r.resolution_y)
    want = (short_side, long_side) if portrait else (long_side, short_side)
    if (r.resolution_x, r.resolution_y) != want:
        r.resolution_x, r.resolution_y = want
    return portrait


def aligned_yaw(scene, front_yaw):
    """Top / Bottom: the camera square to the world axes with the longer side of the model across the
    picture; of the two such directions the one closest to Front, so the front stays at the bottom."""
    import math
    dx, dy = footprint(scene)
    cands = (0.0, math.pi) if dx >= dy else (math.pi / 2, 3 * math.pi / 2)
    return min(cands, key=lambda a: abs(math.remainder(a - front_yaw, 2 * math.pi)))


def camera_view(scene, view, depsgraph=None):
    """Turn the camera "Renderbricks" to one of the six views and frame the model. Returns False
    without the camera or visible parts."""
    import math
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None or cam.type != 'CAMERA':
        return False
    base = tuple(cam.get("rb_base_rotation", ())) or tuple(cam.rotation_euler)
    if "rb_base_rotation" not in cam:
        cam["rb_base_rotation"] = base
    tilt, yaw = base[0], base[2]
    step = {k: d for k, _label, d in CAMERA_VIEWS}[view]
    if view in ("TOP", "BOTTOM"):
        y = aligned_yaw(scene, yaw) if TOP_ALIGNED else yaw
        rot = (0.0, 0.0, y) if view == "TOP" else (math.pi, 0.0, y)
    else:
        rot = (tilt, 0.0, yaw + math.radians(step))
    cam.rotation_euler = rot
    picture_orientation(scene, view)
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    dg.update()
    scene["rb_camera_view"] = view
    apply_sky(scene, view)                          # sun fixed or turned; Bottom: the sky mirrored
    return frame_camera(scene, cam, dg)


ISOLATE_FLAG = "rb_cam_hidden"      # object: what the render camera hid (1 viewport, 2 render)


def isolate(scene, collections):
    """Render camera with chosen collections (user, 2026-09-28): only their parts are shown and rendered.
    Every other object of the scene (not the camera) is disabled in viewports and renders; what was
    hidden before stays as it is and is not recorded, so unisolate() gives back exactly the state
    before. Returns the number of objects hidden."""
    unisolate(scene)
    if not collections:
        return 0
    keep = set()
    for c in collections:
        keep.update(c.all_objects)
    cam = bpy.data.objects.get(CAMERA_NAME)
    n = 0
    for o in scene.objects:
        if o in keep or o == cam or o == scene.camera:
            continue
        flag = 0
        try:
            if not o.hide_viewport:
                o.hide_viewport = True
                flag |= 1
            if not o.hide_render:
                o.hide_render = True
                flag |= 2
        except (AttributeError, RuntimeError):     # linked, not editable
            continue
        if flag:
            o[ISOLATE_FLAG] = flag
            n += 1
    scene["rb_isolated"] = n
    return n


def unisolate(scene):
    """Give back the visibility the render camera took (only what it changed)."""
    for o in scene.objects:
        f = o.get(ISOLATE_FLAG)
        if not f:
            continue
        try:
            if f & 1:
                o.hide_viewport = False
            if f & 2:
                o.hide_render = False
            del o[ISOLATE_FLAG]
        except (AttributeError, RuntimeError, KeyError):
            pass
    if "rb_isolated" in scene:
        del scene["rb_isolated"]


def render_camera_is_on(scene):
    return bool(scene.get("rb_render_on"))


def render_camera_on(scene, template="", depsgraph=None, collections=None, fresh=False):
    """Keep the scene's camera, world and render settings, then make the camera "Renderbricks" and the
    world "Renderbricks Sky" active and take over the setup scene's render settings. A new camera is
    framed; an existing one stays where it is. Returns a short text for the summary."""
    import json
    if render_camera_is_on(scene):
        return "render camera already on"
    before = {"camera": scene.camera.name if scene.camera else "",
              "world": scene.world.name if scene.world else "",
              "world_fake": bool(scene.world and scene.world.use_fake_user),
              "settings": {a: snapshot_props(getattr(scene, a, None)) for a in RENDER_STRUCTS}}
    scene["rb_render_before"] = json.dumps(before)
    if scene.world is not None:
        scene.world.use_fake_user = True    # an unused world would not be saved
    have = sky_world()
    taken, cam_set = apply_template(scene, template)
    if taken is not None and have is not None and taken != have:
        bpy.data.worlds.remove(taken)       # the sky is in the file already
        taken = None
    sky = have or taken or make_sky()
    sky[SKY_TAG] = True
    scene.world = sky
    last = None if fresh else scene.get(LAST_KEY)
    if last:                            # the settings of the last OFF again (user, 2026-09-28)
        for a, snap in json.loads(last).items():
            restore_props(getattr(scene, a, None), snap)
    else:                               # the first time (or fresh): the setup scene, samples on Low
        for owner, prop in (("cycles", "samples"), ("eevee", "taa_render_samples")):
            st = getattr(scene, owner, None)
            if st is not None and hasattr(st, prop):
                setattr(st, prop, START_SAMPLES)
    cam, made = render_camera(scene, setup=cam_set)
    scene.camera = cam
    hidden = isolate(scene, collections)    # only these collections shown and rendered
    if made:
        scene["rb_camera_view"] = "FRONT"
    sky_note = apply_sky(scene, scene.get("rb_camera_view", "FRONT"))
    res_before = (scene.render.resolution_x, scene.render.resolution_y)
    portrait = picture_orientation(scene, scene.get("rb_camera_view", "FRONT"))
    turned = (scene.render.resolution_x, scene.render.resolution_y) != res_before
    framed = False
    if made or turned or hidden:
        dg = depsgraph or bpy.context.evaluated_depsgraph_get()
        dg.update()
        framed = frame_camera(scene, cam, dg)
    scene["rb_render_on"] = True
    import os
    used = bool(template) and os.path.isfile(template)
    return ("render camera on: camera Renderbricks" + (" created and framed" if made and framed else
                                                       " framed" if framed else "")
            + (", portrait 9:16" if portrait else ", landscape 16:9")
            + (f", only {', '.join(c.name for c in collections)}" if collections else "")
            + f", world {scene.world.name}" + (", your last Renderbricks settings" if last else
                                               ", render settings of the setup scene" if used else "")
            + (f"; {sky_note}" if sky_note else ""))


def render_camera_off(scene):
    """Back to the scene's camera, world and render settings from before ON."""
    import json
    if not render_camera_is_on(scene):
        return "render camera already off"
    before = json.loads(scene.get("rb_render_before", "{}"))
    scene[LAST_KEY] = json.dumps({a: snapshot_props(getattr(scene, a, None)) for a in RENDER_STRUCTS})
    unisolate(scene)
    for a, snap in before.get("settings", {}).items():
        restore_props(getattr(scene, a, None), snap)
    scene.camera = bpy.data.objects.get(before.get("camera", "")) if before.get("camera") else None
    world = bpy.data.worlds.get(before.get("world", "")) if before.get("world") else None
    scene.world = world
    if world is not None:
        world.use_fake_user = before.get("world_fake", False)
    scene["rb_render_on"] = False
    if "rb_render_before" in scene:
        del scene["rb_render_before"]
    return "render camera off: camera, world and render settings as before"
