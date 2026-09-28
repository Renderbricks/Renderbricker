# Known issues

## Folds at faces that are broken in the import

A few Mecabricks parts contain faces that are already folded or crossed in the imported mesh. The
subdivided copy follows the import there, and **Check** lists a small number of folded faces. In
18 test scenes this concerned two parts (23985 in *Destiny's Bounty*, 93221 in *The LEGO NINJAGO
Movie*); at render size the spots were not visible. The rules never change the imported mesh, so
these faults are kept rather than repaired.

## Blender versions

- **Blender 4.2 cannot open scenes saved in Blender 5.x.** The add-on therefore needs Blender 4.5
  LTS or newer; 4.5 opens files saved in 5.x.
- **Files saved in Blender 5.3 do not open in Blender 5.2.** Convert with the Blender version you
  work in – with the cache on, both the scene and its cache file are written by that version.

## Variant B and the Mecabricks shading

Variant B (geometric normals) gives crisper logos but does not keep the custom normals of the
import, so the shading of some surfaces differs from Mecabricks. Variant A keeps it and is the
default.
