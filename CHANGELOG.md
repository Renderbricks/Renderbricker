# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/): PATCH for fixes, MINOR for new features, MAJOR for
changes that break existing scenes or settings. Only changes to the add-on itself are listed;
documentation changes are not.

## [Unreleased]

- **Textures stay where they belong:** textures that follow the parts' UV maps – mould lines, the grainy slope texture, prints and logos – lie on the smoothed part where they lie on the import. The smoothing used to slide the faces along the part, and the texture slid with them: the mould line of the curved bar 7052 ended lower and with a changed corner, the grain of slope 3044 streaked along the rounded edge. Now the points slide back along the smooth surface to their import place; the shape stays the same. Also gone: a dent in EEVEE where two drawn lines meet (7052 at level 3). Both reported by the maintainer. Already converted scenes are converted again on the next **Apply**.
- **Remove clears the whole file** with the scope *All*: the parts in every scene go back to the import, and copies of parts deleted in the meantime no longer stay in the file and no longer keep the cache file linked. The summary names how many copies were deleted and, with *Selected* or *Collections*, how many stay outside the scope.
- **Render camera in ACES 2.0:** in Blender 5.x switching the render camera on sets the view ACES 2.0 with the reference gamut compression (Blender 4.5 keeps AgX), and the sun strength starts on 0.06 instead of 0.03 – ACES 2.0 renders darker (a value set by you stays). The summary notes when the file's working colour space is not ACEScg. Switching off brings back your view and look exactly – a look of your own (e.g. AgX Punchy) was lost before.
- **Folds at tiny faces:** a fold that only showed in the finished smoothed copy is now repaired too (one part in more than 1,300).

## [1.2.2] – 2026-10-04

- **EEVEE** on renders the 3D views with EEVEE (*Rendered*, the scene's own settings – the same as F12) instead of Material Preview.
- **EEVEE samples:** switching EEVEE on sets 128 samples for the viewport and 256 for rendering.
- **Curves on flat faces:** where a rounding meets a flat face in a coarse curve, the edge now follows the curve instead of staying a polyline with kinks – e.g. the curved slopes 29119 / 29120, whose curve met the 45° face and the flat side with corners (reported by a user). Designed kinks stay sharp.

## [1.2.0] – 2026-10-01

- **Cycles | EEVEE** right under the render camera button: two switches, both off at the start. **Cycles** on: the 3D views render with Cycles (Rendered) and F12 renders with Cycles – the physical sky with its sun disc lights the model. **EEVEE** on: the 3D views show EEVEE (Material Preview with the Renderbricks sky and its lamp) and F12 renders with EEVEE. Pressed again, the views go back to the shading they had. EEVEE takes the sky's sun only very weakly, so there the sky lights without its disc and a sun lamp "Renderbricks Sun" stands in for the sun: linked to the sun sliders (direction, over the top, "Sun turns with the camera", the mirrored sky of Bottom, direct edits of the Sky node), with the strength and colour the sun has in Cycles at that elevation and altitude – the model is as bright in EEVEE as in Cycles (before: about 60 %). EEVEE is set to everything it can do: ray tracing and global illumination at full resolution, soft shadows with the most rays and steps (in the viewport too), a sharp world probe.
- **Models at real size** (import scale 0.001, as the reworked Mecabricks importers use): EEVEE's shadow and ray-tracing sizes follow the scale of the parts, so shadows stay sharp instead of blotchy; when the scale is changed in the Mecabricks panel, the render camera moves with the model and the picture stays as it was.
- **Blender 4.5:** Cycles crashed when rendering with the Renderbricks sky, whose sky type (Multiple Scattering, Blender 5.x) 4.5 does not know – such a sky now becomes Nishita.

## [1.1.0] – 2026-09-30

- **Import from Mecabricks** at the top of the panel (and in step 1 of the Start Guide) – the same as File > Import > Mecabricks (.zmbx). Greyed out, with a note and a link to www.mecabricks.com, while neither Mecabricks Lite nor Advanced is enabled.
- **Sun sliders** in the render camera: Elevation (−15° to 195°, over the top to the other side), Rotation (0° to 360°), Altitude (0 to 100,000 m) and Strength of the sky (0.01 to 0.1), each with step arrows and a button back to the standard. Typed values stay as they are. With the view Bottom the mirrored sky follows a moment after the last change.
- **Sun in picture: on/off** below the sun sliders (default off): the sun disc lights the model as before – highlights, sharp shadows and reflections – but is not seen in the picture (Cycles; EEVEE never shows it).
- **New standard sky:** Strength 0.03 instead of 0.2.
- **Tidy world nodes:** the nodes of the Renderbricks sky (and of the mirrored sky of Bottom) are laid out in columns along the signal, without overlaps. A world with nodes of your own is left as it is.

## [1.0.1] – 2026-09-30

- No functional changes – the add-on's code is split into modules by task (panel, operators, Start Guide; the core as its own package), so it is easier to read and to extend.

## [1.0.0] – 2026-09-29

- **Smooth parts for rendering:** Apply sets creases on the parts of a Mecabricks import by a tested rule set – sharp where the real part is sharp, round where it is round – and bakes the subdivided result into one copy per part, shared by all its links. The imported meshes stay unchanged; Remove goes back to them.
- **Viewport and render level** separately; F12 and Ctrl+F12 render with the render level.
- **Scope:** All, Selected or chosen collections with their child collections.
- **Several Blender processes** convert large scenes in parallel, as many as the processor and the free memory allow; **Low Memory** (Auto, Off, On) for very large parts or computers with little memory.
- **Convert headless** converts the whole scene in a terminal and writes a new file; the open scene is not changed.
- **Cache file** next to the scene keeps the scene file small; Move or Copy the cache after Save As.
- **Check** finds folded faces and open seams; **Subdivision ON/OFF** compares with the import.
- **Render camera:** a camera, a sky and render settings of their own, six views each into its own render slot, All views, sun fixed or turning, Transparent, Resolution Scale and sample presets – your own camera, world and settings come back when it is switched off.
- **Start Guide** leads through the workflow inside Blender; optional **log file** next to the scene.
- Blender 4.5 LTS or newer on Windows, Linux and macOS.
