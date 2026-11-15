# SPDX-License-Identifier: GPL-3.0-or-later
"""What the add-on that carries this library tells it, filled in the add-on's register(). The library reads these and
nothing of the add-on itself.

    settings_of(scene)    the object holding the scene's Physicalbricks settings (material system, subsurface method,
                          yellowing, glow, parts jitter ...) or None
    parts_of(scene)       the objects that are Mecabricks parts (Parts Jitter moves them)
    AFTER_NETWORK         functions(material), called after the network of a material is built: an add-on adds nodes
                          of its own (marked NET, so that the way back to Mecabricks removes them). They run before
                          the network's layout (network.build_network's after): no outer frame yet, the unused
                          sockets not yet hidden, and their nodes placed with the network's in one go. A hook that
                          raises leaves the network without its layout; the file's next opening lays it
                          (switch.upgrade_on_load)
    SURFACE_BRANCH        None, or function(tree, normal, scale, new) -> node | None: an extra surface branch between
                          the bevel normal and the physical shaders (Renderbricks Dev's surface layers); its node has
                          the outputs Normal, Height and Roughness Factor, optionally Grease
    surface_active(settings)  whether the networks carry that branch (Dev: a layer slider is above 0)
    SETTINGS_VALUES       {settings property: Value node of rb_phys_surface_settings} the add-on writes beside the
                          library's own (surface.VALUES)
    node_height(node)     the drawn height of a node, for stacking the network's nodes
    eevee_glass()         None, or (thin: bool, caustics: bool, strength: float 0-1) - the add-on's Eevee glass
                          settings, which the library's Eevee shader follows (rb_phys_surface_settings)

    DEFAULTS              the library's own value of the six single hooks above
    snapshot()            what the add-on set: {hook: value} of every single hook that is not its default (identity),
                          copies of AFTER_NETWORK and SETTINGS_VALUES when not empty (registry.py keeps it in the entry)
    apply(values)         every hook back to its default, then values; AFTER_NETWORK and SETTINGS_VALUES change in place
                          (__init__.py re-exports the list, an add-on may hold the dictionary)

Several loaded copies: registry.py gives the acting copy's hooks the merged hooks of every host, and every other copy
its own snapshot - so the module's attributes are read at call time (host.settings_of(...)), never bound by import."""
from . import node_size


def _settings_of(scene):
    return getattr(scene, 'rb_phys', None)


def _parts_of(scene):
    return [ob for ob in scene.objects if ob.type == 'MESH'
            and any(s.material is not None and s.material.name.startswith('mb:') for s in ob.material_slots)]


settings_of = _settings_of
parts_of = _parts_of
AFTER_NETWORK = []
SURFACE_BRANCH = None
SETTINGS_VALUES = {}


def _no_surface(_settings):
    return False


surface_active = _no_surface


def _no_eevee_glass():
    return None


eevee_glass = _no_eevee_glass
node_height = node_size.node_height

DEFAULTS = {
    'settings_of': _settings_of,
    'parts_of': _parts_of,
    'SURFACE_BRANCH': None,
    'surface_active': _no_surface,
    'node_height': node_size.node_height,
    'eevee_glass': _no_eevee_glass,
}


def snapshot():
    """What the add-on set (see the module's text); the values themselves, the two collections copied."""
    hooks = globals()
    values = {name: hooks[name] for name, default in DEFAULTS.items() if hooks[name] is not default}
    if AFTER_NETWORK:
        values['AFTER_NETWORK'] = list(AFTER_NETWORK)
    if SETTINGS_VALUES:
        values['SETTINGS_VALUES'] = dict(SETTINGS_VALUES)
    return values


def apply(values):
    """Every hook back to its default, then values (a snapshot() or registry's merge of several)."""
    hooks = globals()
    for name, default in DEFAULTS.items():
        hooks[name] = values.get(name, default)
    AFTER_NETWORK[:] = list(values.get('AFTER_NETWORK', ()))
    merged = dict(values.get('SETTINGS_VALUES', {}))
    SETTINGS_VALUES.clear()
    SETTINGS_VALUES.update(merged)
