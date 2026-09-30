"""Package the add-on (system Python).

Usage:
  python build_addon.py
Zips the package addon/renderbricker (the UI modules and the core package rbcore) to
addon/dist/renderbricker-<version>.zip for Preferences > Add-ons > Install.
"""
import os, re, shutil, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).replace(os.sep, "/")
pkg = f"{ROOT}/addon/renderbricker"
ver = re.search(r'"version": \((\d+), (\d+), (\d+)\)', open(f"{pkg}/__init__.py", encoding="utf-8").read()).groups()
os.makedirs(f"{ROOT}/addon/dist", exist_ok=True)
out = f"{ROOT}/addon/dist/renderbricker-{'.'.join(ver)}.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for sub in ("", "rbcore/"):             # the UI modules and the core package
        for fn in sorted(os.listdir(f"{pkg}/{sub}")):
            if fn.endswith(".py") or (sub and fn.endswith(".json")):     # rbcore: sun lamp table
                z.write(f"{pkg}/{sub}{fn}", f"renderbricker/{sub}{fn}")
    setup = f"{pkg}/setup"                  # the Renderbricks setup scene (render settings, sky)
    if os.path.isdir(setup):
        for fn in sorted(os.listdir(setup)):
            if fn.endswith(".blend"):
                z.write(f"{setup}/{fn}", f"renderbricker/setup/{fn}")
    icons = f"{pkg}/icons"                  # the Renderbricks logo (panel header, About)
    if os.path.isdir(icons):
        for fn in sorted(os.listdir(icons)):
            if fn.endswith(".png"):
                z.write(f"{icons}/{fn}", f"renderbricker/icons/{fn}")
print("BUILT", out)
