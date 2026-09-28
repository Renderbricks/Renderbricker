# Renderbricker

Blender add-on "Renderbricker" (sidebar tab Renderbricker) plus batch pipeline: creases and baked subdivision copies for Mecabricks imports, the imported meshes stay untouched. Single user (Renderbricks), developed on Windows, supports Linux and macOS (platform tests in the private CI repo `Renderbricker-CI`), Blender 4.5 LTS or newer, developed with 5.2 LTS / 5.3. In production use – results are compared version by version.

## Stack and commands

- **Language:** Python (Blender's interpreter for everything under `addon/` and the Blender-side scripts; system Python 3.10+ for `build_addon.py`, `convert_models.py`, `run_suite.py`)
- **Build the add-on:** `python scripts/core/build_addon.py` – copies `scripts/core/mecabricks_subdiv.py` to `addon/renderbricker/core.py` and zips to `addon/dist/renderbricker-<version>.zip`
- **Batch conversion:** `python scripts/core/convert_models.py [--models ...] [--stale|--force|--verify-only]`
- **Rule test runs:** `python scripts/core/run_suite.py NN slug --parts <models>` → `_CLAUDE_/runs/runNN_slug/`
- **Blender path:** `RENDERBRICKER_BLENDER`, else `_CLAUDE_/blender_path.txt`, else `blender` on PATH

## Structure

```
addon/renderbricker/       add-on; core.py is generated – edit scripts/core/mecabricks_subdiv.py
scripts/core/              rules (mecabricks_subdiv.py), import, batch, verification
docs/RULES.md              rule set – every rule with its origin (part, run); version = RULES_VERSION
01_Sources … 06_User       local model data, not in git
_CLAUDE_/                  local R&D: journals, runs, logs, backups, tools (own local git history)
_dev/                      private test repo Renderbricker-CI (own git): platform tests Linux/macOS/Windows,
                           fixture + fingerprint reference; `python _dev/ci/run_all.py --blender <exe> --addon addon --work <dir>`
```

## Rules of work

- Never change geometry or topology of the imported meshes; only creases, attributes, copies.
- A finding from a model becomes a rule in `docs/RULES.md` (with origin) and is checked on all models (scan, comparison sheets with reference photos of the part) before release.
- Results and test files carry the add-on version (`_1-0-0`); older versions stay for comparison. Public numbering starts with the first release, 1.0.0 (maintainer 2026-09-28): until it is published, `bl_info` stays 1.0.0 and every further improvement is added to the CHANGELOG section `[1.0.0] – unreleased` and recorded in the journal; the release date is set at publishing. Results up to `_1-12-2` are from the internal numbering (1.0.0 started from internal 1.12.2, rules 3.2).
- The repository gets release-relevant information only (code, rules, README, CHANGELOG); the chronological R&D record (journals, runs, CHRONOLOGY.md) stays local in `_CLAUDE_`.
- UI features are tested in a real Blender window, not only headless (render thread, timers, undo).
- Journal every working day in `_CLAUDE_/JOURNAL_<date>.md`, commit the local R&D history in `_CLAUDE_`.
- `git push`, new releases, visibility changes: only after asking.

## Versioning and releases (same standard as Gaussian Render Capture, maintainer 2026-09-28)

- **Semantic Versioning from 1.0.0:** PATCH fixes, MINOR features, MAJOR changes that break existing scenes or settings. The version is `bl_info["version"]` in `addon/renderbricker/__init__.py`; a rules change in `scripts/core/mecabricks_subdiv.py` counts as an add-on change.
- **Collect changes:** commit locally, build and install into Blender 5.2 and 5.3, CHANGELOG entry under `## [Unreleased]`. The maintainer decides when a version is published.
- **Version bump only for changes to the add-on** (`addon/`, `scripts/core/mecabricks_subdiv.py`). README, docs, CHANGELOG, images never bump the version; they are pushed (after asking) without a release. Wording-only changes inside the add-on raise PATCH but are collected and published with the next functional release; such a version says "No functional changes – texts in the add-on and the documentation were revised in content and form."
- **CHANGELOG and release notes list functional changes only** (English, format `## [X.Y.Z] – YYYY-MM-DD`). Release notes = the CHANGELOG section + an install line.
- **Before a release:** candidate test – build the zip, install into 5.2 and 5.3, add-on test (Apply with cache, Save As / Move / Copy cache, reopen), window test for UI changes, batch on the test models. Then, after the maintainer's acceptance: push, tag `vX.Y.Z`, GitHub release.
- The internal detail of every change goes into the local R&D record (`_CLAUDE_/JOURNAL_<date>.md`, `CHRONOLOGY.md`), not into the repository.
- Commits here as `Renderbricks <330434884+Renderbricks@users.noreply.github.com>`.
- Name and legal texts (maintainer 2026-09-28): the add-on is "Renderbricker" (package `renderbricker`, operators keep the `mecsub.` prefix and the scene property `mecsub`, so converted scenes keep their settings); the panel shows the copyright line, the About sub-panel the trademark note (Renderbricks® is a registered word mark in Germany – ® only with that note), links to renderbricks.com, Facebook, YouTube and the LEGO disclaimer verbatim. The README links www.mecabricks.com.
- Render camera setup scene: `addon/renderbricker/setup/renderbricks_setup.blend` (90 KB: settings, world, camera only) is made from the maintainer's render scene with `blender -b --factory-startup --python scripts/core/make_setup_scene.py -- <Render.blend>` (source 2026-09-28: `06_User/Render.blend`); never copy a full render scene there.
- Screenshots, tutorial and documentation images are made with Blender 5.2.2 (the maintainer provides the reference scene in 5.2.2); compatibility stays 4.5 LTS or newer.
- Documentation layout (maintainer 2026-09-28): every picture is as wide as GitHub's text column – 948 CSS px, made at 2x = 1896 px (Blender UI scale 2); numbered markers are yellow and anti-aliased. Running text is justified with automatic hyphenation: after every edit of a doc run `python scripts/docs/typeset.py <doc.md>` (needs `pip install pyphen`; wraps the doc in `<div align="justify">` and sets soft hyphens, since GitHub strips CSS; `--strip` takes both out). Long unbreakable code (file names) goes into a code block, not into a justified line. `<…>` in text must be escaped or it vanishes as an HTML tag.
- The rules version (`RULES_VERSION`, docs/RULES.md) is internal: not in the panel, the start script or the CHANGELOG (maintainer 2026-09-28); journals and results metadata keep it.
