"""Which importer is there (UPDATES #34): the add-on that registered File > Import > Mecabricks (.zmbx).

Mecabricks Advanced, Mecabricks Lite and the Renderbricks fork of both all register the operator
import_mecabricks.zmbx, so the operator alone does not say which one will import. This module names it - for the
line under the import button and for the log file. It is information only: Renderbricker treats every import the same.
With two of them enabled Blender keeps the operator of the one registered last; the line then warns."""
import sys
from collections import namedtuple
import bpy

IMPORT_OPERATOR = "import_mecabricks.zmbx"
IMPORT_CLASS = "IMPORT_MECABRICKS_OT_zmbx"      # the name Blender gives the registered operator class
FORK = "Renderbricks"                           # the fork says so in its name or author line, or by FORK_MARKER
FORK_MARKER = "RENDERBRICKS"                    # attribute of the fork's package (not set by the fork yet)

Importer = namedtuple("Importer", "module name version fork label")


def _describe(module_name):
    """The Importer of an enabled add-on module, from its bl_info."""
    mod = sys.modules.get(module_name)
    info = getattr(mod, "bl_info", None) or {}
    name = str(info.get("name") or module_name)
    version = ".".join(str(v) for v in info.get("version", ()))
    fork = bool(getattr(mod, FORK_MARKER, None)) or FORK in name or FORK in str(info.get("author", ""))
    label = " ".join(x for x in (name, version) if x) + (f" ({FORK})" if fork and FORK not in name else "")
    return Importer(module_name, name, version, fork, label)


def _registers_import(module_name):
    """Whether an add-on defines the import operator - in its package or one of its modules."""
    for key, mod in list(sys.modules.items()):
        if mod is None or not (key == module_name or key.startswith(module_name + ".")):
            continue
        for value in list(vars(mod).values()):
            if isinstance(value, type) and getattr(value, "bl_idname", None) == IMPORT_OPERATOR \
                    and getattr(value, "__module__", "") == key:
                return True
    return False


def _addons():
    """The enabled add-on modules, longest name first (bl_ext.user_default.x before a package named bl_ext)."""
    return sorted(bpy.context.preferences.addons.keys(), key=len, reverse=True)


def enabled_importers():
    """Every enabled add-on that registers the import operator, by name."""
    return sorted((_describe(a) for a in _addons() if _registers_import(a)), key=lambda i: i.label)


def active_importer():
    """The importer whose operator is registered now - the one that imports. None without any."""
    cls = getattr(bpy.types, IMPORT_CLASS, None)
    home = getattr(cls, "__module__", None)
    if not home:
        return None
    for a in _addons():
        if home == a or home.startswith(a + "."):
            return _describe(a)
    return _describe(home.split(".")[0])            # registered by something that is not an add-on (a script)


_LINE = [None, None]        # what was enabled when the line was made, the line (the panel asks at every redraw)


def importer_line():
    """(text, warning) for the panel and the log - None when no importer is enabled."""
    key = (tuple(sorted(bpy.context.preferences.addons.keys())), getattr(bpy.types, IMPORT_CLASS, None))
    if _LINE[0] != key:
        _LINE[0], _LINE[1] = key, _make_line()
    return _LINE[1]


def _make_line():
    now = active_importer()
    if now is None:
        return None
    others = [i for i in enabled_importers() if i.module != now.module]
    if others:
        return (f"Two importers enabled: {now.label} imports, not {', '.join(i.label for i in others)}", True)
    return f"Importer: {now.label}", False


def importer_log():
    """The same as one line of the log file."""
    now = active_importer()
    if now is None:
        return "importer: none enabled"
    others = [i.label for i in enabled_importers() if i.module != now.module]
    return f"importer: {now.label}" + (f" (also enabled, not importing: {', '.join(others)})" if others else "")
