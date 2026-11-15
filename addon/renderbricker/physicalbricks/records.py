# SPDX-License-Identifier: GPL-3.0-or-later
"""Material records (architecture v2): one renderer-neutral record per colour id, read from physical/materials.json
(built by scripts/build_physical_records.py; fields described in physical/schema.json). The physical network
(materials/physical.py) takes every value from here; other renderers can read the same file.

Part of Physicalbricks (see __init__.py)."""
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'materials.json')
_cache = {}


def load():
    """All records by colour id (read once per session)."""
    if 'records' not in _cache:
        with open(PATH, encoding='utf-8') as f:
            data = json.load(f)
        _cache['records'] = {int(k): v for k, v in data['records'].items()}
        _cache['decoration'] = data.get('decoration', {})
        _cache['surface'] = data.get('surface', {})
        extra = os.environ.get('RB_PHYS_RECORDS_EXTRA')      # development: trial values of a photo-match run
        if extra and os.path.isfile(extra):
            with open(extra, encoding='utf-8') as f:
                for key, values in json.load(f).items():
                    if int(key) in _cache['records']:
                        _cache['records'][int(key)].update(values)
                    else:                                    # a colour not yet in the table: its whole trial record
                        _cache['records'][int(key)] = values
    return _cache['records']


def decoration():
    """Values of the physical decorations (ink, metallic ink, stickers)."""
    load()
    return _cache['decoration']


def surface():
    """Values of the parts' surface (relief of a part's own bump map)."""
    load()
    return _cache['surface']


def get(colour_id):
    """The record of a colour id; None when there is none."""
    return load().get(int(colour_id)) if colour_id is not None else None


def of(material, colour_id):
    """The record of a colour of this material: the table's, else the one the material carries itself (OWN_RECORD,
    JSON) - an importer stores it there for a colour Mecabricks does not have (LDraw colours), so the file switches
    the same way wherever it is opened."""
    record = get(colour_id)
    if record is not None or colour_id is None:
        return record
    from .constants import OWN_RECORD
    text = material.get(OWN_RECORD)
    own = json.loads(text) if text else None
    return own if own is not None and own.get('id') == int(colour_id) else None
