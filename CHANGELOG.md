# Changelog

Functional changes of the add-on "Renderbricks: Mecabricks Subdiv". Rules versions refer to [docs/RULES.md](docs/RULES.md).

## 1.12.2 – 2026-09-28 (rules 3.2)
- Hexagon sockets stay faceted (W5b): six concave walls at 60° are a designed hex socket, not a polygonised circle.

## 1.12.1 – 2026-09-28
- The On/Off button shows the state: "Subdivision: ON" (pressed), "OFF" or "partly on".
- After Apply or a level change that wrote the cache file, the scene is saved automatically.

## 1.12.0 – 2026-09-27 (rules 3.1)
- Designed corners (W15): a long crease edge turning into a short one that ends at a junction keeps a sharp corner (tire 2515); only on mechanical parts where every face is curved, hair keeps its soft corners.

## 1.11.5 – 2026-09-27
- F12 / Ctrl+F12 switch to the render level in the main thread before the render and back afterwards (switching from the render thread crashed Blender in the window).
- Changing the viewport level always runs with a progress bar; the copies are looked up through an index (Dungeon: 23 s frozen → 2.7 s).

## 1.11.3 – 2026-09-27
- Blender 5.3: a linked cache copy without a user gets a temporary fake user before its override is created.

## 1.11.0 – 1.11.2 – 2026-09-27
- Unticking "Cache file next to the scene" takes the copies back into the scene; ticking it writes the cache again.
- Progress bars for writing, moving, copying and switching the cache; link time estimate.

## 1.10.0 – 1.10.2 – 2026-09-27
- Cache copies are linked as library overrides that carry the original's materials (keeps Cycles instancing).
- "Move cache here" / "Copy cache here" after Save As.

## 1.9.0 – 2026-09-26
- Cache file `<scene>_rbcache.blend` next to the scene; the scene file keeps only the originals.

## 1.8.0 – 1.8.1 – 2026-09-26
- "Use several cores": Apply runs the parts in parallel background Blenders.
- Workers write their copies in batches and wait for memory instead of skipping parts.

## 1.7.0 – 2026-09-26
- Headless conversion on several cores.

## 1.6.0 – 1.6.9 – 2026-09-25/26 (rules 3.0)
- Seams are welded in a temporary copy; the original mesh gets nothing (rules 3.0).
- Steep inner edges (W12), planes beside a bevel (W13), UVs smoothed with boundaries kept (W14).
- Results carry the add-on version in their file name.
