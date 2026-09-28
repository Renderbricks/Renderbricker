# Tutorial – from a Mecabricks scene to smooth, render-ready parts

<!-- DRAFT: the example scene, all numbers in [brackets] and the pictures T01–T10 follow once the
reference scene is chosen. Pictures: Blender 5.2.2, reference scene, yellow numbered markers. -->

This tutorial takes you through the whole workflow once, step by step. It uses [example scene] as
example; the numbers in brackets are the values of that example.

**You need:** Blender 4.5 LTS or newer with the add-on installed ([Install](#0-install-the-add-on)),
and a scene built in [Mecabricks](https://www.mecabricks.com) and imported into Blender with the
Mecabricks Advanced add-on.

**Time:** about [5] minutes of work; the conversion itself takes [1] minute for this scene.

<!-- IMAGE T00: before / after – the same close-up rendered from the import and after Apply -->

**How the idea works:** Mecabricks parts are modelled for real-time display: flat faces, hard
corners, round shapes made of a few segments. A subdivision surface makes them smooth – but
without guidance it rounds everything, and a brick looks like soap. Renderbricker first decides
for every edge whether the real part is sharp or round there (a *crease*), following a rule set
that was built and checked part by part against photos of the real elements. Then it bakes the
subdivided result into a copy of each part mesh. All links of a part – a scene may use the same
brick a thousand times – share that one copy, and the imported mesh stays untouched in the file.

Every step below has the same structure: **what it is for**, the **numbered actions** (the numbers
match the markers in the picture), a **check** that tells you it worked, and an optional **why**.

Contents: [0 Install](#0-install-the-add-on) · [1 Open and save](#step-1-open-and-save-the-scene) ·
[2 Settings](#step-2-settings) · [3 Apply](#step-3-apply) · [4 Check](#step-4-check) ·
[5 Compare](#step-5-compare-with-the-import) · [6 Render](#step-6-render) ·
[7 Save As and the cache](#step-7-save-as-and-the-cache-file) ·
[8 Large scenes](#step-8-large-scenes-convert-headless) · [9 Undo everything](#step-9-remove)

---

## 0. Install the add-on

<!-- IMAGE T01: Preferences → Add-ons, Install from Disk, Renderbricker enabled -->

**[⬇ Download renderbricker-<version>.zip](https://github.com/Renderbricks/Renderbricker/releases/latest)** (latest release)

1. *Edit → Preferences → Add-ons*, open the menu at the top right and choose
   **Install from Disk…**, then pick the zip.
2. Tick **Renderbricker** to enable it.

**Check:** in the 3D viewport, press **N** – the sidebar has a tab **Renderbricker**.

> **Start Guide** at the top of the panel leads through the steps below inside Blender, one step
> at a time with the explanations.

---

## Step 1: Open and save the scene

<!-- IMAGE T02: the imported example scene in the viewport, sidebar tab Renderbricker open -->

**What it is for:** the add-on writes its copies into a cache file next to the scene and saves
the scene when it is done – the scene needs a file first.

1. Open the imported scene ([example scene]).
2. Save it under the name you want to keep (*File → Save As*).

**Check:** the title bar shows the file name.

---

## Step 2: Settings

<!-- IMAGE T03: the panel with the default settings, markers 1–5 -->

**What it is for:** the defaults suit most scenes; here is what they mean.

1. **All** – every part of the scene. *Selected* converts only the selected objects, *Collection*
   the parts of one collection (with its child collections) – choose it in the field below.
2. **A – Mecabricks normals** – keeps the shading of the import. *B* gives crisper logos.
3. **Viewport 1 / Render 2** – smooth enough to judge the viewport, full quality in the render.
4. **Use several cores** – on; larger scenes run in parallel background Blenders.
5. **Cache file next to the scene** – on; the scene file stays small.

**Why two levels:** level 2 has three to four times the faces of level 1. The viewport stays fast
with level 1, and F12 switches to level 2 only while it renders.

---

## Step 3: Apply

<!-- IMAGE T04: progress bar during Apply; T05: summary after Apply -->

1. Press **Apply**.

A progress bar shows the parts and the time left; **Esc** cancels. At the end the summary says how
many parts were converted, that the copies were written into `[scene]_rbcache.blend` and that the
scene was saved.

**Check:** the button now reads **Subdivision: ON**, and the parts look smooth.

**Why a copy:** the imported mesh is never changed. The copy `<part> L1` (viewport) and
`<part> L2` (render) carry the subdivision; every link of the part points to them.

---

## Step 4: Check

<!-- IMAGE T06: Check result, a problem entry with the select arrow -->

1. Press **Check**.

**Check:** *[…] meshes, 0 with problems*. If a part is listed, the arrow next to it selects and
frames it – see [Troubleshooting](TROUBLESHOOTING.md) and [Known issues](KNOWN_ISSUES.md).

---

## Step 5: Compare with the import

<!-- IMAGE T07: the same part with Subdivision ON and OFF side by side -->

1. Press **Subdivision: ON** – it switches to **OFF** and every link shows the import.
2. Press it again to switch back.

**Check:** sharp edges of the real part stay sharp (brick edges, notches, hexagon sockets), round
shapes become round (studs, tires, curved slopes).

---

## Step 6: Render

<!-- IMAGE T08: F12 render of the example scene -->

1. Press **F12** (or *Render → Render Image (Renderbricker levels)*).

**Check:** the render shows the smooth render level; after the render the viewport is back on
level 1.

---

## Step 7: Save As and the cache file

<!-- IMAGE T09: the cache box with Move cache here / Copy cache here -->

**What it is for:** the copies live in `<scene>_rbcache.blend`. When you save the scene under
another name or in another folder, the new file still links the old cache.

1. After *Save As*, the panel shows **Cache of another scene**.
2. Press **Move cache here** to take the cache along, or **Copy cache here** to keep one for each
   file.

**Check:** the panel shows *Cache: <new name>_rbcache.blend*.

---

## Step 8: Large scenes: Convert headless

<!-- IMAGE T10: the terminal window of Convert headless with its progress lines -->

**What it is for:** scenes with thousands of parts convert faster without the window.

1. Press **Convert headless**.

A terminal opens and shows the progress. The open scene is not changed; the result is written as
`<scene>_subdiv_<version>.blend` next to it. Open that file when the terminal says *Done*.

---

## Step 9: Remove

1. Press **Remove** to take the scene back to the plain import. The copies are removed.

---

Next: all settings in the [Reference](REFERENCE.md); the rules and where each comes from in
[RULES.md](RULES.md).
