# Quick start

The shortest way from a Mecabricks scene to smooth, render-ready parts. Each line is one click or
one decision; the [tutorial](TUTORIAL.md) explains every step with pictures. New to the add-on? Press
**Start Guide** at the top of the panel – it leads through the same steps inside Blender.

| # | In Blender | You see |
|---|---|---|
| 1 | [Download](https://github.com/Renderbricks/Renderbricker/releases/latest) `renderbricker-<version>.zip`, install it (*Preferences → Add-ons → Install from Disk*), enable **Renderbricker** | Sidebar tab **Renderbricker** (press N) |
| 2 | Open a scene imported with the Mecabricks Lite or Advanced add-on and save it | – |
| 3 | Leave **All** (or pick **Collection** and a collection), **A – Mecabricks normals**, Viewport **1**, Render **2** | – |
| 4 | **Apply** | progress bar, then *… copies in <scene>_rbcache.blend, scene saved* |
| 5 | **Check** | *Check: … meshes, 0 with problems* |
| 6 | **Subdivision: ON / OFF** to compare with the import | the button shows the state |
| 7 | **F12** | the render uses the render level |

Large scene? Use **Convert headless** instead of step 4: the conversion runs in a terminal and
writes `<scene>_subdiv_<version>.blend` next to your scene, which stays unchanged.
