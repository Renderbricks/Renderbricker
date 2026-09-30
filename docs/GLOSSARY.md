# Glossary

**Part mesh / link.** Mecabricks imports every element type once as a mesh (e.g. `3001.002`, a
2×4 brick); each brick in the scene is an object that links this mesh. A scene may link one mesh
hundreds of times.

**Subdivision.** Blender's subdivision surface (Catmull-Clark, OpenSubdiv): every face is split
and the surface smoothed. Each level multiplies the faces by three to four (a triangle becomes three
faces, a quad four).

**Crease.** A weight on an edge (0–1) that keeps the subdivision from rounding it. Creases are
what makes a smoothed brick keep its sharp edges. Renderbricker sets them by rules
([RULES.md](RULES.md)).

**Copy (`<mesh> L1`, `<mesh> L2`).** The subdivided result for one level, baked into a mesh of its
own. All links of a part use the same copy; the imported mesh stays in the file, unchanged.

**Cache file (`<scene>_rbcache.blend`).** A second file next to the scene that holds the copies.
The scene links them as *library overrides*, so its own file stays small.

**Custom normals.** The shading directions Mecabricks stores in the import. Variant A carries them
into the subdivided copy, so the parts shade as Mecabricks made them.

**Headless.** Blender without a window, started from a terminal – used by *Convert headless* and
by the background Blenders of *Use several Blender processes*.

**Renderbricks Sky / Renderbricks Sun.** The world of the render camera: Blender's physical sky (Sky Texture) with a sun at a height and direction set by the sun sliders. Cycles is lit by the sky and its sun disc; EEVEE takes that sun only very weakly, so with EEVEE a sun lamp *Renderbricks Sun* follows the sky, with the strength and colour the sun has in Cycles.

**Import scale 0.001.** Mecabricks parts at their real size in Blender's metric units (a 2×4 brick 3.2 cm long). The reworked Mecabricks importers use it by default; scale 1 makes one millimetre one unit.
