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
- Scope All, Selected or Collection (a chosen collection with its child collections) for Apply, Check, On/Off, levels and Remove.
- "Subdivision: ON / OFF" switches all links between copy and original and shows the current state.
- Checks after every conversion: original untouched, folds, seam gaps.
- Windows, Linux and macOS: the headless conversion writes a start script for the platform (.bat, .sh, .command) and opens it in a terminal; the number of parallel jobs follows the free memory on all three.
- Blender 4.5 LTS or newer; tested on 18 scenes (up to 71,000 objects) in Blender 5.2 LTS and 5.3, platform tests on Windows, Linux and macOS with 4.5 and 5.2.
