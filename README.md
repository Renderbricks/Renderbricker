# Renderbricker

Smooth, render-ready LEGO® parts from Mecabricks imports – without touching the imported meshes.

Renderbricker is a Blender add-on and a batch pipeline for scenes built in [Mecabricks](https://www.mecabricks.com) by Nicolas 'Scrubs' Jarraud and imported with his Mecabricks Lite or Advanced add-on. Each part mesh is processed once: seams are welded in a temporary copy, edges get creases by a tested rule set, and the subdivided result is baked into a copy that every link of that part uses. The original import stays unchanged, so the conversion can always be undone.

## Features

- **Rule-based creases** – sharp where the real part is sharp, round where it is round; the rules are documented with the part and finding they come from in [docs/RULES.md](docs/RULES.md).
- **One copy per part** – thousands of links share one subdivided mesh; viewport and render level can differ (the render level is switched in for F12 and back afterwards).
- **Cache file** – the copies can live in `<scene>_rbcache.blend` next to the scene, linked as library overrides, so the scene file stays small; move or copy the cache with the scene, switch it off to take the copies back into the scene.
- **Several Blender processes** – Apply and the headless conversion share the parts among several Blenders in the background; how many depends on the processor and the free memory.
- **Checks** – the original is verified untouched, folds and seam gaps are measured after every conversion.

## Requirements

- Blender 4.5 LTS or newer (developed with 5.2 LTS and 5.3)
- Windows, Linux or macOS
- Scenes from [www.mecabricks.com](https://www.mecabricks.com), imported with the Mecabricks Lite or Advanced add-on

## Installation

1. Build the package: `python scripts/core/build_addon.py` → `addon/dist/renderbricker-<version>.zip`
2. Blender: Edit → Preferences → Add-ons → Install from Disk → choose the zip, enable "Renderbricker"
3. Panel: 3D Viewport → Sidebar (N) → Renderbricker

## Documentation

- [Quick start](docs/QUICKSTART.md) – the workflow in seven steps
- [Tutorial](docs/TUTORIAL.md) – every step with pictures
- [Reference](docs/REFERENCE.md) – all settings and buttons
- [Troubleshooting](docs/TROUBLESHOOTING.md) · [Known issues](docs/KNOWN_ISSUES.md) · [Glossary](docs/GLOSSARY.md)
- [Rules](docs/RULES.md) – the rule set with the origin of every rule

## Usage

- **Apply** converts all mesh objects (or the selection). Choose viewport and render level first; with "Cache file next to the scene" the scene is saved automatically once the cache is written.
- **Subdivision: ON / OFF** switches every link between the subdivided copy and the original.
- **F12 / Ctrl+F12** render with the render level.
- **Convert headless** runs the conversion without the window (faster for large scenes).

Batch conversion of many models (system Python):

```
python scripts/core/convert_models.py [--models NAME ...] [--stale] [--force] [--jobs N]
```

It expects `01_Sources/<model>.zmbx` beside the code, writes `02_Imports/` and `03_Results/<model>_subdiv_A_mecabricks_<version>.blend` and checks every result. Blender is taken from `RENDERBRICKER_BLENDER`, a path in `_CLAUDE_/blender_path.txt` or `blender` on the PATH; `--blender PATH` overrides all.

## Repository layout

```
addon/renderbricker/       Blender add-on (core.py is a copy of scripts/core/mecabricks_subdiv.py)
scripts/core/              rule set (mecabricks_subdiv.py), batch conversion, import, verification
docs/RULES.md              the rule set with the origin of every rule
```

Model files, results and the development journal are kept locally beside the code and are not part of the repository.

## Author

© 2026 Renderbricks® – Prof. Michael Klein, who has worked in CGI since 1987. Developed with Claude (Anthropic).

[www.renderbricks.com](https://www.renderbricks.com) · [Facebook](https://www.facebook.com/renderbricks) · [YouTube](https://www.youtube.com/@renderbricks)

Renderbricks® is a registered trademark in Germany.

## Credits

Renderbricker is built on [Mecabricks](https://www.mecabricks.com) and its Blender add-ons Mecabricks
Lite and Mecabricks Advanced, all developed by **Nicolas 'Scrubs' Jarraud**.

The example scene of the [Tutorial](docs/TUTORIAL.md) is the
[Italian Riviera](https://www.mecabricks.com/en/models/qxv4E8VdadJ) by Nicolas 'Scrubs' Jarraud,
used with his kind permission – thank you for the model.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).

Renderbricks is about rendering digital LEGO®. LEGO is a trademark of the LEGO Group of companies which does not sponsor, authorize or endorse this site.

Mecabricks is a trademark of its owner, who does not sponsor, authorize or endorse this project.
