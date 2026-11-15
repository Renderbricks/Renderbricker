# SPDX-License-Identifier: GPL-3.0-or-later
"""One acting copy: several add-ons may carry a copy of this library (Renderbricks Dev, Renderbricker ...), and of all
copies loaded at once exactly one acts - it switches, does the work when a file opens, and runs with the hooks of all
hosts merged. The highest (VERSION, REVISION) acts; equal ones: the first registered.

    register(name)          the last step of a host's register(), after every hook of host.py is filled (a host changes
                            its hooks only between unregister() and register()); again while registered: unregister()
                            first, then the entry is rebuilt and the handler moves to the end of load_post; after
                            registry.py was reloaded in place, the old module's handler of this package goes first
    unregister()            in the host's unregister(): its handler goes, its host gets its own hooks back
    copies()                the entries on load_post, in handler order (= registration order)
    acting()                the package that acts, or None
    switch(mode)            the call a button makes -> (materials with a network, skipped); (0, 0) when no copy acts
    settings_of(scene)      the settings object a panel draws (the acting copy's host.settings_of)
    after_import(scene, state)  the acting copy's switch.after_import (an importer's hook)
    elect()                 the election among the copies of this protocol; register() and unregister() run it, and a
                            copy of a higher protocol calls it on the lower copies when it arrives and when it leaves

Where the copies are found: each registered copy appends its own persistent load_post handler (_on_load) that carries
its entry. Persistent handlers stay when a file is opened (bpy_app_handlers.cc BPY_app_handlers_reset keeps those with
_bpy_persistent); bpy.app.driver_namespace does not - Blender empties it on every file load, before load_post runs
(bpy_interface.cc BPY_python_reset, wm_files.cc wm_file_read_post). The work on load is done once per file: only the
handler of the last entry runs it, through the acting copy - so the load handlers every host appended before its
registry.register() have run first (Dev's settings migration before the upgrade). register() reads no file data: an
add-on's register() runs with bpy.data and bpy.context restricted (addon_utils.py enable(): RestrictBlend).

Protocol: the entry carries PROTOCOL. A copy that finds an entry of a higher protocol defers completely - no pointer,
no load work of its own, switch() and settings_of() forward to the copy that acts through the frozen calls below,
after_import() does nothing; a copy ignores entries of a lower protocol. The election runs only in the copy that calls
it and sees only its own protocol's copies: so a copy of a higher protocol, after it has appended its handler and
before it registers its pointer, calls registry.elect() of the lower copies (one live copy of each lower protocol is
enough) - they give the pointer up and every host of theirs gets its own hooks back; and after it has removed its
handler and its pointer, it calls elect() of the lower copies again - they elect among themselves (pointer, merged
hooks). The frozen cross-copy contract of protocol 1 (another copy may read or call these; a change to any of them
raises PROTOCOL):
    the handler             a persistent function on bpy.app.handlers.load_post with the attribute rb_phys_entry
    the entry's keys        name, version ((ints of VERSION), REVISION), package (the module), hooks (host.snapshot()
                            of the host: the names of host.DEFAULTS, AFTER_NETWORK, SETTINGS_VALUES), protocol,
                            pointer (True while that copy's settings.register_pointer() is in effect; set and cleared
                            by whichever copy calls it)
    live, stale             an entry is live while entry['package'] is sys.modules[entry['package'].__name__]; a
                            stale entry (an add-on gone without unregister()) takes no part, only its pointer goes
    the work on load        only the handler of the last live entry on load_post, of any protocol, does it: through
                            acting().registry._load_work() of the copy it finds acting
    the package's names     registry, host, switch, settings (plan 4, Task 2): another copy reaches them through
                            entry['package']
    registry.elect()        see above
    registry._load_work()   the work when a file opens
    settings.register_pointer() / settings.unregister_pointer()   scene.rb_phys of the acting copy (plan 4, Task 2)
    switch.switch_to(mode)  host.settings_of(scene)
    host.apply(values)      the election gives copies of the same protocol their hooks through it
    host-facing calls a protocol-1 copy keeps   a host calls them on the acting copy's package (Renderbricks Dev:
                            lib() in fx/settings.py and its hook functions in fx/__init__.py), with these signatures:
                            set_material_system(mode, surface=None, settings=None), set_subsurface_method(method),
                            apply_afterglow(), apply_surface(settings=None), yellowing_viewport(),
                            surface_active(settings=None), built_with_surface(), jitter.apply(scene, settings),
                            jitter.after_import(scene, state), yellowing_default(scene, state=None, *, nicolas=False),
                            apply_eevee_glass(), place(tree); and switch.after_import(scene, state), which this
                            module's after_import() calls on the acting copy. A copy of protocol 2 needs its hosts
                            updated in the same release.

Part of Physicalbricks (see __init__.py)."""
import re
import sys

import bpy

from . import host, settings
from . import switch as switching

PROTOCOL = 1


def _package():
    return sys.modules[__package__]


def _numbers(version):
    return tuple(int(part) for part in re.findall(r'\d+', str(version)))


def _entries():
    """Every entry on load_post, stale ones too."""
    found = []
    for handler in bpy.app.handlers.load_post:
        entry = getattr(handler, 'rb_phys_entry', None)
        if isinstance(entry, dict):
            found.append(entry)
    return found


def _live(entry):
    package = entry.get('package')
    return package is not None and sys.modules.get(getattr(package, '__name__', '')) is package


def copies():
    """The entries found on load_post, in handler order; an entry whose package is no longer the module in sys.modules
    (an add-on that went without unregistering) is left out."""
    return [entry for entry in _entries() if _live(entry)]


def _candidates(entries):
    """The entries the election is held among: those of the highest protocol, when it is not below this copy's."""
    top = max((entry.get('protocol', 0) for entry in entries), default=0)
    return [entry for entry in entries if entry.get('protocol', 0) == top] if top >= PROTOCOL else []


def _elected(entries):
    best = None
    for entry in _candidates(entries):
        if best is None or entry['version'] > best['version']:      # equal: the first registered stays
            best = entry
    return best


def acting():
    """The package of the copy that acts: the highest (VERSION, REVISION), equal ones the first registered."""
    best = _elected(copies())
    return None if best is None else best['package']


def _merged(entries):
    """The hooks of several hosts in one: AFTER_NETWORK joined in registration order (each function once),
    SETTINGS_VALUES united, every single hook the first registered host's value that it set."""
    merged, after, values = {}, [], {}
    for entry in entries:
        for name, value in entry['hooks'].items():
            if name == 'AFTER_NETWORK':
                for function in value:
                    if function not in after:
                        after.append(function)
            elif name == 'SETTINGS_VALUES':
                for key, node in value.items():
                    values.setdefault(key, node)
            else:
                merged.setdefault(name, value)
    if after:
        merged['AFTER_NETWORK'] = after
    if values:
        merged['SETTINGS_VALUES'] = values
    return merged


def _pointer(package, call):
    """settings.register_pointer / unregister_pointer of a copy (scene.rb_phys, settings.py); a copy without a
    settings module (one built before plan 4, Task 2) has nothing to register."""
    function = getattr(getattr(package, 'settings', None), call, None) if package is not None else None
    if function is not None:
        function()


def elect():
    """The election among the copies of this protocol, from the entries alone (no state of its own, so any copy may
    call it at any time - see the module's text). The copy that acts gets the merged hooks when several take part,
    every other copy of this protocol its own snapshot; when a copy of a higher protocol acts, every host of this
    protocol its own. The pointer: every entry of this protocol that holds it (entry['pointer']) and does not act -
    a stale one too - gives it up first, then the acting copy registers it, when it is of this protocol."""
    entries = copies()
    best = _elected(entries)
    group = _candidates(entries)
    merged = _merged(group) if len(group) > 1 else None
    for entry in entries:
        if entry.get('protocol') == PROTOCOL:
            entry['package'].host.apply(merged if merged is not None and entry is best else entry['hooks'])
    mine = best if best is not None and best.get('protocol') == PROTOCOL else None
    for entry in _entries():
        if entry.get('pointer') and entry is not mine and entry.get('protocol') == PROTOCOL:
            _pointer(entry['package'], 'unregister_pointer')
            entry['pointer'] = False
    if mine is not None and not mine.get('pointer'):
        _pointer(mine['package'], 'register_pointer')
        mine['pointer'] = True


def _drop_ghosts():
    """The handlers an earlier run of this module left on load_post for this same package (registry.py reloaded in
    place with importlib.reload: a new _on_load, the old one still there with a live entry): each goes as unregister()
    takes its own - the handler, its pointer when it held it, its host's own hooks back. Only this copy's own
    (entry['package'] is this package); another copy's handler, stale or live, stays."""
    package = _package()
    for handler in list(bpy.app.handlers.load_post):
        entry = getattr(handler, 'rb_phys_entry', None)
        if handler is _on_load or not isinstance(entry, dict) or entry.get('package') is not package:
            continue
        bpy.app.handlers.load_post.remove(handler)
        if entry.get('pointer'):
            _pointer(package, 'unregister_pointer')
            entry['pointer'] = False
        host.apply(entry['hooks'])
        del handler.rb_phys_entry


def register(name):
    """This copy takes part: its entry on its load_post handler, then the election. First the handlers an earlier run
    of this module left for this package go (_drop_ghosts). Registered already: unregister() first (its host gets its
    own hooks back), so the entry is rebuilt from them and the handler moves to the end of load_post. Reads no file
    data."""
    _drop_ghosts()
    if _on_load in bpy.app.handlers.load_post or hasattr(_on_load, 'rb_phys_entry'):
        unregister()
    package = _package()
    _on_load.rb_phys_entry = {'name': name, 'version': (_numbers(package.VERSION), package.REVISION),
                              'package': package, 'hooks': host.snapshot(), 'protocol': PROTOCOL, 'pointer': False}
    bpy.app.handlers.load_post.append(_on_load)
    elect()


def unregister():
    """This copy leaves: its handler goes, its pointer goes when it held it, its host gets its own hooks back (while it
    acted for several copies it held the merged ones - a host registering again would take them for its own), the rest
    elect."""
    while _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    entry = getattr(_on_load, 'rb_phys_entry', None)
    if entry is not None:
        if entry.get('pointer'):
            _pointer(entry['package'], 'unregister_pointer')
            entry['pointer'] = False
        host.apply(entry['hooks'])
        del _on_load.rb_phys_entry
    elect()


def _deferred(package):
    best = _elected(copies())
    return package is None or best is None or best.get('protocol') != PROTOCOL


def switch(mode):
    """mode 'PHYSICAL' or 'MECABRICKS' through the acting copy -> (materials with a network, skipped); (0, 0) when no
    copy acts."""
    package = acting()
    return (0, 0) if package is None else package.switch.switch_to(mode)


def settings_of(scene):
    """The settings object of the scene as the acting copy's host gives it (what a panel draws), or None."""
    package = acting()
    return None if package is None else package.host.settings_of(scene)


def after_import(scene, state):
    """The acting copy's switch.after_import (an importer's hook); None when a copy of a higher protocol acts."""
    package = acting()
    return None if _deferred(package) else package.switch.after_import(scene, state)


def _load_work():
    """The work when a file opens, done by the acting copy: the old prefix first (a file of group version 37 or older
    still carries mb_phys_net and would read as Mecabricks), the mode once, every scene's settings from the file's data
    (settings.from_file: the upgrade reads material_system from them, and a panel shows the file's state - Review
    Focus 3), then the upgrade (an attribute of switch, so a test can count it). An error in from_file for one scene
    is printed in one line naming the scene, and the next scene and the upgrade still run. Below Blender 5.0 nothing in
    it switches: from_file returns at once there, upgrade_on_load stops before its switch (constants.AVAILABLE)."""
    switching.rename_old_prefix()
    mode = switching.current_mode()
    for scene in bpy.data.scenes:
        try:
            settings.from_file(scene, mode)
        except Exception as exc:  # noqa: BLE001 one scene's settings must not stop the others and the upgrade
            print(f"Physicalbricks: the settings of scene {scene.name!r} not read from the file - "
                  f"{type(exc).__name__}: {exc}", flush=True)
    switching.upgrade_on_load()


@bpy.app.handlers.persistent
def _on_load(*_args):
    """This copy's load_post handler; it carries the entry (rb_phys_entry). Only the last entry's handler does the
    work, through the acting copy."""
    entries = copies()
    if not entries or entries[-1] is not getattr(_on_load, 'rb_phys_entry', None):
        return
    package = acting()
    if package is not None:
        package.registry._load_work()
