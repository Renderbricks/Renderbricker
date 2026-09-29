# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/): PATCH for fixes, MINOR for new features, MAJOR for
changes that break existing scenes or settings. Only changes to the add-on itself are listed;
documentation changes are not.

## [1.0.0] – unreleased

First release – in preparation; improvements are added here until it is published.

- Rule-based creases for Mecabricks imports: seams welded in a temporary copy, hard edges, bevels, designed corners and hexagon sockets kept sharp, round shapes and polygonised circles smoothed; the imported meshes stay unchanged.
- One subdivided copy per part, shared by all its links; separate viewport and render levels, F12 / Ctrl+F12 render with the render level.
- Optional cache file next to the scene (copies linked as library overrides), with Move/Copy cache after Save As and switching the cache on and off; the panel shows the cache file on a line of its own and Move/Copy one below the other, readable at the default sidebar width.
- Apply and headless conversion with several Blender processes (as many as the processor and the free memory allow, estimated per scene; each process loads only its own parts, not the whole scene; option Low Memory: Auto, Off or On – On cuts the parts into small segments, each baked by a Blender that ends afterwards and frees its memory, for little memory or very large parts; Auto uses it only when a single part would otherwise leave room for few processes); progress bars for all long steps; the scene is saved after the cache was written.
- Start Guide: a step-by-step guide through the workflow (save, choose the parts, settings, Apply, Check, compare, render, what next), every step explained in bullet points, with its own controls and a status line; the next action is highlighted.
- Raising a subdivision level above 2 asks first (Cancel keeps the old level) and the panel shows a warning while it is above 2.
- Convert headless on a scene that was already converted no longer stands still: the previous conversion is left out of the working copy (Italian Riviera: 1 GB instead of 3.9 GB per background Blender), and a background Blender short of memory stops and hands its remaining parts back instead of waiting for the others; the terminal says so.
- Render camera ON/OFF: ON makes the camera "Renderbricks" (framing all visible parts to fill the picture) and a world "Renderbricks Sky" (Physical Sky) of its own active and takes over the Renderbricks render settings; OFF brings back the scene's own camera, world and render settings, so a scene set up before is never overwritten. The camera button frames the model again; six view buttons (Front, Right, Back, Left, Top, Bottom) turn the camera around the model in 90° steps or look straight from above and below (square to the model, longer side across), framed each time; the picture is landscape 16:9 or, for a model taller than wide, portrait 9:16; the 3D viewport looks through the camera while it is on; sample buttons Low 128, Medium 256, Good 512, High 1024 and a Render button. Every view renders into a slot of its own in the Render window (Slot 1 Front, 2 Right, 3 Back, 4 Left, 5 Top, 6 Bottom, named after the views); All views renders the six one after the other, Esc in the Render window stops the chain. For Bottom the sky is mirrored vertically (rendered once as a panorama), so the sun lights the underside; a sun button keeps the sun fixed (default) or turns it with the camera. ON starts on Low (128 samples) and shows the Output tab of the Properties editor; buttons Transparent (Film Transparent with Transparent Glass) and Resolution Scale. ON again brings back the settings of the last OFF; Shift+click on ON starts fresh.
- Apply skips parts that are already converted with the same settings and rules, so adding parts to a converted scene converts only the new ones; Shift+click converts all again.
- Option Log file: the results of Apply, Check and Convert headless are appended to `<scene>_Renderbricker.log` next to the scene, with date, settings and the full problem list; a button opens it.
- The results in the panel are listed as compact bullet points.
- Scope All, Selected or Collection (a list of collections with their child collections; each can be marked for the render camera, which then shows, renders and frames only the marked ones) for Apply, Check, On/Off, levels and Remove.
- "Subdivision: ON / OFF" switches all links between copy and original and shows the current state.
- Checks after every conversion: original untouched, folds, seam gaps.
- Windows, Linux and macOS: the headless conversion writes a start script for the platform (.bat, .sh, .command) and opens it in a terminal; the number of parallel jobs follows the free memory on all three.
- Variant B works in Blender 4.5 as well (a node socket is named differently there).
- Blender 4.5 LTS or newer; tested on 18 scenes (up to 71,000 objects) in Blender 5.2 LTS and 5.3, platform tests on Windows, Linux and macOS with 4.5 and 5.2.
