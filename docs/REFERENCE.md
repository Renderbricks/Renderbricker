# Reference – all settings

The panel is in the 3D Viewport sidebar (press N), tab **Renderbricker**. Its header shows the
add-on version. Defaults in brackets. The
tooltips in Blender say the same in short.

## Start Guide

**Start Guide** at the top of the panel replaces the panel by a guide through the workflow in eight
steps: save the scene, choose the parts, settings, Apply, Check, compare with the import, render, and
what next. Every step explains its functions in bullet points and shows only its own controls; a
status line says what is still open (red) or done (green, with a tick), the action of the step is
highlighted, and **Next** is highlighted once the step is done. **Back** and the **×** in the step
header work any time.

## Settings

| Setting | Default | What it does |
|---|---|---|
| **All / Selected / Collection** | All | Which mesh objects Apply, Check, On/Off, Levels and Remove work on: every mesh object in the scene, the selected ones, or the ones in a chosen collection and its child collections (the field below *Collection*; when it is empty, the collection active in the Outliner is taken). Only the links in scope switch to the copy; other links of the same part keep the original until they are converted too. *Convert headless* always converts the whole scene. |
| **Variant** | A – Mecabricks normals | **A:** the subdivision interpolates the custom normals of the import – the shading stays as Mecabricks made it, logos on studs look soft. **B – geometric normals:** normals of the smoothed surface, creased edges sharp – crisper logos, but the shading of the import is not kept. |
| **Viewport** level | 1 | Subdivision shown in the viewport. 0 shows the original mesh (no viewport copy is stored – the file gets about a fifth smaller). Levels already baked switch at once, others are computed the first time (with a progress bar). |
| **Render** level | 2 | Subdivision used for rendering; the checks use this level. 2 is enough even for close-ups. Raising a level above 2 asks first – *Cancel* (or Esc) keeps the old level – and the panel shows a warning while it is above 2: every level multiplies the faces by three to four, so memory, file size and conversion time grow a lot for a small visible gain. |
| **Use several cores** | on | Apply on larger scenes (about 40 meshes and more) runs in background Blenders on several cores and loads the result into this scene. The scene is saved first. The number of Blenders follows the free memory. |
| **Log file** | off | Appends the results of Apply, Check and Convert headless to `<scene>_renderbricker.log` next to the scene: date, add-on and Blender version, settings, the summary and the full problem list (the panel shows the first 12 problems). Needs a saved scene. |
| **Cache file next to the scene** | on | The subdivided copies are kept in `<scene>_rbcache.blend` next to the scene and linked into it, so the scene file stays about as large as the import. Needs a saved scene. Switching it off takes the copies back into the scene file; switching it on writes them out again. |

## Buttons

| Button | What it does |
|---|---|
| **Apply** | Sets the creases of each part mesh once and bakes the subdivision into a copy of it (`<mesh> L<level>`) that all its links use. The original mesh stays in the file, unchanged. Parts whose copies already match the settings (levels, variant) and the current rules are skipped – after adding parts to a scene, Apply converts only the new ones. **Shift+click** converts all parts again. With the cache on, the copies are written into the cache file and the scene is saved. Esc cancels; the parts converted so far keep their copies. |
| **Check** | Looks for folded faces and seam gaps in the render copies and lists the objects with problems; the arrow button next to an entry selects and frames that object. |
| **Subdivision: ON / OFF** | Switches every link between the subdivided copy and the original mesh (viewport and render). The button shows the state: *ON* (pressed), *OFF*, or *partly on* when objects differ. |
| **Remove** | Points the links back to the original meshes and removes the copies – the scene is the plain import again. |
| **Convert headless** | Saves the scene, writes a start script next to it (`.bat` on Windows, `.command` on macOS, `.sh` on Linux) and runs it in a terminal. Blender converts the whole scene in the background on several cores and saves the result as `<scene>_subdiv_<version>.blend` – the open scene is not changed. If no terminal is found (Linux), the panel names the script to start by hand. |
| **Move cache here / Copy cache here** | Shown when the scene was saved under another name or in another folder and still links the cache of the old scene file. *Move* renames the cache to belong to this scene (the old scene file then shows its original meshes); *Copy* gives this scene a cache of its own. |

## Render camera

**Render camera: ON / OFF** below the settings switches between your own render setup and the
Renderbricks one – nothing of yours is overwritten:

- **ON** keeps the scene's camera, world and render settings, then makes the camera *Renderbricks*
  and a world *Renderbricks Sky* (Physical Sky) of its own active and takes over the render settings
  of the Renderbricks setup scene (Cycles, 1024 samples, 1920 × 1080, AgX Base Contrast, Physical Sky).
  The first time, the camera is created with the direction and lens of the setup scene's camera and
  moved so that all visible parts fill the picture with a small margin (clip end 1000, more for very
  large scenes). Your world stays in the file even while it is not used.
  The 3D viewport switches to the camera view, the camera frame filling it (also with the view
  buttons below).
- **OFF** brings back your camera, world and render settings exactly as they were, and the viewport
  its view from before. The camera
  *Renderbricks* and the sky world stay in the file, so ON is quick the next time; a camera you moved
  stays where you put it.
- The **camera button** next to it frames the camera *Renderbricks* again, e.g. after adding parts.
- **Front, Right, Back, Left, Top, Bottom** (shown while the render camera is on) turn the camera
  around the model and frame it: *Front* is the view of the render setup, *Right*, *Back* and *Left* go
  round the model in 90° steps at the same tilt, *Top* and *Bottom* look straight down and up. The
  current view is highlighted.

Apply and Convert headless never change the camera, world or render settings.

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
| `<scene>_renderbricker.log` | The log of Apply, Check and Convert headless (option *Log file*); new entries are appended. |
| `<scene>_subdiv_<version>.blend` | Result of *Convert headless* (plus its own `_rbcache.blend`). Earlier results are never overwritten. |
| `<scene>_subdiv_<version>.bat / .sh / .command` | The start script of *Convert headless*; it can be run again by hand. |

## Converting again

- **Apply on a converted scene** converts only the parts that are not up to date: new parts, parts
  converted with another variant or levels, or with an older version of the rules. When everything is
  up to date it says so and changes nothing (links switched off with *Subdivision: OFF* are switched
  back on). **Shift+click** on Apply converts all parts again; the result is the same (same copies, no
  duplicates, the cache file is rewritten and the scene saved). To change only the smoothness, change
  the viewport or render level: that switches or computes copies without running the rules.
- **Convert headless on a converted scene** opens the saved scene in the background, goes back from
  the copies to the imported meshes and converts them again. It writes a new file
  `<scene>_subdiv_<version>.blend` with its own cache file; the open scene and its cache stay
  unchanged, and earlier results are never overwritten (a number is added).

## About

The sub-panel **About** shows the copyright, the trademark notes and links to
[www.renderbricks.com](https://www.renderbricks.com), Facebook, YouTube and this repository.
