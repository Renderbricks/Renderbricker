# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/): PATCH for fixes, MINOR for new features, MAJOR for
changes that break existing scenes or settings. Only changes to the add-on itself are listed;
documentation changes are not.

## [1.0.0] – unreleased

First release – in preparation; improvements are added here until it is published.

- Rule-based creases for Mecabricks imports: seams welded in a temporary copy, hard edges, bevels, designed corners and hexagon sockets kept sharp, round shapes and polygonised circles smoothed; the imported meshes stay unchanged.
- One subdivided copy per part, shared by all its links; separate viewport and render levels, F12 / Ctrl+F12 render with the render level.
- Optional cache file next to the scene (copies linked as library overrides), with Move/Copy cache after Save As and switching the cache on and off.
- Apply and headless conversion on several cores; progress bars for all long steps; the scene is saved after the cache was written.
- Start Guide: a step-by-step guide through the workflow (save, choose the parts, settings, Apply, Check, compare, render, what next), every step explained in bullet points, with its own controls and a status line; the next action is highlighted.
- Raising a subdivision level above 2 asks first (Cancel keeps the old level) and the panel shows a warning while it is above 2.
- Convert headless on a scene that was already converted no longer stands still: the previous conversion is left out of the working copy (Italian Riviera: 1 GB instead of 3.9 GB per background Blender), and a background Blender short of memory stops and hands its remaining parts back instead of waiting for the others; the terminal says so.
- Render camera ON/OFF: ON makes the camera "Renderbricks" (framing all visible parts to fill the picture) and a world "Renderbricks Sky" (Physical Sky) of its own active and takes over the Renderbricks render settings; OFF brings back the scene's own camera, world and render settings, so a scene set up before is never overwritten. The camera button frames the model again; six view buttons (Front, Right, Back, Left, Top, Bottom) turn the camera around the model in 90° steps or look straight from above and below (square to the model, longer side across), framed each time; the 3D viewport looks through the camera while it is on.
- Apply skips parts that are already converted with the same settings and rules, so adding parts to a converted scene converts only the new ones; Shift+click converts all again.
- Option Log file: the results of Apply, Check and Convert headless are appended to `<scene>_renderbricker.log` next to the scene, with date, settings and the full problem list.
- The results in the panel are listed as compact bullet points.
- Scope All, Selected or Collection (a chosen collection with its child collections) for Apply, Check, On/Off, levels and Remove.
- "Subdivision: ON / OFF" switches all links between copy and original and shows the current state.
- Checks after every conversion: original untouched, folds, seam gaps.
- Windows, Linux and macOS: the headless conversion writes a start script for the platform (.bat, .sh, .command) and opens it in a terminal; the number of parallel jobs follows the free memory on all three.
- Variant B works in Blender 4.5 as well (a node socket is named differently there).
- Blender 4.5 LTS or newer; tested on 18 scenes (up to 71,000 objects) in Blender 5.2 LTS and 5.3, platform tests on Windows, Linux and macOS with 4.5 and 5.2.
