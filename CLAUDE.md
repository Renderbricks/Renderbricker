# Renderbricker

Blender add-on "Renderbricks: Mecabricks Subdiv" plus batch pipeline: creases and baked subdivision copies for Mecabricks imports, the imported meshes stay untouched. Single user (Renderbricks), Windows, Blender 5.2 LTS / 5.3. In production use – results are compared version by version.

## Stack and commands

- **Language:** Python (Blender's interpreter for everything under `addon/` and the Blender-side scripts; system Python 3.10+ for `build_addon.py`, `convert_models.py`, `run_suite.py`)
- **Build the add-on:** `python scripts/core/build_addon.py` – copies `scripts/core/mecabricks_subdiv.py` to `addon/mecabricks_subdiv/core.py` and zips to `addon/dist/`
- **Batch conversion:** `python scripts/core/convert_models.py [--models ...] [--stale|--force|--verify-only]`
- **Rule test runs:** `python scripts/core/run_suite.py NN slug --parts <models>` → `_CLAUDE_/runs/runNN_slug/`
- **Blender path:** `RENDERBRICKER_BLENDER`, else `_CLAUDE_/blender_path.txt`, else `blender` on PATH

## Structure

```
addon/mecabricks_subdiv/   add-on; core.py is generated – edit scripts/core/mecabricks_subdiv.py
scripts/core/              rules (mecabricks_subdiv.py), import, batch, verification
docs/RULES.md              rule set – every rule with its origin (part, run); version = RULES_VERSION
01_Sources … 06_User       local model data, not in git
_CLAUDE_/                  local R&D: journals, runs, logs, backups, tools (own local git history)
```

## Rules of work

- Never change geometry or topology of the imported meshes; only creases, attributes, copies.
- A finding from a model becomes a rule in `docs/RULES.md` (with origin) and is checked on all models (scan, comparison sheets with reference photos of the part) before release.
- Results and test files carry the add-on version (`_1-12-2`); older versions stay for comparison.
- UI features are tested in a real Blender window, not only headless (render thread, timers, undo).
- Journal every working day in `_CLAUDE_/JOURNAL_<date>.md`, commit the local R&D history in `_CLAUDE_`.
- `git push`, new releases, visibility changes: only after asking.
- Commits here as `Renderbricks <330434884+Renderbricks@users.noreply.github.com>`.
