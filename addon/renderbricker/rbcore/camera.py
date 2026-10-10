"""The render camera: camera Renderbricks, sky, the six views, the setup scene's render settings."""
import bpy, math
import numpy as np
from mathutils import Vector
from . import copies, workscene


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
    for p in sorted(struct.bl_rna.properties, key=lambda p: p.identifier in LATE_PROPS):
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


# Settings whose allowed values depend on another one: set last. The look's items depend on the view transform -
# set before it, a look of the other view was refused and the view then reset the look (run 213: switching the
# render camera on again lost "ACES 2.0 - Reference Gamut Compression", switching off a look such as AgX Punchy).
LATE_PROPS = ("look",)


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
    for k, v in sorted(snap.items(), key=lambda kv: kv[0] in LATE_PROPS):   # snapshots of 1.2.2 kept the old order
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


def valid_sky_types(world):
    """A sky type this Blender does not know (the setup scene, saved by 5.x with Multiple Scattering,
    read by 4.5) reads as "" and crashed Cycles in 4.5: such skies become Nishita, the physical sky of
    4.5. Returns the number of nodes changed."""
    n = 0
    for node in (world.node_tree.nodes if world is not None and world.node_tree else []):
        if node.bl_idname != "ShaderNodeTexSky":
            continue
        known = {i.identifier for i in node.bl_rna.properties["sky_type"].enum_items}
        if node.sky_type not in known:
            for t in ('MULTIPLE_SCATTERING', 'NISHITA'):
                if t in known:
                    node.sky_type = t
                    n += 1
                    break
    return n


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
    # the values of the setup scene's sky (user, 2026-09-29: altitude 3000 m; 2026-09-30: strength
    # 0.03; the sun disc stays on - it gives the highlights and the sharpness of the shadows)
    for k, v in (("sky_type", 'MULTIPLE_SCATTERING'), ("sun_elevation", math.radians(SUN_STANDARD["elevation"])),
                 ("sun_rotation", math.radians(SUN_STANDARD["rotation"])), ("sun_size", 0.009512),
                 ("altitude", SUN_STANDARD["altitude"]), ("sun_disc", True)):
        try:
            setattr(sky, k, v)
        except (AttributeError, TypeError, ValueError):
            pass
    bg.inputs["Strength"].default_value = SUN_STANDARD["strength"]
    arrange_world(nt)
    return w


# ---------------------------------------------------------------- tidy node trees (user, 2026-09-30)
# The add-on's world trees are laid out in columns along the signal (inputs left, World Output right),
# every column centred on one line, NODE_GAP apart. node.dimensions is only known once a node editor has
# drawn the node, so the sizes Blender 5.2 draws them in are the fallback (measured,
# _CLAUDE_/scripts/tools/measure_world_nodes.py). A tree with nodes of the user's is never moved.
NODE_GAP = (60, 40)                     # between columns, between nodes of one column


NODE_SIZE = {"ShaderNodeOutputWorld": (140, 96), "ShaderNodeBackground": (140, 99),
             "ShaderNodeTexSky": (160, 309), "ShaderNodeLightPath": (140, 358), "ShaderNodeMix": (140, 220),
             "ShaderNodeTexCoord": (140, 236), "ShaderNodeMapping": (140, 351),
             "ShaderNodeTexEnvironment": (240, 199)}


def _node_size(n):
    w, h = n.dimensions
    if w > 0 and h > 0:
        s = bpy.context.preferences.system.ui_scale if bpy.context.preferences else 1.0
        return w / s, h / s
    h = NODE_SIZE[n.bl_idname][1]
    if n.bl_idname == "ShaderNodeTexSky" and not getattr(n, "sun_disc", True):
        h = 284                         # without the disc its size and intensity rows are hidden
    return n.width, h


def arrange_world(nt):
    """Lay out a world tree of the add-on; False (nothing moved) when it holds other nodes."""
    if any(n.bl_idname not in NODE_SIZE for n in nt.nodes):
        return False
    out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputWorld"), None)
    if out is None:
        return False
    # column = longest way to the World Output; within a column in the order of the sockets fed
    col, order = {out: 0}, {out: (0,)}
    todo = [out]
    while todo:
        n = todo.pop(0)
        for i, s in enumerate(n.inputs):
            for l in s.links:
                f = l.from_node
                if col.get(f, -1) < col[n] + 1:
                    col[f], order[f] = col[n] + 1, order[n] + (i,)
                    todo.append(f)
    first = max(col.values())
    for n in nt.nodes:                  # not linked (Light Path while the sun is in the picture): on top of
        col.setdefault(n, first)        # the first column, where it stands when linked
        order.setdefault(n, (-1,))
    x = 0.0
    for c in range(max(col.values()), -1, -1):
        nodes = sorted((n for n in nt.nodes if col[n] == c), key=lambda n: order[n])
        if not nodes:
            continue
        sizes = [_node_size(n) for n in nodes]
        y = (sum(h for _, h in sizes) + NODE_GAP[1] * (len(nodes) - 1)) / 2
        for n, (w, h) in zip(nodes, sizes):   # location is the top left corner; column centred on y = 0
            n.location = (x, y)
            y -= h + NODE_GAP[1]
        x += max(w for w, _ in sizes) + NODE_GAP[0]
    return True


# ---------------------------------------------------------------- sun sliders (user, 2026-09-30)
# While the render camera is on, four sliders set the add-on's sky: elevation, rotation, altitude and
# the strength of the Background. Their values are kept on the sky world (rb_sun); the sky nodes follow.
# Elevation runs from below the horizon over the zenith to the other side (-15 ... 195 deg).
SUN_KEY = "rb_sun"


SUN_STANDARD = {"elevation": 60.0, "rotation": 120.0, "altitude": 3000.0, "strength": 0.03}


ACES_STRENGTH = 0.06                    # the strength standard under ACES 2.0 (maintainer, 2026-10-05; AgX 0.03)


def sun_standard(scene, key):
    """The standard of a sun slider; the strength depends on the view (ACES 2.0: 0.06, else 0.03)."""
    if key == "strength" and scene is not None and scene.view_settings.view_transform == ACES_VIEW:
        return ACES_STRENGTH
    return SUN_STANDARD[key]


SUN_GRID = {                            # the values the step buttons go to
    "elevation": [-15.0] + [float(d) for d in range(-10, 191, 10)] + [195.0],
    "rotation": [float(d) for d in range(0, 361, 10)],
    "altitude": [float(m) for m in range(0, 10001, 1000)] + [float(m) for m in range(20000, 100001, 10000)],
    "strength": [round(0.01 * i, 2) for i in range(1, 11)],
}


ALTITUDE_KNEE = 10000.0                 # the altitude slider: 0 ... 10,000 m on its first half (user, 2026-09-30)


def altitude_position(m):
    """Altitude in metres -> position on the slider (0 ... 1): 0 ... 10,000 m on the first half,
    10,000 ... 100,000 m on the second."""
    m = min(max(m, 0.0), 100000.0)
    if m <= ALTITUDE_KNEE:
        return 0.5 * m / ALTITUDE_KNEE
    return 0.5 + 0.5 * (m - ALTITUDE_KNEE) / (100000.0 - ALTITUDE_KNEE)


def altitude_from_position(p):
    p = min(max(p, 0.0), 1.0)
    if p <= 0.5:
        return ALTITUDE_KNEE * p / 0.5
    return ALTITUDE_KNEE + (100000.0 - ALTITUDE_KNEE) * (p - 0.5) / 0.5


def sun_values(world):
    """The slider values of the sky (degrees, metres, strength): the stored ones, else read from its
    first Sky Texture and Background."""
    out = dict(SUN_STANDARD)
    if world is None:
        return out
    nodes = sky_nodes(world)
    if nodes:
        n = _main_sky(world) or nodes[0]
        out["elevation"] = math.degrees(n.sun_elevation)
        out["rotation"] = math.degrees(sun_rotations(world)[nodes.index(n)]) % 360.0
        out["altitude"] = float(n.altitude)
    bg = [n for n in world.node_tree.nodes if n.bl_idname == "ShaderNodeBackground"] if world.node_tree else []
    if bg:
        out["strength"] = float(bg[0].inputs["Strength"].default_value)
    stored = world.get(SUN_KEY)
    if stored is not None:
        for k in SUN_STANDARD:
            if k in stored:
                out[k] = float(stored[k])
    return out


def sun_step(key, value, direction):
    """The next value of the grid above (direction 1) or below (-1); rotation goes round."""
    grid = SUN_GRID[key]
    eps = 1e-6 * max(1.0, abs(value))
    if direction > 0:
        up = [g for g in grid if g > value + eps]
        if up:
            return up[0]
        return grid[1] if key == "rotation" else grid[-1]
    down = [g for g in grid if g < value - eps]
    if down:
        return down[-1]
    return grid[-2] if key == "rotation" else grid[0]


def set_sun(scene, key, value):
    """Set one slider value on the add-on's sky and its nodes. Returns True when the scene shows the
    mirrored sky of Bottom, which then has to be made again."""
    w = sky_world()
    if w is None:
        return False
    vals = sun_values(w)
    vals[key] = float(value)
    w[SUN_KEY] = vals
    elev, rot = vals["elevation"], vals["rotation"]
    over = elev > 90.0 and _elevation_max() < math.pi / 2 + 1e-4     # older Blender: over the zenith by
    if over:                                                            # turning the sun round
        elev, rot = 180.0 - elev, rot + 180.0
    r = math.radians(rot % 360.0)
    nodes = sky_nodes(w)
    turn = 0.0
    if w.get(SUN_BASE) is not None:                     # the sun turns with the camera: the base moves
        w[SUN_BASE] = [r] * len(nodes)
        turn = camera_turn(scene)
    for n in nodes:
        n.sun_elevation = math.radians(elev)
        n.sun_rotation = r - turn
        try:
            n.altitude = vals["altitude"]
        except (AttributeError, TypeError, ValueError):
            pass
    for n in w.node_tree.nodes:
        if n.bl_idname == "ShaderNodeBackground":
            n.inputs["Strength"].default_value = vals["strength"]
    from . import engine                    # the sun lamp of EEVEE follows
    engine.sync(scene)
    return bool(scene.world is not None and scene.world.get(BELOW_TAG))


# ---------------------------------------------------------------- sun in picture (user, 2026-09-30)
# The sun disc gives the highlights and the sharpness of the shadows, but it need not be seen in the
# picture: a second Sky Texture without the disc (same values) is shown to camera rays only - a Mix by
# Light Path > Is Camera Ray in front of the Background. The switch links or unlinks that factor.
SUN_PICTURE = "rb_sun_in_picture"       # sky world: the sun disc is seen by the camera (default False)


CAMERA_SKY = "Sky (camera)"


PICTURE_MIX = "Sun in picture"


def _main_sky(world):
    return next((n for n in sky_nodes(world) if n.name != CAMERA_SKY), None)


def sun_picture_setup(world):
    """Make (once) and set the switch of the sky: the camera sees the sky without the sun disc unless
    SUN_PICTURE is set. The camera's sky takes the values of the main sky every time. False when the
    node tree has no Sky Texture into a Background."""
    if world is None or not world.node_tree:
        return False
    nt = world.node_tree
    main = _main_sky(world)
    if main is None:
        return False
    cam = nt.nodes.get(CAMERA_SKY)
    mix = nt.nodes.get(PICTURE_MIX)
    if cam is None or mix is None:
        link = next((l for l in nt.links if l.from_node == main and l.to_node.bl_idname == "ShaderNodeBackground"), None)
        if link is None:
            return False
        to_socket = link.to_socket
        nt.links.remove(link)
        cam = nt.nodes.new("ShaderNodeTexSky")
        cam.name = cam.label = CAMERA_SKY
        path = nt.nodes.new("ShaderNodeLightPath")
        path.name = "Light Path"
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = 'RGBA'
        mix.name = mix.label = PICTURE_MIX
        rgba = [i for i in mix.inputs if i.type == 'RGBA']       # the colour sockets (the Mix node has
        out = next(o for o in mix.outputs if o.type == 'RGBA')    # float, vector ... ones as well)
        nt.links.new(main.outputs["Color"], rgba[0])              # A: with the disc (all other rays)
        nt.links.new(cam.outputs["Color"], rgba[1])               # B: without (camera rays)
        nt.links.new(out, to_socket)
        base = world.get(SUN_BASE)
        if base is not None:                                      # the sun turning with the camera
            world[SUN_BASE] = list(base) + [float(base[0])]
    for prop in _SKY_PROPS + ("sun_rotation",):
        if prop != "sun_disc" and hasattr(main, prop):
            try:
                setattr(cam, prop, getattr(main, prop))
            except (AttributeError, TypeError, ValueError):
                pass
    # EEVEE (engine.py): the lighting sky has no disc, so the camera's sky carries it when the sun is
    # to be seen, and camera rays always see the camera's sky
    eevee = bool(world.get("rb_eevee"))
    cam.sun_disc = eevee and bool(world.get(SUN_PICTURE))
    path = nt.nodes.get("Light Path")
    fac = mix.inputs[0]
    for l in list(nt.links):
        if l.to_socket == fac:
            nt.links.remove(l)
    if world.get(SUN_PICTURE) and not eevee:
        fac.default_value = 0.0
    elif path is not None:
        nt.links.new(path.outputs["Is Camera Ray"], fac)
    arrange_world(nt)                   # also tidies the trees of the test builds before
    return True


def _elevation_max():
    rna = bpy.types.ShaderNodeTexSky.bl_rna.properties["sun_elevation"]
    return rna.hard_max


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
nt = sc.world.node_tree
mix = nt.nodes.get("Sun in picture")        # the panorama lights Bottom: the sky with the sun disc
if mix is not None:
    for l in list(nt.links):
        if l.to_socket == mix.inputs[0]:
            nt.links.remove(l)
    mix.inputs[0].default_value = 0.0
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
        arrange_world(nt)
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
    nt.links.new(coord.outputs["Generated"], m.inputs["Vector"])
    nt.links.new(m.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs[0])
    arrange_world(nt)
    return w


def camera_turn(scene):
    """How far the camera "Renderbricks" is turned about Z from the view it was set up with (radians)."""
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None or "rb_base_rotation" not in cam:
        return 0.0
    return cam.rotation_euler[2] - float(cam["rb_base_rotation"][2])


def apply_sky(scene, view):
    """_apply_sky_worlds, then the sun lamp of EEVEE follows (engine.sync)."""
    note = _apply_sky_worlds(scene, view)
    from . import engine
    engine.sync(scene)
    return note


def _apply_sky_worlds(scene, view):
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
    sun_picture_setup(sky)                          # the sun disc lights, the camera does not see it
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
        if o.type == 'MESH' and o.name != workscene.WORK_NAME:
            try:
                vis = o.visible_get(view_layer=vl) if vl else not o.hide_get()
            except (RuntimeError, TypeError):
                vis = True
            if vis:
                out.append(o)
    return out


# ---------------------------------------------------------------- the parts' scale (user, 2026-09-30)
# The importer forks import at 0.001 (real size) and their panel scales the models by their import Empty.
# The render camera then has to follow: it keeps the scale it was framed for (CAM_UNIT) and, when the
# parts' scale changes, moves towards / away from the Empty by the same factor - the picture stays exactly
# as it was, also a camera set up by hand. EEVEE's absolute sizes follow the same unit (engine.scale_sizes).
CAM_UNIT = "rb_unit"                    # on the render camera: the parts' scale it was framed for


def world_unit(scene, sample=200):
    """Scale of the parts in the world: the median object scale of the visible meshes (1 for imports at
    scale 1, 0.001 for the importer forks' real size)."""
    obs = visible_meshes(scene)
    if not obs:
        return 1.0
    step = max(1, len(obs) // sample)
    s = sorted(sum(abs(x) for x in o.matrix_world.to_scale()) / 3.0 for o in obs[::step])
    u = s[len(s) // 2]
    return u if u > 0 else 1.0


def _scale_pivot(scene):
    """World position the parts are scaled about: their common top parent (the import Empty), else None."""
    tops = set()
    for o in visible_meshes(scene)[::50] or []:
        while o.parent is not None:
            o = o.parent
        tops.add(o)
        if len(tops) > 1:
            return None
    top = next(iter(tops), None)
    return top.matrix_world.translation.copy() if top is not None and top.type != 'MESH' else None


def follow_scale(scene, cam=None):
    """Keep the render camera's picture when the parts' scale changed since it was framed. True if moved."""
    cam = cam or scene.camera
    if cam is None or cam.type != 'CAMERA' or not cam.name.startswith(CAMERA_NAME) or not render_camera_is_on(scene):
        return False
    u = world_unit(scene)
    old = cam.get(CAM_UNIT)
    cam[CAM_UNIT] = u
    if not old or abs(u - old) <= abs(old) * 1e-6:
        return False
    f = u / old
    pivot = _scale_pivot(scene)
    if pivot is None:                   # parts without one common parent: frame them anew
        frame_camera(scene, cam, bpy.context.evaluated_depsgraph_get())
        return True
    cam.location = pivot + (cam.location - pivot) * f
    cam.data.clip_start = cam.data.clip_start * f
    cam.data.clip_end = max(CLIP_END, cam.data.clip_end * f)
    if cam.data.type == 'ORTHO':
        cam.data.ortho_scale = cam.data.ortho_scale * f
    return True


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
    cam[CAM_UNIT] = world_unit(scene)   # framed for this scale of the parts
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


# Colour management of the render camera (maintainer 2026-10-05, UPDATES #12): view ACES 2.0 with the
# reference gamut compression in Blender 5.x. The setup scene keeps its AgX view for Blender 4.5, which has no
# ACES 2.0. The file's working colour space is not touched (the importer converts its colours into it) - the
# summary only notes when it is not ACEScg.
ACES_VIEW = "ACES 2.0"


ACES_LOOK = "ACES 2.0 - Reference Gamut Compression"


OLD_SETUP_VIEW = ("AgX", "AgX - Base Contrast")    # the setup scene's view up to 1.2.2


def aces_view(scene, last=None):
    """ACES 2.0 + gamut compression; with the user's last settings (`last`, JSON) only if they still hold the
    old setup view. True if set."""
    import json
    if last:
        lv = json.loads(last).get("view_settings", {})
        if (lv.get("view_transform"), lv.get("look")) != OLD_SETUP_VIEW:
            return False                    # a view the user chose stays
    v = scene.view_settings
    try:
        v.view_transform = ACES_VIEW
        v.look = ACES_LOOK
    except (TypeError, ValueError):
        return False                        # Blender 4.5: no ACES 2.0, the setup scene's view stays
    return True


def working_space_note():
    """A note when the file's working colour space is not ACEScg (Blender 5.x), else ''."""
    cs = getattr(bpy.data, "colorspace", None)
    ws = getattr(cs, "working_space", None) if cs is not None else None
    return f"working colour space {ws} - ACES 2.0 works best in ACEScg" if ws and ws != "ACEScg" else ""


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
    valid_sky_types(sky)
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
    aces = aces_view(scene, last)
    if aces and abs(sun_values(sky)["strength"] - SUN_STANDARD["strength"]) < 1e-6:
        set_sun(scene, "strength", ACES_STRENGTH)   # the AgX standard becomes the ACES one; a value of the user stays
    ws_note = working_space_note()
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
    if not framed:                          # an existing camera: scale changed while it was off?
        follow_scale(scene, cam)
    import os
    used = bool(template) and os.path.isfile(template)
    return ("render camera on: camera Renderbricks" + (" created and framed" if made and framed else
                                                       " framed" if framed else "")
            + (", portrait 9:16" if portrait else ", landscape 16:9")
            + (f", only {', '.join(c.name for c in collections)}" if collections else "")
            + f", world {scene.world.name}" + (", your last Renderbricks settings" if last else
                                               ", render settings of the setup scene" if used else "")
            + (", view ACES 2.0 with gamut compression" if aces else "")
            + (f"; {sky_note}" if sky_note else "") + (f"; {ws_note}" if ws_note else ""))


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
    from . import engine                    # the sun lamp of EEVEE only with the render camera
    engine.sync(scene)
    return "render camera off: camera, world and render settings as before"
