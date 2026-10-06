<div align="justify">

# Reference – all settings

The panel is in the 3D View­port sidebar (press N), tab **Ren­der­bricker**. Its header shows the
add-on version. Defaults in brackets. The
tooltips in Blender say the same in short.

## Import from Mecabricks

**Import from Mecabricks** at the very top of the panel imports a Mecabricks scene (`.zmbx`) – the same
as *File > Import > Mecabricks (.zmbx)*. It needs the Mecabricks Lite or Advanced add-on by Nicolas
'Scrubs' Jarraud, installed and enabled; without it the button is greyed out, with a note and a link to
[www.mecabricks.com](https://www.mecabricks.com) below it.

## Start Guide

**Start Guide** at the top of the panel replaces the panel by a guide through the work­flow in eight
steps: save the scene, choose the parts, set­tings, Apply, Check, compare with the import, render, and
what next. Every step explains its func­tions in bullet points and shows only its own con­trols; a
status line says what is still open (red) or done (green, with a tick), the action of the step is
high­lighted, and **Next** is high­lighted once the step is done. **Back** and the **×** in the step
header work any time.

## Settings

| Setting | Default | What it does |
|---|---|---|
| **All / Selected / Collection** | All | Which mesh objects Apply, Check, On/Off, Levels and Remove work on: every mesh object in the scene, the selected ones, or the ones in the collections of a list and their child collections (below *Collection*: **+** adds the collection active in the Outliner, **−** removes the selected entry; the list starts empty). Only the links in scope switch to the copy; other links of the same part keep the original until they are converted too. *Convert headless* always converts the whole scene. |
| **Variant** | A – Mecabricks normals | **A:** the subdivision interpolates the custom normals of the import – the shading stays as Mecabricks made it, logos on studs look soft. **B – geometric normals:** normals of the smoothed surface, creased edges sharp – crisper logos, but the shading of the import is not kept. |
| **Viewport** level | 1 | Subdivision shown in the viewport. 0 shows the original mesh (no viewport copy is stored – the file gets about a fifth smaller). Levels already baked switch at once, others are computed the first time (with a progress bar). |
| **Render** level | 2 | Subdivision used for rendering; the checks use this level. 2 is enough even for close-ups. Raising a level above 2 asks first – *Cancel* (or Esc) keeps the old level – and the panel shows a warning while it is above 2: every level multiplies the faces by three to four, so memory, file size and conversion time grow a lot for a small visible gain. |
| **Use several Blender processes** | on | Apply on larger scenes (about 40 meshes and more) starts several Blenders in the background that share the parts, and loads the result into this scene. The scene is saved first. How many: at most one per two processor cores, and only as many as fit into the free memory – estimated per scene from its parts; each of them uses several processor cores itself. |
| **Low Memory** | Auto | How the Blender processes share the parts. **Off:** every process gets its share at once and books large parts in a shared memory ledger before it bakes them – the fastest way when there is memory enough. **On:** the parts are cut into small segments (every large part a segment of its own), each baked by a fresh Blender that ends afterwards and gives its memory back; a segment starts only when the free memory has room for it – slower, for computers with 16 or 32 GB or very large parts. **Auto:** on only when a single part needs so much memory that otherwise less than half the processes could run (NINJAGO City with a 27 GB part: 229 s instead of 674 s). Headless: `--low-memory auto\|on\|off`. |
| **Log file** | off | Appends the results of Apply, Check and Convert headless to `<scene>_Renderbricker.log` next to the scene: date, add-on and Blender version, settings, the summary and the full problem list (the panel shows the first 12 problems). Needs a saved scene. The icon next to the option opens the log file. |
| **Cache file next to the scene** | on | The subdivided copies are kept in `<scene>_rbcache.blend` next to the scene and linked into it, so the scene file stays about as large as the import. Needs a saved scene. Switching it off takes the copies back into the scene file; switching it on writes them out again. |

## Buttons

| Button | What it does |
|---|---|
| **Apply** | Sets the creases of each part mesh once and bakes the subdivision into a copy of it (`<mesh> L<level>`) that all its links use. The original mesh stays in the file, unchanged. Parts whose copies already match the settings (levels, variant), the current rules and their import (an import edited since is converted again) are skipped – after adding or editing parts, Apply converts only those. **Shift+click** converts all parts again. When nothing has changed since the last Apply, the button reads *Apply: up to date*; pressing it anyway says so at the mouse. With the cache on, the copies are written into the cache file and the scene is saved. Esc cancels; the parts converted so far keep their copies. |
| **Check** | Looks for folded faces and seam gaps in the render copies and lists the objects with problems; the arrow button next to an entry selects and frames that object. |
| **Subdivision: ON / OFF** | Switches every link between the subdivided copy and the original mesh (viewport and render). The button shows the state: *ON* (pressed), *OFF*, or *partly on* when objects differ. |
| **Update cache** | Shown under Apply when parts were edited and converted again while the scene uses a cache file: their new copies are still in the scene file. Writes them into the cache – the other copies are carried over unchanged, nothing is converted again. |
| **Remove** | Points the links back to the original meshes and removes the copies – the scene is the plain import again. With the scope *All* it covers the whole file: every scene, and copies of parts deleted in the meantime. |
| **Convert headless** | Saves the scene, writes a start script next to it (`.bat` on Windows, `.command` on macOS, `.sh` on Linux) and runs it in a terminal. Blender converts the whole scene in the background on several cores and saves the result as `<scene>_subdiv_<version>.blend` – the open scene is not changed. If no terminal is found (Linux), the panel names the script to start by hand. |
| **Move cache here / Copy cache here** | Shown when the scene was saved under another name or in another folder and still links the cache of the old scene file. *Move* renames the cache to belong to this scene (the old scene file then shows its original meshes); *Copy* gives this scene a cache of its own. |

## Render camera

**Render camera: ON / OFF** below the set­tings switches between your own render setup and the
Ren­der­bricks one – nothing of yours is over­writ­ten:

- **ON** keeps the scene's camera, world and render set­tings, then makes the camera *Ren­der­bricks*
  and a world *Ren­der­bricks Sky* (Phys­i­cal Sky) of its own active and takes over the render set­tings
  of the Ren­der­bricks setup scene (Cycles, 1920 × 1080, Phys­i­cal Sky); the samples start on *Low*
  (128). In Blender 5.x the view becomes **ACES 2.0** with the look *ACES 2.0 - Ref­er­ence Gamut
  Com­pres­sion* (Blender 4.5: AgX Base Con­trast). The file's working colour space is left as it is;
  the summary notes when it is not **ACEScg**, in which ACES 2.0 works best – set it before import­ing,
  or convert later with Blender's own colour man­age­ment setting, which con­verts the colours.
  The first time, the camera is created with the direc­tion and lens of the setup scene's camera and
  moved so that all visible parts fill the picture with a small margin (clip end 1000, more for very
  large scenes). Your world stays in the file even while it is not used.
  The picture is land­scape 16:9, or por­trait 9:16 when the model is taller than its widest side
  (the res­o­lu­tion of the setup scene is turned; *Top* and *Bottom* are always land­scape).
  The 3D view­port switches to the camera view, the camera frame filling it (also with the view
  buttons below), with rela­tion­ship lines off and sta­tis­tics on. The Prop­er­ties editor shows the
  *Output* tab (res­o­lu­tion, scale, file); OFF brings back the tab it had.
- **OFF** brings back your camera, world and render set­tings exactly as they were, and the view­port
  its view and over­lays from before. The camera
  *Ren­der­bricks* and the sky world stay in the file, so ON is quick the next time; a camera you moved
  stays where you put it.
- **ON again** brings back the Ren­der­bricks set­tings you had at the last OFF (samples, Trans­par­ent,
  Res­o­lu­tion Scale, the view, the sun …) – they are kept in the scene, also after saving.
  **Shift+click** on ON starts fresh from the setup scene (samples on *Low*).
- The **camera button** next to it frames the camera *Ren­der­bricks* again, e.g. after adding parts.
- **Cycles | EEVEE** right below: two switches, both off at the start. **Cycles** on: the 3D views
  render with Cycles (*Ren­dered*) and F12 renders with Cycles – the phys­i­cal sky with its sun disc
  lights the model. **EEVEE** on: the 3D views render with EEVEE (*Ren­dered*) and F12 renders with
  EEVEE. Pressed again, the views go back to the shading they had;
  the engine for F12 stays the last one chosen. EEVEE takes the sky's sun only very weakly, so with
  EEVEE the sky lights without its disc and the lamp *Ren­der­bricks Sun* stands in for the sun: it
  follows the sun sliders, *Sun: turns with the camera*, *Bottom* and direct edits of the Sky node,
  with the strength and colour the sun has in Cycles (mea­sured over ele­va­tion and alti­tude). EEVEE is
  set to every­thing it can do: ray tracing and global illu­mi­na­tion at full res­o­lu­tion, soft shadows
  with the most rays and steps, also in the view­port, a sharp world probe. In Cycles, and with the
  render camera off, the lamp is hidden.
- **Models at real size** (import scale 0.001, as the reworked Mecabricks importers use): EEVEE's
  shadow and ray-tracing sizes follow the scale of the parts, and when the scale is changed in the
  Mecabricks panel the camera *Ren­der­bricks* moves with the model – the picture stays as it was.
- **Samples:** Low 128, Medium 256, Good 512, High 1024 set the render samples (Cycles and EEVEE)
  while the render camera is on; the current level is high­lighted, ON starts on *Low*. OFF brings
  your own samples back.
- **Trans­par­ent: on / off** switches Film > Trans­par­ent together with Trans­par­ent Glass: the sky is
  left out of the picture (alpha) and glass shows what lies behind it; the sky still lights the model.
- **Res­o­lu­tion Scale** is the render res­o­lu­tion in percent (Output > Format), e.g. 25 % for quick
  tests. OFF brings both back as you had them.
- **Render (F12)** below renders through the camera *Ren­der­bricks* with the render level, into the slot of the current view: Slot 1 Front, 2 Right, 3 Back, 4 Left, 5 Top, 6 Bottom (the slots of the Render window carry the names of the views, so earlier views stay there to compare).
- **All views** renders the six views one after the other, each into its slot; the camera then returns to the view it had. Esc in the Render window stops the running view and the chain; closing the Render window stops only the running view, the chain goes on with the next.
- **Only some col­lec­tions:** the camera icon of a col­lec­tion in the *Col­lec­tion* list marks it for the
  render camera (one or several). With the camera on, only the marked col­lec­tions are shown and
  ren­dered, and the camera frames them; marking or unmark­ing while it is on updates at once. OFF
  gives every object its vis­i­bil­ity back – what you had hidden your­self stays hidden.
- **Front, Right, Back, Left, Top, Bottom** (shown in pairs while the render camera is on) turn the camera
  around the model and frame it: *Front* is the view of the render setup, *Right*, *Back* and *Left* go
  round the model in 90° steps at the same tilt, *Top* and *Bottom* look straight down and up, square
  to the model with its longer side across the picture and its front at the bottom. The
  current view is highlighted. For *Bottom* the sky is mir­rored ver­ti­cally: the sun and the bright
  sky are below the model and light its under­side as they light the top from above. The phys­i­cal
  sky cannot be turned upside down (a sun below the horizon is night), so the add-on renders it once
  as a panorama (a few seconds, in a Blender of its own) and shows it mir­rored in a world
  *Ren­der­bricks Sky Below*; it is made again only when the sky is changed.
- **Sun: fixed / Sun: turns with the camera** – fixed (the default): the sun stays where it is, and
  the views show the model from every side in the same light. Turning: the sun goes round with the
  camera, so every view is lit like *Front*. Switch­ing back puts the sun back to its place.
- **Ele­va­tion, Rota­tion, Alti­tude, Strength** (shown below the sun button while the render camera is
  on) set the sky *Ren­der­bricks Sky*. *Ele­va­tion* (60°) is the height of the sun from 15° below the
  horizon over the top (90°) to the other side (195°); *Rota­tion* (120°) its direc­tion, 0° to 360° –
  with *Sun: turns with the camera* the direc­tion for *Front*; *Alti­tude* (3,000 m) the height of the
  viewer, 0 to 100,000 m – the first half of the slider covers 0 to 10,000 m, the slider shows its
  posi­tion and the name the metres, a typed number above 100 is taken as metres; *Strength* (0.06 under ACES 2.0, 0.03 under AgX)
  the bright­ness of the sky, 0.01 to 0.1 on the slider, any value typed. The arrows beside a slider go
  one step (10°; 1,000 m up to 10,000 m, 10,000 m above; 0.01), the round arrow sets it back to the
  stan­dard in brackets. The values are kept with the sky in the file. With
  *Bottom* the mir­rored sky is made again a moment after the last change.
- **Sun in picture: off / on** (off) – off: the sun disc is not seen where the camera looks at the sky,
  but it lights the model exactly as before – high­lights, the sharp­ness of the shadows and
  reflec­tions stay. The sky has a second Sky Texture without the disc for the camera rays (Light
  Path > *Is Camera Ray*, node *Sun in picture*); the sliders set both. On: the disc is seen. EEVEE
  never shows the disc in the background.
- **Drag­ging a slider** (a Blender feature): **Shift** for fine control, **Ctrl** for coarse steps;
  a double-click types an exact value.

Apply and Convert head­less never change the camera, world or render settings.

## Rendering

**F12** and **Ctrl+F12** render with the render level: the links are switched to the render copies
before the render starts and back to the view­port level afterwards. The same is in the *Render*
menu as *Render Image / Render Ani­ma­tion (Ren­der­bricker levels)*. Renders started from the command
line (`blender -b … -f`) switch the level as well.

## Files

| File | What it is |
|---|---|
| `<scene>.blend` | Your scene; with the cache on it links the copies and stays small. |
| `<scene>_rbcache.blend` | The subdivided copies. Keep it next to the scene; when you move or rename the scene, move or rename the cache with it, or use *Move cache here* after *Save As*. |
| `<scene>_Renderbricker.log` | The log of Apply, Check and Convert headless (option *Log file*); new entries are appended. |
| `<scene>_subdiv_<version>.blend` | Result of *Convert headless* (plus its own `_rbcache.blend`). Earlier results are never overwritten. |
| `<scene>_subdiv_<version>.bat / .sh / .command` | The start script of *Convert headless*; it can be run again by hand. |

## Converting again

- **Apply on a con­verted scene** con­verts only the parts that are not up to date: new parts, parts
  con­verted with another variant or levels, or with an older version of the rules. When every­thing is
  up to date it says so and changes nothing (links switched off with *Sub­di­vi­sion: OFF* are switched
  back on). **Shift+click** on Apply con­verts all parts again; the result is the same (same copies, no
  dupli­cates, the cache file is rewrit­ten and the scene saved). To change only the smooth­ness, change
  the view­port or render level: that switches or com­putes copies without running the rules.
- **Convert head­less on a con­verted scene** opens the saved scene in the back­ground, goes back from
  the copies to the imported meshes and con­verts them again. It writes a new file
  `<scene>_subdiv_<version>.blend` with its own cache file; the open scene and its cache stay
  unchanged, and earlier results are never over­writ­ten (a number is added).

## Editing a part

A converted part shows its subdivided copy; edits belong on the imported mesh (the copy is rebuilt on every Apply,
and with the cache file Blender does not even allow Edit Mode on it).

1. Select the part and press **Tab**: all its links switch to the imported mesh (*Subdivision OFF* for them) and
   Edit Mode starts on it.
2. Edit as usual.
3. Leave Edit Mode (**Tab**, or any other way): the part is converted again from the edited mesh and its links switch
   back on. If nothing was changed, it only switches back.
4. With the cache file the new copy stays in the scene file; under Apply the panel names the edited parts and offers
   **Update cache**.

Only the **Tab** key can be taken over by the add-on – the *Mode* menu in the header calls Blender's own operator.
From that menu, Edit Mode works on parts whose copies are in the scene file (the add-on then switches to the import as
well), not on parts from the cache file: use Tab there.

## About

The sub-panel **About** shows the copy­right, the trade­mark notes and links to
[www.renderbricks.com](https://www.renderbricks.com), Face­book, YouTube and this repository.

</div>
