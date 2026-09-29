# Troubleshooting

**"Save the scene first".** Several Blender processes, the cache file and *Convert headless* work with the
scene file on disk. Save the scene (Ctrl+S) and press the button again.

**"Cache missing: …" – the objects show their original meshes.** The cache file was moved,
renamed or deleted. Put it back next to the scene under `<scene>_rbcache.blend`: when the scene is
opened, the add-on finds it and links it again (save the scene afterwards). Or press **Apply** to
build a new cache.

**"Cache of another scene: …".** You saved the scene under another name or in another folder,
and it still links the cache of the old file. Press **Move cache here** (one scene, one cache) or
**Copy cache here** (both scene files keep a cache).

**"Stopped: … memory" or "SKIPPED for memory".** Blender ran short of memory. The parts converted so
far keep their copies. Close other programs and press **Apply** again, or convert the scene in
portions with *Selected*. *Convert headless* is an alternative for very large scenes.

**Convert headless: "RETIRE worker short of memory …".** One of the background Blenders ran short of memory and
stopped; its remaining parts are converted at the end by the main process, the result is complete.
The conversion only takes longer. Closing other programs – or the scene in Blender – leaves more
memory for the next run.

**"Errors in N meshes – left as imported".** These parts could not be converted and keep the
original mesh. Please report them with the part number (the mesh name, e.g. `3001.002`) in the
[issues](https://github.com/Renderbricks/Renderbricker/issues).

**Check lists problems.** Click the arrow next to an entry to select and frame the object. Folds
can come from faces that are already broken in the import; at render size they are usually not
visible – render a close-up before you worry. See [Known issues](KNOWN_ISSUES.md).

**The render shows the viewport level.** Render with **F12 / Ctrl+F12** or the *Render* menu
entries *(Renderbricker levels)*. If you changed the F12 key in your keymap, use the menu entries.

**The panel stays greyed out after a crash.** A progress state was left behind. Open the scene
again – the panel unlocks when a file is loaded.

**Convert headless: no terminal opens (Linux).** None of the known terminals was found. The panel
names the start script; run it in a terminal of your choice: `sh <scene>_subdiv_<version>.sh`.

**The viewport is slow.** Set the viewport level to 1 or 0; the render level stays as it is.

**The scene file is large.** Switch on *Cache file next to the scene* – the copies then live in
the cache file.
