# Changelog

All notable changes to this project are documented here. The project follows
[Semantic Versioning](https://semver.org/): PATCH for fixes, MINOR for new features, MAJOR for
changes that break existing scenes or settings. Only changes to the add-on itself are listed;
documentation changes are not.

## [1.0.0] – 2026-09-29

First release.

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
