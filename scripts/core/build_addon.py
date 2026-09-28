"""Package the add-on (system Python).

Usage:
  python build_addon.py
Copies scripts/core/mecabricks_subdiv.py into addon/mecabricks_subdiv/core.py
(one source of truth for the rules) and zips the package to
addon/dist/mecabricks_subdiv-<version>.zip for Preferences > Add-ons > Install.
"""
import os, re, shutil, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).replace(os.sep, "/")
pkg = f"{ROOT}/addon/mecabricks_subdiv"
shutil.copyfile(f"{ROOT}/scripts/core/mecabricks_subdiv.py", f"{pkg}/core.py")
ver = re.search(r'"version": \((\d+), (\d+), (\d+)\)', open(f"{pkg}/__init__.py", encoding="utf-8").read()).groups()
os.makedirs(f"{ROOT}/addon/dist", exist_ok=True)
out = f"{ROOT}/addon/dist/mecabricks_subdiv-{'.'.join(ver)}.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for fn in ("__init__.py", "core.py"):
        z.write(f"{pkg}/{fn}", f"mecabricks_subdiv/{fn}")
print("BUILT", out)
