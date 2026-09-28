# Reference – all settings

The panel is in the 3D Viewport sidebar (press N), tab **Renderbricker**. Its header shows the
add-on version. Defaults in brackets. The
tooltips in Blender say the same in short.

## Settings

| Setting | Default | What it does |
|---|---|---|
| **All / Selected / Collection** | All | Which mesh objects Apply, Check, On/Off, Levels and Remove work on: every mesh object in the scene, the selected ones, or the ones in a chosen collection and its child collections (the field below *Collection*; when it is empty, the collection active in the Outliner is taken). Only the links in scope switch to the copy; other links of the same part keep the original until they are converted too. *Convert headless* always converts the whole scene. |
| **Variant** | A – Mecabricks normals | **A:** the subdivision interpolates the custom normals of the import – the shading stays as Mecabricks made it, logos on studs look soft. **B – geometric normals:** normals of the smoothed surface, creased edges sharp – crisper logos, but the shading of the import is not kept. |
| **Viewport** level | 1 | Subdivision shown in the viewport. 0 shows the original mesh (no viewport copy is stored – the file gets about a fifth smaller). Levels already baked switch at once, others are computed the first time (with a progress bar). |
| **Render** level | 2 | Subdivision used for rendering; the checks use this level. |
| **Use several cores** | on | Apply on larger scenes (about 40 meshes and more) runs in background Blenders on several cores and loads the result into this scene. The scene is saved first. The number of Blenders follows the free memory. |
| **Cache file next to the scene** | on | The subdivided copies are kept in `<scene>_rbcache.blend` next to the scene and linked into it, so the scene file stays about as large as the import. Needs a saved scene. Switching it off takes the copies back into the scene file; switching it on writes them out again. |

## Buttons

| Button | What it does |
|---|---|
| **Apply** | Sets the creases of each part mesh once and bakes the subdivision into a copy of it (`<mesh> L<level>`) that all its links use. The original mesh stays in the file, unchanged. With the cache on, the copies are written into the cache file and the scene is saved. Esc cancels; the parts converted so far keep their copies. |
| **Check** | Looks for folded faces and seam gaps in the render copies and lists the objects with problems; the arrow button next to an entry selects and frames that object. |
| **Subdivision: ON / OFF** | Switches every link between the subdivided copy and the original mesh (viewport and render). The button shows the state: *ON* (pressed), *OFF*, or *partly on* when objects differ. |
| **Remove** | Points the links back to the original meshes and removes the copies – the scene is the plain import again. |
| **Convert headless** | Saves the scene, writes a start script next to it (`.bat` on Windows, `.command` on macOS, `.sh` on Linux) and runs it in a terminal. Blender converts the whole scene in the background on several cores and saves the result as `<scene>_subdiv_<version>.blend` – the open scene is not changed. If no terminal is found (Linux), the panel names the script to start by hand. |
| **Move cache here / Copy cache here** | Shown when the scene was saved under another name or in another folder and still links the cache of the old scene file. *Move* renames the cache to belong to this scene (the old scene file then shows its original meshes); *Copy* gives this scene a cache of its own. |

## Rendering

**F12** and **Ctrl+F12** render with the render level: the links are switched to the render copies
before the render starts and back to the viewport level afterwards. The same is in the *Render*
menu as *Render Image / Render Animation (Renderbricker levels)*. Renders started from the command
line (`blender -b … -f`) switch the level as well.

## Files

| File | What it is |
|---|---|
| `<scene>.blend` | Your scene; with the cache on it links the copies and stays small. |
| `<scene>_rbcache.blend` | The subdivided copies. Keep it next to the scene; when you move or rename the scene, move or rename the cache with it, or use *Move cache here* after *Save As*. |
| `<scene>_subdiv_<version>.blend` | Result of *Convert headless* (plus its own `_rbcache.blend`). Earlier results are never overwritten. |
| `<scene>_subdiv_<version>.bat / .sh / .command` | The start script of *Convert headless*; it can be run again by hand. |

## About

The sub-panel **About** shows the copyright, the trademark notes and links to
[www.renderbricks.com](https://www.renderbricks.com), Facebook, YouTube and this repository.
