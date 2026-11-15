# SPDX-License-Identifier: GPL-3.0-or-later
"""Names, tables and markers of the physical network shared by its modules.

Part of Physicalbricks (see __init__.py)."""
import os

import bpy

AVAILABLE = bpy.app.version >= (5, 0, 0)

TYPES = ('solid', 'transparent', 'rubber', 'milky', 'opal', 'speckle', 'glitter')

# classes on a glass core: volume, transmittance numbers, single colour only
GLASS = ('transparent', 'milky', 'opal', 'glitter')

# opal platelets: group input -> record field of record['iridescence']
IRIDESCENCE_INPUTS = {'Iridescence Size': 'size_mm', 'Iridescence Density': 'density', 'Film Thickness': 'film_nm',
                      'Film IOR': 'film_ior', 'Iridescence Tilt': 'tilt_deg'}

# glitter foil flakes: group input -> record field of record['flakes']
FLAKE_INPUTS = {'Flake Size': 'size_mm', 'Flake Density': 'density_mm3', 'Flake Depth': 'depth_mm',
                'Flake Tilt': 'tilt_deg', 'Flake Roughness': 'roughness', 'Flake Foil': 'foil',
                'Fine Fraction': 'fine_fraction'}

# values a record from before may lack - the add-on's former behaviour
FLAKE_DEFAULTS = {'foil': 0.9, 'fine_fraction': 0.0}

# speckle particles: group input -> record field of record['particles'] (the colour separately, ACEScg). Three fleck
# layers since group version 17 (UPDATES #84): large, medium at its own strength, small; a soft fleck edge. No tilt
# since group version 37 (every record had tilt_deg 0; the field stays in the records for Maya's reader)
PARTICLE_INPUTS = {'Particle Metallic': 'metallic', 'Particle Roughness': 'roughness',
                   'Fleck Size Large': 'size_large_mm', 'Fleck Fraction Large': 'fraction_large',
                   'Fleck Size Medium': 'size_medium_mm', 'Fleck Fraction Medium': 'fraction_medium',
                   'Fleck Strength Medium': 'strength_medium',
                   'Fleck Size Small': 'size_small_mm', 'Fleck Fraction Small': 'fraction_small',
                   'Fleck Edge Softness': 'edge_soft'}

# values a record from before may lack (it described one or two fleck sizes): the accepted speckle, variant ZB95
PARTICLE_DEFAULTS = {'size_large_mm': 0.40375, 'fraction_large': 0.39,
                     'size_medium_mm': 0.247, 'fraction_medium': 0.468, 'strength_medium': 0.75,
                     'size_small_mm': 0.13775, 'fraction_small': 0.33, 'edge_soft': 0.25}

CLASS_GROUPS = {'solid': 'rb_phys_solid', 'transparent': 'rb_phys_transparent', 'rubber': 'rb_phys_rubber',
                'milky': 'rb_phys_transparent', 'opal': 'rb_phys_opal', 'speckle': 'rb_phys_speckle',
                'glitter': 'rb_phys_glitter',
                'pearlescent': 'rb_phys_pearl', 'metal': 'rb_phys_pearl', 'chrome': 'rb_phys_chrome'}

# group input <- record 'effect' key; colours through network.effect_value (metal_rgb / metal_f82_rgb Rec.709,
# *_acescg ACEScg). Metal Edge Tint (group version 37): the chrome's F82 tint of measured aluminium
EFFECT_INPUTS = {'Metallic': 'metallic', 'Base Roughness': 'base_roughness', 'Flake Size': 'flake_mm',
                 'Flake Tilt': 'flake_tilt_deg', 'Flake Roughness': 'flake_roughness', 'Thin Film': 'thin_film_nm',
                 'Thin Film IOR': 'thin_film_ior', 'Coat IOR': 'coat_ior', 'Metal Roughness': 'base_roughness',
                 'Metal Color': 'metal_rgb', 'Metal Edge Tint': 'metal_f82_rgb', 'Specular Tint': 'specular_tint_acescg'}

# version of the class groups in physical.blend (scripts/build_physical_blend.py writes the same); a file holding older
# groups gets them replaced. 13: glitter foil and fine fraction; 14: glitter in Eevee; 15: opal and speckle in Eevee;
# 16: speckle evenly spread with one fleck size (UPDATES #75); 17: speckle in three fleck sizes with a soft edge (#84);
# 18: fluorescence follows the light - a gain of the scattering in glass, one Volume Coefficients node (#85);
# 19: the glow amplifies only light not yet scattered in a volume, so it does not run away in thick parts (#85);
# 20: the surface of new parts - rb_phys_surface with unevenness, micro surface and stud variation (UPDATES #91);
# 21: micro-scratches as a third layer, procedural - rb_phys_micro_scratches, rb_phys_scratch_family (#91, #94);
# 22: smudges - roughness with contrast (clouds, wipe marks, fingerprints), procedural - rb_phys_smudges (#94);
# 23: micro surface and unevenness with a density (the size of their features) beside the intensity (#94);
# 24: fingerprints as a layer of their own (rb_phys_fingerprints), scratches - the sparse deeper ones
#     (rb_phys_scratches, rb_phys_cut_family) (#94);
# 25: dents, vertical stripes, edge wear - rb_phys_dents, rb_phys_stripes, rb_phys_edge_wear (#94);
# 26: grease - rb_phys_grease, the surface's output Grease, the solid group's input Grease (a rough coat) (#94);
# 27: the print as a stamp - rb_phys_decoration reads Ink Relief and Ink Grain from the surface settings (#92);
# 28: edge wear on the edge with a soft overflow (input Spread); the decoration's output Alpha (the print with its
#     wear), the bead along its outline (#92, #94);
# 29: the decoration's input Soft Alpha (soft_alpha.py) - a bevelled, visible ink film; one value Ink Wear (#92);
# 30: a seed of its own per layer beside the seed for all; Ink Rim Wear (#94, #92);
# 31: fingerprints only where a finger gets - open (ambient occlusion) and flat (Bevel normal) places (#94);
# 32: fluorescence redistributes what the dye takes (efficiency 0.8) instead of a gain of 4 - no energy out of
#     nothing, nothing in the dark (B2 of the debriefing of 27.10.2026, run 118);
# 33: no per-cell flake normals in rb_phys_pearl (pearl and metal) - the platelets' spread is the pigment roughness;
#     a 0.03 mm cell was one pixel at farm resolution and showed as dark grain (user 31.10.2026, run 142);
# 34: rb_phys_pearl's input Specular Tint (white by default) on the pigment's Specular Tint - a coloured highlight
#     beside an unchanged body colour (176 / 178 Flip-Flop, user 02.11.2026, run 142);
# 35: rb_phys_speckle_glitter - a speckle record with the glitter's flakes (132, 287-291 „with Glitter“): the opaque core
#     with the foil flakes of the glitter materials instead of speckle flecks (user 02.11.2026, run 142);
# 36: the same group as rb_phys_glitter_opaque - the colours „with Glitter“ are glitter records with an opaque body
#     (materials version 8, user 02.11.2026: „Die Sondermaterialien Glitter aus opakem Material gehören doch nicht nach
#     Speckle?“)
# 37: shader audit (run 144, spec 2026-11-03) - rb_phys_transparent rebuilt (Vector Math, frame notes with sources,
#     the unused refracting Eevee glass and output 'Eevee' removed) and input Abbe Number for the dispersion of Blender
#     5.3+ (groups.wire_dispersion, Clamp Indirect >= MIN_CLAMP_INDIRECT)
# 38: the settings group's value Yellowing - the panel's slider blends a record's transmittance towards its yellowing
#     end (20 Nature, materials version 16; user 06.11.2026: „Das Material braucht einen Regler für den
#     Vergilbungseffekt.“)
# 39: rb_phys_solid inputs SSS Radius and SSS Own Radius - a record's own scatter radius per channel (358 Translucent
#     White, materials version 17; user 06.11.2026: „Muss eben einen eigen Streuradius bekommen.“)
# 40: the class groups compute their Eevee data themselves - no nested mb_base_* / mb_sss_radius from the Mecabricks
#     node library (library part 2, run 148; user 08.11.2026: „wir wollen uns komplett lösen“)
# 41: rb_phys_pearl's flakes back - one tilted platelet per 0.03 mm cell (rb_phys_flake_normal), the record's tilt 9 deg
#     in every pearl and metal record (materials version 23; run 151, user 08.11.2026: „9° passt.“); rb_phys_eevee's own
#     refraction glass fitted to Cycles, refraction at rest (run 148, user 08.11.2026: „Der EEVEE Branch für
#     Physicalbricks muss komplett unabhängig sein.“ - „Sieht gut aus.“)
# 42: direct links, the order – no reroutes, one Group Input per input in its consumer's column, frames in level stacks
#     (library part 4c)
PHYS_VERSION = 42

# Eevee refracts a LEGO part as a shell: the wall, in the part's space (mm), at the Eevee output's Thickness of glass -
# 4 LDU, the wall of an LDraw brick (run 148)
EEVEE_WALL_MM = 1.6

# Release 1 brings the materials clean (user 04.11.2026: "Im ersten Release werden wir noch keine Effekte haben. Die
# kommen erst später."): the panel offers no surface layer (micro surface, unevenness, stripes, the wear) and no ink
# wear, only the clean print. The layers' machinery stays whole and tested; True shows them in the panel again. At the
# defaults every layer is 0, so the network carries no surface node either way.
EFFECTS = False

# a glitter record with body "opaque" (network.render_kind 'glitter_opaque', network.class_group): the glitter's flakes
# on the opaque core, no glass; loaded with the class groups
GLITTER_OPAQUE = 'rb_phys_glitter_opaque'

# the library's own Eevee shader (group version 40; run 148 tuned its thin glass to Cycles)
EEVEE_GROUP = 'rb_phys_eevee'
EEVEE_GROUPS = (EEVEE_GROUP,)

# the physical groups and their ID properties: rb_ (Renderbricks) - our own groups, not Mecabricks'; until group
# version 37 they were mb_phys_* (user 03.11.2026: „Wenn dann rb_“), renamed when a file opens
# (groups.rename_old_prefix)
PREFIX = 'rb_phys_'
OLD_PREFIX = 'mb_phys_'

MARK = 'mb_base_type'       # on a swapped node: the type it came from

LIBRARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'physical.blend')

SAVED = 'rb_phys_saved'      # on a node: links and values the other tree has no socket for, kept for the way back

# --------------------------------------------------------------------------------------------------------------------
# Architecture v2: the physical network beside the Mecabricks tree
# --------------------------------------------------------------------------------------------------------------------
NET = 'rb_phys_net'          # on every node of the physical network

REFRACTION = 'rb_phys_refraction'   # on a glass material in Physical: its raytrace-refraction flag before (restored)

RT_BEFORE = 'rb_phys_raytracing_before'   # on the scene until 2.1.17.64: its Eevee raytracing before; dropped on load

VIEWPORT = 'rb_phys_viewport'      # on a material in Physical: its viewport (Solid) colour before (restored)

BOUNCES_BEFORE = 'rb_phys_bounces_before'   # on the scene in Physical: its Cycles bounce limits before (restored)

BOUNCES = ('max_bounces', 'diffuse_bounces', 'glossy_bounces', 'transmission_bounces', 'volume_bounces',
           'transparent_max_bounces')

MIN_BOUNCES = 32                     # glass: internal reflections and the haze of the volume need deep paths

CLAMP_BEFORE = 'rb_phys_clamp_before'   # on the scene in Physical: its Cycles Clamp Indirect before (restored)

# on the glass Principled of rb_phys_transparent (group version 37): physical.blend is built with 5.3, whose builder
# links the group input 'Abbe Number' to 'Transmission Dispersion Abbe Number' (5.0-5.2 open the file without those
# sockets); groups.wire_dispersion sets 'Transmission Dispersion Scale' 1 and links where a link is missing
DISPERSION_MARK = 'rb_phys_dispersion'

# Clamp Indirect in Physical at least this (0 = off stays off): a dispersive glass path (Blender 5.3+) carries one
# wavelength with RGB weights far above 1; Blender's default 10 clips them, blue most - clear glass turned yellow,
# ΔE2000 12-16 in highlights (run 144 spike, 03.11.2026); 50, 100, 200 and off gave the same image (ΔE 0.07 to no
# dispersion). 50 is also Christopher 3D's starting value („Blender 5.3 gets dispersion!“, 03.09.2026), who warns that
# off brings fireflies the denoiser smears. The importer's render settings use 50 already (render_settings.json).
MIN_CLAMP_INDIRECT = 50.0

# the title of the network's outer frame; its steps are numbered frames inside it (layout.py), so it carries no
# number. Since part 4c's ruling G3 (task 7g, 12.11.2026) no frame of ours carries a label: the title is the frame's
# text and its ID property layout.TITLE (rb_phys_title); the frame's name stays Blender's (ruling G3a)
FRAME_LABEL = 'Physical network (records, Cycles reference; Eevee follows)'

# the layout of the networks (layout.layout writes it on the outer frame); a file holding a network of another layout
# gets it rebuilt when it opens (switch.upgrade_on_load). 3: part 4c - direct links, the systematic order (spec
# 2026-11-12); 2: part 4b, never released (the Outputs frame in every case with its taps, trace reroutes); missing = 1:
# library part 4
LAYOUT_VERSION = 3
LAYOUT = 'rb_phys_layout'

# the mark part 4b's traces left on a node tree ('<layout>:<major>.<minor>' of the Blender that laid them); files of
# that branch carry it, and network.remove_network deletes it with the network
OLD_TRACES = 'rb_phys_traces'

EEVEE_PARAMS = ('Color', 'Subsurface', 'Metallic', 'Roughness', 'Transmission', 'Height')

PART_BUMP = 'rb_phys_part_bump'   # on a normal tree copied for the network: its relief in mm

SOLID_RW = 'rb_phys_solid_rw'

# the panel's subsurface choice -> Cycles' method (run 108): plain Random Walk refracts its entry around the shading
# normal with the material's roughness and drops every path that then points out of the geometric surface
# (intern/cycles/kernel/integrator/subsurface.h); the custom normals of Mecabricks parts lean 20-25 degrees off
# their small chamfers - dark rings at the knob foot, and the part 5-7 % darker than Burley. Skin enters half
# diffusely, with roughness 1 (closure/bssrdf.h): no rings, the brightness of Burley, the detail of Random Walk.
SUBSURFACE_METHODS = {'BURLEY': 'BURLEY', 'RANDOM_WALK': 'RANDOM_WALK_SKIN'}

OWN_RECORD = 'mb_record'     # on a material: the record of its colour as JSON, for a colour the table does not have

