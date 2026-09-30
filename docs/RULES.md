# Mecabricks → Subdivision Surface: Rule Set

Version 3.2 · 2026-09-28 (3.1: W15, 3.2: W5b) · implemented in `addon/renderbricker/rbcore/` (`creases.py`, `welding.py`: `process`, weld; the island rules up to 2.4 remain as `process_24`, `--method rules24`), checked by `scripts/core/verify_part.py` and `scripts/core/verify_generic.py`
Every rule names the part and the development run in which it was found; the run records are kept with the project, not in this repository.

The rules make imported Mecabricks parts subdividable (Catmull-Clark) without cracks, folds or lost detail. Each rule comes from a concrete finding; the column *Origin* names the part and run where it was found.

---

## W · Rules 3.0: weld (runs 48–50, refined 53–56)

The island rules (sections 2–4) treat every Mecabricks island as an open surface and hold the
seams together with pins – pins that keep silhouettes angular (tail of 10509a4, nostril). Rules
3.0 weld the seams in a temporary copy instead; the original mesh gets nothing (no attributes).

| No. | Rule | Why | Source |
|---|---|---|---|
| W1 | **Weld** coincident open vertices along seams (open edges whose end points coincide with those of another open edge), in a temporary copy. Never two corners of one face, never two corners of one face onto one target, no point contacts; faces that would become duplicates stay unwelded. | Seams become ordinary edges: no seam gaps, creased edge chains smooth as curves. | runs 48, 50 (NINJAGO lost corners, 1,472 → 1,448 loops) |
| W2 | **Seam creases:** a former seam is creased if its faces meet at ≥ 10°; seams of a **smooth wedge** (a thin island whose tip turns ≥ 150° while every partner island at that tip bends < 30°) only from ≥ 30° (WEDGE_SEAM). Nearly tangent seams (open seams through one surface) stay smooth. Edges with more than two faces: creased. Logo islands: inner edges above 50° (as R-logo). | Mecabricks splits at hard edges; tangent splits are no edges. Hair 13768: a 29° seam made a third crease and so a corner at the face opening (P18). The first form (30° between any two curved islands, run 54) left the Technic pins/axles of the Porsche too soft (32016 0.104 → 0.42) – run 56 narrowed it to smooth wedges. | runs 48, 54, 56 |
| W3 | **Flat stays flat:** a flat island without round outline gets all its inner edges creased (as R2). | Left free, open edges of flat faces curled inward (29119 0.14). | run 50 |
| W4 | **Corners:** on a crease chain (creased and open edges) a vertex with two chain edges turning > 30° that is not on a circle/arc (K3/K3b applied to the chain) gets a vertex crease; three creased edges are a corner anyway. Sharp corners of the original island outlines stay pinned – except the tips of smooth wedges (as W2: turn ≥ 150°, partners bend < 30°); a wedge tip where a partner island itself turns sharply (Technic ends) stays pinned. **Organic shapes** (every face at the vertex in a curved island): a bend counts as a corner from 60°; a hairpin turn (≥ 150°) is the end of a groove or strand and stays free. | 54200: a corner where three islands meet almost tangentially lost all creases, the surface curled 0.29. Hair 13768: 47° outline corners and a 163° wedge tip pinned the face opening (P18). | runs 48, 50, 53, 54, 55, 56 |
| W5 | **Ring:** ≥ 6 flat patches around a recess or hole (walls facing the axis), meeting at equal angles (±1°) with one angle to a common axis = polygonised cylinder/cone: wall seams smooth, smooth normals on that island. Convex rings (diamond 30153, hex heads) stay faceted. | Nostril of 10509a4 round; diamond facets are design. | runs 48, 50 |
| W5b | **Hexagon sockets stay faceted:** a concave ring of exactly six walls bending by 60° (±1°) – a regular planar hexagon – is no polygonised circle and keeps its creases. | Box wrench 11402p2 (Coppersteam, real part: hex socket) became a round hole. Scan of all 19 imports: concave six-wall rings are only this one (60°) and the nostril of 10509a4 (42°, a cone – stays round); Mecabricks' small round holes have 8 walls (19798, 5904 – stay round, reference photos). | run 75 |
| W6 | **Relief tips:** a short creased edge (< 0.5) between two small wall faces (longest edge < 1.0), both ends three-crease corners where the relief edge bends by 45° to below 80° (a V tip), the other faces in curved islands, stays smooth and unpinned (imported normals kept). Bulge check: if the surface there moves more than 20 % of the step height from the original, the tip is creased again. | Zigzag mane of 10509a4: tips bend 59–76° (round); stroke ends bulged → check. The rib ends of the pistol 95199 are right-angled box ends (80–100°) and must stay hard (user, P19); the circular rib outlines bend 22°. Watch the narrow margin at 80°. | runs 48, 54 |
| W7 | **Degenerate faces** (zero area): all edges creased, corners pinned. | 54200: notch at the foot of the body. | run 50 |
| W8 | **Open points that stay apart** (unwelded coincident vertices, T vertices and the ends of their host edge): pinned on every side. | 4973 cracked at an unwelded point; T gaps ≤ 0.0001 (NINJAGO before 0.023). Costs a slight kink in the outline at such points (as the seam pins of 2.4). | run 50 |
| W9 | **Normals:** the imported custom normals are set explicitly on the welded copy (same corner order), former seams marked sharp; rings (W5) get smooth normals. | Variant A keeps Mecabricks shading. | run 48 |
| W10 | **Fold repair** as section 4 (folding faces 0.5 → 1.0 → with neighbours). | Large flat faces of the horse folded. | run 48 |
| W12 | **Steep inner edges:** an edge inside one island (not a former seam) whose faces meet at ≥ 85° is creased (INNER_SHARP). | Mecabricks sometimes leaves a right angle inside an island with normals smooth across it; left free, subdivision rounds it off: 35787 recess corner 1.39, NINJAGO 2450 rim 1.56, tyre 15413 0.64 → 0.08 / 0.28 / 0.37. No tessellated curve bends that much; hair, Technic and all other parts unchanged. | run 57 |
| W13 | **Plane beside a bevel:** Mecabricks models rounded edges as a strip of narrow faces in the same island as the large plane faces beside them. Within an island, planar patches (normals within 1°) are found; an edge between two patches bending ≥ 10° is creased when one patch is at least 8× the area of the other (PLANE_RATIO). | Left free, the subdivision pulled the rounding far into the planes – bevels grew, the part shrank (user, Ratatouille 86209). With W13 the bevel rounds within its own width. Deviation better in 344 meshes, worse in none (8 models); horse and hairs without hard lines. Fallback: faces that still fold after the repair (W10) release the W13 edges within twice their size and the part is welded again (Bugatti 35188: 4 folds → 0). | run 58 |
| W14 | **UVs smoothed, boundaries kept:** the Subdivision modifier keeps `uv_smooth = 'PRESERVE_BOUNDARIES'` (Blender's "Keep Boundaries"). | The subdivision also moves vertices *within* a plane; smoothed UVs move along, so prints keep their shape. Tested on 86209 (texture as emission): linear UVs (`'NONE'`, add-on 1.6.7/1.6.8) and UVs projected from the original triangles distort the lettering; all smoothing modes keep it. The wavy print lines the user saw came from the spreading bevel and are gone with W13. | run 58 |
| W15 | **Designed corners:** a crease-chain vertex (two chain edges) turning ≥ 20° (DESIGN_TURN) gets a vertex crease when its two chain edges differ in length ≥ 4× (DESIGN_RATIO) and the short edge ends at a junction of ≥ 3 creased edges – also on organic spots (W4: 60°), there only on parts with ≥ 12 % of the area in not curved islands (MECH_FLAT). **W15b:** an uncreased edge bending ≥ 20° between such a corner and another pinned corner is creased too. Arcs (K3/K3b) and groove ends stay free. | Tire 2515 (SuperStarDestroyer, user): the groove ends turn by 27° / 36° (edges 11.2 : 1.2, 10.6 : 2.0) on the tread, which counts as organic – rounded off; the real part (BrickLink photo, user photo) has sharp step ends. Without the junction condition W15 put kinks where a straight line runs into a polygonised curve (Banana 3820v2, 11214, 98313); without MECH_FLAT hair corners turned angular (11908, 13765, 13766; hairs ≤ 0.10, tire 0.17). W15b: with both ends pinned, the rounding of the 35° wall bend between them bulged into a wedge. 116 meshes in 8 models change (largest: tire 1.69, 56904 1.16, notch corners of 2741/11272 now as the import); hairs and horse unchanged. | run 73 |
| W11 | **Checks:** folds against the original face order (welding keeps all faces), T gaps exact from the stored T points (`rb_tv`), deviation from the original surface (`verify_generic.py`), and close-ups of risky spots (`runs/run50_weld_all/scripts/spot_sheets.py`) – the deviation measure missed the 54200 notch. | | run 50 |

## 0 · Principles

| # | Rule | Why | Origin |
|---|---|---|---|
| P1 | **The imported mesh is never modified.** No merging, splitting, moving or replacing of vertices, edges or faces. Only attributes (`crease_edge`, `crease_vert`, `sharp_edge`) and modifiers are added. | The originals are the reference; anything else is a different model. | User decision, run 16 |
| P2 | **Shading data stays as imported.** `sharp_face` flags and custom normals are not touched. | Mecabricks stores the look in custom normals encoded against the flat flags; changing the flags scrambles them. | 3001, run 7 |
| P3 | **Subdiv off = import.** With the modifier disabled the part must look exactly like the import. | Toggle without side effects. | 3001, run 7 |
| P4 | **Build with the Blender version that saved the import.** | Newer files do not open in older versions (5.3 alpha vs 5.2.2). | Run 11 |
| P5 | **Every rule is checked by measurement and render before it counts.** | Several "fixes" moved the defect elsewhere (runs 2, 4, 15). | All runs |
| P6 | **Only the original meshes are processed; the links take over the result.** Models are meshes plus their instances (objects linking one mesh; material on the mesh data). Creases go into the mesh; the subdivision is applied once per mesh into a copy of it (`<mesh> L<level>`), and every link points to that copy. No modifiers on the links, no extra objects. The original stays in the file unchanged (fake user): On/Off points the links back to it. Viewport and render level may differ: then two copies, and the add-on switches the links to the render copy for the duration of a render. | A modifier on every link made Blender subdivide (and cache) every instance separately: Porsche 2,710 objects > 80 GB, crash in the window. Run 37 tried hidden master objects + GN instances (11 GB) – the user did not want extra objects. With copies: 2.4 GB, identical positions and custom normals. | User, runs 36–38 |

## 1 · How Mecabricks builds parts (observed)

- Faces are split into **loose islands along hard edges**; hard edges are open boundaries, not creases.
- All faces are **flat-flagged**; the look comes from **custom normals**.
- Circles are **regular polygons** (12, 16, 32, 64 segments).
- Stud logos are an **embossed layer** (height ≈ 0.12, sloped flanks ~68°) with **open slits** at inner corners (bottom vertex duplicated).
- Axes differ per part (3001: Y up; 3648: axle along Z) – no rule may assume an axis or a size.

## 2 · Recognition

| # | Class | Recognised by |
|---|---|---|
| K1 | **island** | faces connected across shared edges |
| K2 | **flat** | all face normals of the island within 1° |
| K3 | **circle vertex** | boundary turn 5–40° **and** the turn repeats regularly: both neighbours within ±3° (period 1), **or** both neighbours also 5–40° and the vertices two steps away within ±3° (period 2 – alternating circles such as 13.9°/8.6° on the 42610 rim, run 26–27) |
| K3b | **arc vertex** (unevenly divided curve) | lies in a run of ≥ 3 consecutive boundary turns of 3–40° that bends ≥ 45° in all, neighbouring turns differing by at most ×2.5 – e.g. a quarter circle as 9·14·11·17·22·16° or a fillet easing into a straight edge as 32·27·13·6·7·4° (part.380 = 54200.002, Banana_Mech, run 41). Counts as round like K3, first and last vertex of the run included. A designed polygon corner (45° chamfer, 90° corners) never forms such a run |
| K4 | **sharp corner** | boundary turn > 30° and not a circle vertex |
| K5 | **flat-round** | flat island with at least one circle vertex |
| K6 | **curved** | not flat |
| K7 | **logo** | ≤ 4 units across, vertices on exactly two levels 0.05–0.30 apart along a candidate top normal (tried largest-area first, since flanks can outweigh narrow tops), flat top faces on the upper level, flanks at 40–85° |
| K8 | **seam group** | boundary vertices of different islands at the same position (0.1 µm grid) |
| K9 | **slit** | seam group whose vertices belong to the **same** island |
| K10 | **T vertex** | circle vertex with more than three edges (other edges end on the arc) |
| K11 | **broken face** of the import | area < 1e-8 (sliver triangles: duplicate or collinear vertices), **or self-intersecting** (bowtie quad: two edges cross in the face plane; run 29, Technic panels 87080/87086/64391/64683 on the Porsche, one of them also facing the wrong way). Its subdivision folds because the original is folded, so the fold check skips it and it never triggers escalation – otherwise the whole island gets fully creased (a round ring turned polygonal) and the fold stays anyway. Zero-area faces are also left out of the flatness test (reference = the island's largest face) |

## 3 · Crease rules

| # | Applies to | Rule | Origin |
|---|---|---|---|
| R1 | flat | Crease **every edge** 1.0 – subdivides linearly, keeps the exact outline, cannot fold. | 3001 rim: corners drifted 1.48 (run 1), pinning left folds (run 2) |
| R2 | flat-round | Stay smooth so round edges follow the smoothed neighbours; **sharp corners** get vertex crease 1.0. | 3001 tube rings, 3648 side faces |
| R3 | curved | Stay smooth; **sharp corners** get vertex crease 1.0 (Keep Corners only holds corners with exactly two edges). | 3001 run 1, 3648 |
| R4 | logo | Crease every edge bending **> 50°** (top outline 65–70°, inner corners ~90°; flanks ≤ 35° stay soft). | 3001, runs 1 and 5 |
| R5 | logo | Where **three or more** creased edges meet (bar joins stroke), also crease the flat top edges there. Open slit edges count as creased. | 3001 E middle bar folded (runs 6, 16) |
| R6 | slit | Pin the vertices of a slit (vertex crease 1.0) – **only where its sides follow different outlines** (S2, run 47). Sides with the same boundary neighbours move alike without a pin; pinning them froze the tail silhouette of the horse (53 pairs) and the strand ends of hair pieces. | 3001, horse 10352 (run 16); S2: horse 10354 tail, 49 hair pieces (run 47) |
| R7 | seam group | Treat alike: if one vertex is pinned, **pin all**. | Horse gaps up to 1.10, turntable 0.40 (run 13) |
| R8 | seam group | Two phases: first all pins to a fixed point; then a **partial** crease is mirrored onto the partners' single interior edge, only in unpinned groups with at most one vertex that has several interior edges (the carrier). Otherwise all are pinned. | Turntable gap 0.32 (run 14); mirror-before-pin bug caused a chain (run 20) |
| R9 | all | Circle vertices are **never** treated as corners (regularity test K3), incl. 12-gons at exactly 30°. | 3001 odd-stud mark (run 10) |
| R10 | seam group | **Branching seam:** if the members' boundary neighbours are not at the same positions (their outlines continue in different directions), pin the whole group – otherwise each side smooths along its own path and they part. | Banana_Mech 3713: gap 0.060 (run 21) |

## 4 · T fans, self-check and fold repair

**F0 · T fans (before the fold loop).** Every T fan in a flat island (arc vertex with three interior edges: a strip in the middle, two diagonals to the strip's corners) is evaluated at diagonal creases 0, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0 (mirrored onto the seam partner, T free). A fan is creased only if it **folds** at 0 or if the crease **reduces** how far its sub-edges cross the straight corner outline (depth at 0 > depth at 1.0 + 0.005). A fan that needs it gets its diagonals creased **fully (1.0)**; the T group is pinned by the seam rule. Crossings that do not react to the crease come from elsewhere and are left alone.
Why not a partial crease (runs 17–18): it would have to be mirrored onto the partner's edge, whose far end lies on the next ring – the crease runs on as a **chain of points** through the whole hole (48168: 0.051 at every ring, run 20). A pin does not travel along edges: one point at the T, the rings stay round.
Origin: 48452 upper T – no fold, but a 0.054 sliver at the rib corner, clean at 0.3; 48168 lower T – folds, clean at 0.4; 3648 gear – two fans with 0.035 slivers, clean at 0.4; other gear fans cross by a constant 0.025/0.081 unrelated to the fan (run 18).


After the crease rules the part is subdivided and every original face is compared with its sub-faces. A sub-face turned by more than 90° is a **fold**. Folding islands are repaired step by step, gentlest first; the check repeats (max. 7 passes).

| Step | Repair | Origin |
|---|---|---|
| F1 | **T fan** still folding after F0: diagonal from the T vertex at 0.4, mirrored (R8), T free. **Other folds:** crease the interior edges of the folding faces at **0.5**. | Pinning vertices never stops a fold, creasing the right edge does (run 14). Diagonal-only scan (run 17): 0.2 stops the flip but the sub-faces still cross the inside corner (visible sliver); 0.4 is the lowest clean value, point at the T 0.051 instead of 0.079 |
| F2 | Crease the interior edges of the folding faces **and their neighbours** at 1.0. | Run 12 |
| F3 | Crease **all** edges of those faces and neighbours. | Run 12 |
| F4 | flat-round only: crease the **whole island** (last resort). | Run 11 |

Why folds happen (turntable, runs 16–17): the new point on an interior edge is the average of its ends and the centres of the two faces beside it. A long neighbouring face (e.g. a rib 3.05 long instead of 2.1) pulls that point past a nearby corner and the thin face beside it flips. A crease puts the point back on the middle of the edge.

## 5 · Modifier and shading

| # | Rule |
|---|---|
| M1 | Subdivision Surface, Catmull-Clark, level 2 (viewport and render), **Use Creases** on, **Boundary Smooth: Keep Corners** (until run 41; since run 42 All + explicit corner pins, M1b), **Use Limit Surface** on, **UV Smooth: Keep Boundaries** (default; checked on prints in run 23 – shift of inked texture < 1 px on Banana_Mech; Keep Corners / None bring no consistent gain). |
| M2 | **Variant A (default, user choice):** *Use Custom Normals* on – the modifier interpolates Mecabricks' normals (soft logo, matches the import look). |
| M0 | The modifiers of M1–M3 run only on a temporary work object of the original mesh while the rules are checked and the copies are baked (`bpy.data.meshes.new_from_object`, all attributes kept); the model objects never carry them. Results are saved compressed (a car: 200–260 MB). |
| M1b | **Boundary Smooth: All** instead of Keep Corners (run 42). Keep Corners froze every boundary vertex with exactly two edges – also arc vertices on few large faces (plate corners of 36840, part.375 in Banana_Mech), and the seam rule passed the pin on to the neighbouring band. Now every two-edge boundary vertex that is *not* round (K3/K3b) gets a vertex crease – the same corners as before stay sharp – and round ones move. The copies are baked at subdivision **quality 10**: at the default 3 the limit surface near such free two-edge vertices is only approximated and seams opened by up to 0.018; at 10 they are exactly 0. The rule checks keep quality 3 (speed). Meshes above 50,000 faces are baked at quality 6 (run 45: quality 10 needs ~0.2 MB per face, the 286k-face baseplate 3811 of NINJAGO_City crashed at 33 GB; quality 6 took 24 GB, seam gaps ≤ 0.0003 < check threshold). |
| M3 | Variant B (`--shading geometric`): creased edges added to `sharp_edge`, the same Subdivision modifier as variant A but without custom normals (quality by size), then one node modifier "Mecabricks Smooth" that only shades smooth. Until run 45 the node group "Mecabricks Subdiv" also subdivided – the GN Subdivision node has no quality setting, which brought back seam gaps of 0.018 (run 45b). No driver – a driver on the object's own modifier toggle forms a dependency cycle. |

## 6 · Verification (every part, every run)

| Check | Pass |
|---|---|
| Original mesh identical (counts and positions) | exactly |
| Corner normals vs import, modifier off | 0.000° |
| Faces with folded sub-faces | 0 |
| Seam gaps at vertices (limit positions of seam groups) | 0.0000 |
| Seam gaps along edges (the 2^L−1 subdivided points of every pair of coincident original edges) | 0.0000 |
| Outline deviation | only circles smoothing (≤ ~0.07 on these parts) |
| Renders: overview, close-ups of logo, corners, seams; before/after for every change | visually clean |
| T fans: sub-edges must not cross the island's straight corner outline beyond what a full crease leaves (built into F0; scan: `experiment_fans_all.py`) | no crease-dependent crossing |
| Prints: shift of the texture where the print has ink (`tools/uv_shift.py <obj>:<uvmap>:<px>:<image>`), plus EEVEE close-ups off/on (`tools/render_prints.py`) | < 1 texture pixel on flat prints |

## 7 · Known limits

| Case | State |
|---|---|
| **T fans that need a crease** (48168 lower T, 48452 upper T, two gear fans) | One point remains at the T (0.079), the arcs around it are round. A fully round T and fold-free wedges are mutually exclusive without a mesh change (P1): the fold comes only from the diagonal, and only a crease on it stops it, which makes the T a corner (run 20 table). |
| **Tangent points** (pin hole circle touching the block's straight edge: 48168/48452 pin holes, `tools/why_pinned.py`) | Four islands meet in a branching seam (two end-face halves with 168.7° cusps, the straight edge strip, the hole wall); R10 must pin it, otherwise the pieces part. The rest of the circle shrinks by the usual Catmull-Clark amount (≈0.06–0.09 here), the pinned point does not: a V of that size remains. Not removable without a mesh change (P1). Neighbouring "points" (0.056–0.067) are the same V seen from the next arc vertices. |
| Constant crossings near some T fans (gear: 0.081 on the side faces) | Investigated (run 19): a narrow groove bends by 22.6° at a fan vertex; subdivision rounds the bend, the straight groove edge bows 0.081. Seams closed. Shape decision (keep the bend or smooth it) is open; pinning the bend point alone has no effect. |
| Parts not yet tested | plates, slopes, tiles, round parts with double curvature, tyres, hoses, minifig heads, transparent parts, whole models with many parts. |
| Rejected approaches | merging logo slits (violates P1), T-fan topology repair (run 15; violates P1 and the band folded anyway), tolerating flat folds (visible slivers, run 14). |
- **Tangent point of a rounded corner (run 42, part.375 = 36840.004):** where an arc of one island ends at a real corner of a neighbouring flat island (a straight side face), the shared point stays pinned; the arc's last turn (e.g. 15°) remains as a small kink instead of a tangent blend. Freeing it would bend the flat face and open the seam – not solvable without changing the mesh (P1).
- **Polygonal holes with split walls (run 44, horse nostril 10350):** a hole whose walls are separate flat faces meeting at the corners keeps its polygon – the corner pins of the walls hold the rim of the surrounding face; rounding the rim alone would open gaps.

## 8 · Tested parts

| Part | Content | Result |
|---|---|---|
| 3001 | Brick 2×4, logo on 8 studs | passes all checks |
| 3648 | Technic gear Z24 | passes |
| 48452 + 48168 | Technic turntable (two meshes) | passes; limit 7 (small point at one T) |
| 10509a4 | Horse: 10350 printed head, 10352, 10354 | passes; print unchanged |
| Banana_Mech | Model: 560 objects, 179 meshes, ~120 part types, 296k faces, many prints | passes (run 22); 700 logo islands, 28 T fans, 33 s build; contact sheets without visible defects |

## 9 · Process for a new part

1. Import: `import_zmbx.py` (Mecabricks Advanced add-on, same Blender version as P4).
2. Build: `rbcore/run.py -- <target.blend>`.
3. Verify: `verify_part.py -- <import.blend>` – all checks in section 6.
4. Render: `render_generic.py`, plus close-ups of anything unusual.
5. A failure is a finding: find the cause, adjust or add a rule here, rerun **all** tested parts, then record it in the journal.
