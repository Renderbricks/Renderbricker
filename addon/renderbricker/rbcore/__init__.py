"""Renderbricker core: the crease rules and the conversion of Mecabricks imports, split by task.

    config    command line options and shared settings (levels, shading, method)
    creases   the crease rules (islands, corners, logos, T fans, seams)       - docs/RULES.md
    checks    checks of a result (broken import faces, folded sub-faces)
    copies    the subdivided copies of a part and the links that use them
    shading   geometric shading (variant B)
    memory    memory estimates and the number of Blender processes
    welding   the conversion of one part: weld, creases, repair, bake (process)
    cache     the cache file next to the scene
    workers   several Blender processes (shares, segments, merge)
    camera    the render camera
    engine    Cycles or EEVEE with the Renderbricks sky (EEVEE: sun lamp linked to the sky)
    headless  the run without a window (run.py)

The package reads and writes like one module: rbcore.NAME finds NAME in the module that holds it, and
rbcore.NAME = value sets it there (the add-on sets the levels and the shading before a run).
Without a window: blender -b scene.blend --python rbcore/run.py -- result.blend [options]
"""
import importlib, sys, types as _types

from . import config, creases, checks, copies, shading, memory, welding, cache, workers, camera, engine, headless, uvs

MODULES = (config, creases, checks, copies, shading, memory, welding, cache, workers, camera, engine, headless, uvs,)

def _owners(modules):
    """name -> module that defines it: everything a module binds itself (functions and classes defined
    there, its constants); names it imported (bpy, other modules, their functions) are left out."""
    out = {}
    for m in modules:
        short = m.__name__.rsplit(".", 1)[1]
        for name, value in vars(m).items():
            if name.startswith("__") or isinstance(value, _types.ModuleType):
                continue
            home = getattr(value, "__module__", None)
            if callable(value) and home is not None and home != m.__name__:
                continue
            out.setdefault(name, short)
    return out


OWNER = _owners(MODULES)


class _Package(_types.ModuleType):
    """Reads and writes of a name go to the module that holds it."""

    def __getattr__(self, name):
        m = OWNER.get(name)
        if m is None:
            raise AttributeError(f"rbcore has no {name!r}")
        return getattr(sys.modules[__name__ + "." + m], name)

    def __setattr__(self, name, value):
        m = OWNER.get(name) if name != "OWNER" else None
        if m is not None and m != name:
            setattr(sys.modules[__name__ + "." + m], name, value)
        else:
            super().__setattr__(name, value)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(OWNER))


sys.modules[__name__].__class__ = _Package


def reload_all():
    """Reload Scripts / re-enabling the add-on: every module fresh, in the same module objects."""
    for m in MODULES:
        importlib.reload(m)
    OWNER.clear()
    OWNER.update(_owners(MODULES))
