"""Calibration of the EEVEE sun lamp against the Renderbricks sky (user 2026-09-30, UPDATES #7).

Usage: blender -b --factory-startup --python scripts/core/calibrate_sun_lamp.py -- <table.json>

EEVEE reads the world from a probe in which the 0.5 deg sun disc of the Sky Texture loses most of its
energy, so in EEVEE the sky lights without its disc and a Sun lamp stands in for it. This script
measures in Cycles what that lamp has to give: a white diffuse plane seen from above, lit by the sky
with the sun disc and by the same sky without it; the difference is the sun's irradiance. A lamp of
strength 1 at elevation e gives sin(e) / pi on that plane, so

    lamp strength (per colour channel) = (with disc - without disc) / (sin(e) / pi)

per unit Background strength (the sun scales linearly with it). Grid: sun elevation x altitude, the
Renderbricks sky (sun size 0.00951, densities 1, sun intensity 1). The sky type is the one this
Blender makes (Multiple Scattering from 5.0, Nishita in 4.5); the table keeps one entry per type, so
run it once with each: the file is merged, not replaced.
"""
import bpy, sys, os, json, math
import numpy as np

out = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progress import Progress

ELEVATIONS = [1, 2, 3, 4, 5, 7.5, 10, 12.5, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90]
ALTITUDES = [0, 1000, 2000, 3000, 5000, 7500, 10000, 20000, 40000, 70000, 100000]

scene = bpy.context.scene
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.active_object
mat = bpy.data.materials.new("white")
mat.use_nodes = True
nodes = mat.node_tree.nodes
nodes.clear()
diffuse = nodes.new('ShaderNodeBsdfDiffuse')
diffuse.inputs[0].default_value = (1, 1, 1, 1)
output = nodes.new('ShaderNodeOutputMaterial')
mat.node_tree.links.new(diffuse.outputs[0], output.inputs[0])
plane.data.materials.append(mat)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 0.5
cam.location = (0, 0, 1)
scene.camera = cam
r = scene.render
r.engine = 'CYCLES'
r.resolution_x = r.resolution_y = 16
scene.cycles.device = 'CPU'
scene.cycles.samples = 256
scene.cycles.use_denoising = False
scene.view_settings.view_transform = 'Standard'
r.image_settings.file_format = 'OPEN_EXR'
world = bpy.data.worlds.new("sky")
scene.world = world
world.use_nodes = True
sky = world.node_tree.nodes.new('ShaderNodeTexSky')
try:
    sky.sky_type = 'MULTIPLE_SCATTERING'
except TypeError:
    sky.sky_type = 'NISHITA'
sky.sun_size = 0.00951
world.node_tree.links.new(sky.outputs[0], world.node_tree.nodes['Background'].inputs[0])
world.node_tree.nodes['Background'].inputs[1].default_value = 1.0
path = os.path.join(bpy.app.tempdir, "cal.exr")


def level():
    bpy.ops.render.render()
    bpy.data.images['Render Result'].save_render(path)
    im = bpy.data.images.load(path)
    px = np.array(im.pixels[:], dtype=np.float64).reshape(-1, 4)[:, :3].mean(axis=0)
    bpy.data.images.remove(im)
    return px


progress = Progress(f"sun lamp calibration {sky.sky_type}")
progress.set_stage(1, "renders", total=len(ELEVATIONS) * len(ALTITUDES))
rows = []
for alt in ALTITUDES:
    sky.altitude = alt
    row = []
    for elev in ELEVATIONS:
        sky.sun_elevation = math.radians(elev)
        sky.sun_disc = True
        a = level()
        sky.sun_disc = False
        b = level()
        lamp = math.sin(math.radians(elev)) / math.pi
        row.append([round(float(v), 5) for v in np.maximum(a - b, 0) / lamp])
        progress.tick()
    rows.append(row)
    print("CAL altitude", alt, "strength at 30 deg", row[ELEVATIONS.index(30)])

table = json.load(open(out, encoding="utf-8")) if os.path.isfile(out) else {}
table[sky.sky_type] = {"elevations": ELEVATIONS, "altitudes": ALTITUDES, "rgb": rows,
                       "sun_size": 0.00951, "note": "lamp strength per unit Background strength, rows = altitudes",
                       "blender": bpy.app.version_string}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(table, fh, indent=1)
progress.finish()
print("CAL written", out, sky.sky_type)
