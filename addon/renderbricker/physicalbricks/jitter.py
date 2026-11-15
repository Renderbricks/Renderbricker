# SPDX-License-Identifier: GPL-3.0-or-later
"""Parts Jitter: every part a little moved and turned - sliders Translate and Rotate, each
with its own seed, for real LEGO models that are never built perfectly.

Every Mecabricks part of the scene gets a small random offset and turn in its delta transform
(delta_location, delta_rotation_euler); its own location and rotation stay as imported. The draw
of a part comes from its name and the seeds, so the same values give the same result again.
100 % Translate = up to 0.4 mm along each axis, 100 % Rotate = up to 2 degrees about each axis
(the strengths of the original add-on's Randomize).

Part of Physicalbricks (see __init__.py). The parts come from host.parts_of, the values from host.settings_of
(parts_translate, parts_rotate, their seeds, parts_mute)."""
import math
import random
import zlib

from . import host

MAX_SHIFT = 0.4                    # mm (the parts' own units) at 100 %
MAX_TURN = math.radians(2.0)       # at 100 %


def parts(scene):
    """Every part of every Mecabricks model in the scene (as the carrying add-on knows them)."""
    return host.parts_of(scene)


def apply(scene, settings):
    """Move and turn every part as the settings say (delta transforms); Mute puts them back."""
    on = 0.0 if settings.parts_mute else 1.0               # Mute: every part back on its place, settings stay
    shift = on * MAX_SHIFT * settings.parts_translate / 100
    turn = on * MAX_TURN * settings.parts_rotate / 100
    for ob in parts(scene):
        own = zlib.crc32(ob.name.encode())
        move = random.Random(own ^ (settings.parts_translate_seed * 7919))          # each with its own seed
        spin = random.Random(own ^ (settings.parts_rotate_seed * 104729 + 0x5bd1e995))
        location = tuple(move.uniform(-1.0, 1.0) * shift for _ in range(3))
        rotation = tuple(spin.uniform(-1.0, 1.0) * turn for _ in range(3))
        if tuple(ob.delta_location) != location:
            ob.delta_location = location
        if tuple(ob.delta_rotation_euler) != rotation:
            ob.delta_rotation_euler = rotation


def after_import(scene, state):
    """Hook (after an import): the new parts off their place as the panel says."""
    settings = host.settings_of(scene)
    if settings is not None:
        apply(scene, settings)
