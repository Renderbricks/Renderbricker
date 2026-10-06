"""Cycles or EEVEE with the Renderbricks sky (user 2026-09-30, UPDATES #7).

Cycles lights with the physical sky as it is: the Sky Texture with its sun disc. EEVEE reads the world
from a probe in which the 0.5 deg sun disc loses most of its energy (the sun came out far too weak,
run 31 of the importer project), so for EEVEE the sky lights without its disc and the Sun lamp
"Renderbricks Sun" stands in for it, linked to the sky: its direction is the sky's sun (elevation,
rotation, also over the zenith and turning with the camera; mirrored below the model for the view
Bottom), its angle the sun size, its strength and colour come from sun_lamp_table.json (measured in
Cycles, scripts/core/calibrate_sun_lamp.py) at the sky's elevation and altitude, times the
Background strength. Switching back and forth keeps everything; the lamp is only hidden in Cycles.
"""
import json
import math
import os

import bpy
from mathutils import Vector

from . import camera

LAMP_NAME = "Renderbricks Sun"
LAMP_TAG = "rb_sun_lamp"                # on the lamp object
EEVEE_KEY = "rb_eevee"                  # on the sky world: EEVEE mode (sky without its disc + lamp)
EEVEE_IDS = ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT')

_TABLE = []


def engine_ids():
    return {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}


def eevee_id():
    """EEVEE's identifier in this Blender (BLENDER_EEVEE_NEXT in 4.2-4.5, BLENDER_EEVEE from 5.0; the
    enum of 4.5 still lists the legacy BLENDER_EEVEE, which it refuses)."""
    if (4, 2) <= bpy.app.version < (5, 0) and 'BLENDER_EEVEE_NEXT' in engine_ids():
        return 'BLENDER_EEVEE_NEXT'
    return 'BLENDER_EEVEE'


def is_eevee(scene):
    return scene.render.engine in EEVEE_IDS


def lamp_table():
    if not _TABLE:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sun_lamp_table.json")
        try:
            with open(path, encoding="utf-8") as fh:
                _TABLE.append(json.load(fh))
        except (OSError, ValueError):
            _TABLE.append({})
    return _TABLE[0]


def _interp(xs, x):
    """Index and weight of x between the grid values xs (clamped)."""
    if x <= xs[0]:
        return 0, 0.0
    if x >= xs[-1]:
        return len(xs) - 2, 1.0
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            return i, (x - xs[i]) / (xs[i + 1] - xs[i])
    return len(xs) - 2, 1.0


def lamp_rgb(sky_type, elevation_deg, altitude):
    """Lamp strength per colour channel for Background strength 1: 0 with the sun at or below the
    horizon, fading in over the first degree; elevations over the zenith count from the other side."""
    e = elevation_deg
    if e > 90.0:
        e = 180.0 - e
    if e <= 0.0:
        return (0.0, 0.0, 0.0)
    t = lamp_table().get(sky_type) or next(iter(lamp_table().values()), None)
    if not t:
        return (0.0, 0.0, 0.0)
    els, alts, rgb = t["elevations"], t["altitudes"], t["rgb"]
    fade = min(1.0, e / els[0])
    i, u = _interp(els, max(e, els[0]))
    j, v = _interp(alts, altitude)
    out = []
    for c in range(3):
        a = rgb[j][i][c] * (1 - u) + rgb[j][i + 1][c] * u
        b = rgb[j + 1][i][c] * (1 - u) + rgb[j + 1][i + 1][c] * u
        out.append((a * (1 - v) + b * v) * fade)
    return tuple(out)


def lamp_object(scene, create=True):
    ob = next((o for o in bpy.data.objects if o.get(LAMP_TAG)), None)
    if ob is None and create:
        light = bpy.data.lights.new(LAMP_NAME, 'SUN')
        ob = bpy.data.objects.new(LAMP_NAME, light)
        ob[LAMP_TAG] = True
    if ob is not None and create and ob.name not in scene.collection.objects:
        scene.collection.objects.link(ob)
    return ob


def _background_strength(world):
    bg = next((n for n in world.node_tree.nodes if n.bl_idname == "ShaderNodeBackground"), None)
    return float(bg.inputs["Strength"].default_value) if bg else 1.0


def _show(ob, on):
    for prop in ("hide_render", "hide_viewport"):
        if getattr(ob, prop) == on:
            setattr(ob, prop, not on)


# EEVEE sizes in world units (run 197, user 2026-09-30: blotchy shadows at import scale 0.001, fine at 1):
# the lamp's shadow map texel and the thickness of Fast GI and screen tracing are absolute lengths. They are
# set for parts at scale 1 (1 unit = 1 mm, the setup scene's values) and follow the scale of the parts - the
# importer forks import at 0.001 (real size) and their panel scales the models.
EEVEE_SIZES = {"shadow_maximum_resolution": 0.001, "fast_gi_thickness_near": 0.25, "screen_trace_thickness": 0.2}


def scale_sizes(scene, light=None):
    """The EEVEE sizes for the parts' scale; writes only what changes."""
    u = camera.world_unit(scene)
    e = scene.eevee
    opts = getattr(e, "ray_tracing_options", None)
    for target, key in ((light, "shadow_maximum_resolution"), (e, "fast_gi_thickness_near"),
                        (opts, "screen_trace_thickness")):
        if target is not None and hasattr(target, key):
            v = EEVEE_SIZES[key] * u
            if abs(getattr(target, key) - v) > v * 1e-4:
                setattr(target, key, v)
    return u


def sync(scene):
    """Sky and lamp for the scene's engine: Cycles - sun disc on, lamp hidden; EEVEE - sun disc off
    (the camera may still see it, "Sun in picture"), lamp on and following the sky. Outside the render
    camera the lamp is hidden. Idempotent; writes only what changes."""
    sky = camera.sky_world()
    ob = lamp_object(scene, create=False)
    if sky is None or not camera.render_camera_is_on(scene):
        if ob is not None:
            _show(ob, False)
        return
    eevee = is_eevee(scene)
    if bool(sky.get(EEVEE_KEY)) != eevee:
        sky[EEVEE_KEY] = eevee
    main = camera._main_sky(sky)
    for n in camera.sky_nodes(sky):
        if n.name != camera.CAMERA_SKY and n.sun_disc == eevee:
            n.sun_disc = not eevee
    camera.sun_picture_setup(sky)
    if not eevee or main is None:
        if ob is not None:
            _show(ob, False)
        return
    ob = lamp_object(scene)
    light = ob.data
    e, r = main.sun_elevation, main.sun_rotation
    d = Vector((math.sin(r) * math.cos(e), math.cos(r) * math.cos(e), math.sin(e)))
    if scene.world is not None and scene.world.get(camera.BELOW_TAG):
        d.z = -d.z                                  # Bottom: the sky is mirrored below the model
    rot = d.to_track_quat('Z', 'Y').to_euler()
    if tuple(ob.rotation_euler) != tuple(rot):
        ob.rotation_euler = rot
    rgb = lamp_rgb(main.sky_type, math.degrees(e), float(getattr(main, "altitude", 0.0)))
    rgb = [c * _background_strength(sky) * float(getattr(main, "sun_intensity", 1.0)) for c in rgb]
    energy = max(rgb)
    colour = tuple(c / energy for c in rgb) if energy > 0 else (1.0, 1.0, 1.0)
    if abs(light.energy - energy) > 1e-6:
        light.energy = energy
    if tuple(round(c, 6) for c in light.color) != tuple(round(c, 6) for c in colour):
        light.color = colour
    if abs(light.angle - main.sun_size) > 1e-7:
        light.angle = main.sun_size
    if hasattr(light, "use_shadow_jitter") and not light.use_shadow_jitter:
        light.use_shadow_jitter = True              # soft shadow like the sun's size
    if getattr(light, "shadow_filter_radius", 0.0) != 0.0:
        light.shadow_filter_radius = 0.0            # unfiltered: closest to Cycles' shadow edges (run 235)
    scale_sizes(scene, light)                       # shadow and trace sizes follow the parts' scale (run 197)
    _show(ob, energy > 0)


def eevee_best(scene):
    """Everything EEVEE can do (user: "EEVEE shall use everything the renderer can do"): ray tracing at
    full resolution with denoising, Fast GI global illumination at full quality, shadows with the most
    rays and steps, a sharp world probe. Only settings of this Blender that exist are set."""
    e = scene.eevee
    wanted = {"use_shadows": True, "shadow_ray_count": 4, "shadow_step_count": 16, "shadow_resolution_scale": 1.0,
              "use_raytracing": True, "ray_tracing_method": 'SCREEN', "use_fast_gi": True,
              "fast_gi_method": 'GLOBAL_ILLUMINATION', "fast_gi_quality": 1.0, "fast_gi_step_count": 16,
              "fast_gi_ray_count": 4, "fast_gi_resolution": '1',
              # soft shadows in the viewport too: without jitter the shadow map's texels show as steps
              # on curved parts (run 201)
              "use_shadow_jitter_viewport": True,
              "taa_samples": 128, "taa_render_samples": 256}   # viewport 128, render 256 (user, 2026-10-02)
    for k, v in wanted.items():
        if hasattr(e, k):
            try:
                setattr(e, k, v)
            except (TypeError, ValueError):
                pass
    opts = getattr(e, "ray_tracing_options", None)
    if opts is not None:
        # Backface Hit (Blender 5.2+, off in setup files older than the option) and full trace quality: arches
        # and insides darken like in Cycles (run 236: 2.30 -> 2.15 % from Cycles, insides 5.01 -> 4.27 %)
        for k, v in {"resolution_scale": '1', "use_denoise": True, "trace_max_roughness": 1.0,
                     "use_backface_hit": True, "backface_radiance_scale": 0.25, "screen_trace_quality": 1.0}.items():
            if hasattr(opts, k):
                try:
                    setattr(opts, k, v)
                except (TypeError, ValueError):
                    pass
    sky = camera.sky_world()
    if sky is not None and hasattr(sky, "probe_resolution"):
        try:
            sky.probe_resolution = '2048'
        except (TypeError, ValueError):
            pass


def set_engine(scene, name):
    """Switch the render engine ('CYCLES' or 'EEVEE') with the matching lighting. Returns a short note."""
    if name == 'EEVEE':
        scene.render.engine = eevee_id()
        eevee_best(scene)
    else:
        scene.render.engine = 'CYCLES'
    sync(scene)
    note = camera.apply_sky(scene, scene.get("rb_camera_view", "FRONT"))   # Bottom: the panorama follows
    sync(scene)
    return note


_LAST = {}


def watch_key(scene):
    """What the lamp depends on, for the depsgraph handler (direct edits of the Sky node, the engine
    switched elsewhere)."""
    sky = camera.sky_world()
    if sky is None or not camera.render_camera_is_on(scene):
        return None
    main = camera._main_sky(sky)
    if main is None:
        return None
    return (scene.render.engine, round(main.sun_elevation, 6), round(main.sun_rotation, 6),
            round(float(getattr(main, "altitude", 0.0)), 3), round(main.sun_size, 7),
            round(_background_strength(sky), 6), bool(scene.world and scene.world.get(camera.BELOW_TAG)),
            bool(sky.get(camera.SUN_PICTURE)), round(camera.world_unit(scene), 9))


def on_depsgraph(scene, _depsgraph=None):
    key = watch_key(scene)
    if key is None or _LAST.get(scene.name) == key:
        return
    _LAST[scene.name] = key
    camera.follow_scale(scene)                      # the parts scaled (Mecabricks panel): the camera follows
    sync(scene)
    _LAST[scene.name] = watch_key(scene)
