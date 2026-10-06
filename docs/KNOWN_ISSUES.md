<div align="justify">

# Known issues

## Folds at faces that are broken in the import

A few Mecabricks parts contain faces that are already folded or crossed in the imported mesh. The
sub­di­vided copy follows the import there, and **Check** lists a small number of folded faces. In
18 test scenes this con­cerned two parts (23985 in *Destiny's Bounty*, 93221 in *The LEGO NINJAGO
Movie*); at render size the spots were not visible. The rules never change the imported mesh, so
these faults are kept rather than repaired.

## Blender versions

- **Blender 4.2 cannot open scenes saved in Blender 5.x.** The add-on there­fore needs Blender 4.5
  LTS or newer; 4.5 opens files saved in 5.x.
- **Files saved in Blender 5.3 do not open in Blender 5.2.** Convert with the Blender version you
  work in – with the cache on, both the scene and its cache file are written by that version.

## Variant B and the Mecabricks shading

Variant B (geo­met­ric normals) gives crisper logos but does not keep the custom normals of the
import, so the shading of some sur­faces differs from Mecabricks. Variant A keeps it and is the
default.

## EEVEE: glass and insides

EEVEE refracts only what is already in the picture. Behind a window pane the room is hidden by the pane itself, so EEVEE shows the sky there and the glass looks milky, where Cycles shows the dark room behind it. For the same reason EEVEE lights the insides of arches and rooms brighter than Cycles. Real trans­parency, thicker panes or a reflec­tion probe did not change this in tests; for pic­tures with glass in front, use Cycles.

</div>
