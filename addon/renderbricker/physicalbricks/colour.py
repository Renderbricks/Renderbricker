# SPDX-License-Identifier: GPL-3.0-or-later
"""Colours into the file's working colour space (Blender 5: Linear Rec.709, ACEScg or Linear Rec.2020).

The records hold linear Rec.709 colours (colour.rgb) and, where a colour lies beyond Rec.709, ACEScg values. A value
typed into a node is read in the file's working space, so it is converted first. The 3x3 matrices are derived here
from the standards' primaries and white points: Rec.709 / Rec.2020 (ITU-R BT.709, BT.2020, white D65) and ACES AP1
(SMPTE ST 2065-1 / ACEScg, white ≈ D60) with a Bradford chromatic adaptation D65 -> D60."""
import bpy

D65 = (0.3127, 0.3290)
ACES_WHITE = (0.32168, 0.33767)
REC709 = ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060))
REC2020 = ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046))
AP1 = ((0.713, 0.293), (0.165, 0.830), (0.128, 0.044))
BRADFORD = ((0.8951, 0.2664, -0.1614), (-0.7502, 1.7135, 0.0367), (0.0389, -0.0685, 1.0296))

_warned = set()


def _mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


def _inverse(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return (((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
            ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
            ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))


def _xyz(xy):
    x, y = xy
    return (x / y, 1.0, (1.0 - x - y) / y)


def _rgb_to_xyz(primaries, white):
    """RGB -> XYZ of a space from its primaries' and white's chromaticities (white Y = 1)."""
    columns = [_xyz(p) for p in primaries]
    p = tuple(tuple(columns[j][i] for j in range(3)) for i in range(3))
    s = _apply(_inverse(p), _xyz(white))
    return tuple(tuple(p[i][j] * s[j] for j in range(3)) for i in range(3))


def _bradford(source, target):
    """XYZ under white `source` -> XYZ under white `target`."""
    ls, lt = _apply(BRADFORD, _xyz(source)), _apply(BRADFORD, _xyz(target))
    scale = tuple(tuple((lt[i] / ls[i]) if i == j else 0.0 for j in range(3)) for i in range(3))
    return _mul(_inverse(BRADFORD), _mul(scale, BRADFORD))


_REC709_TO_XYZ = _rgb_to_xyz(REC709, D65)
# the sRGB -> XYZ matrix as IEC 61966-2-1 publishes it (four digits): the Rec.709 -> ACEScg matrix in common use (OCIO,
# colour-science „sRGB to ACEScg, Bradford“, 0.6131324224 …) is built from it, and the records' ACEScg values were
# converted with that matrix - so it is used here for ACEScg (the primaries give the same to 3.5e-5).
SRGB_TO_XYZ_IEC = ((0.4124, 0.3576, 0.1805), (0.2126, 0.7152, 0.0722), (0.0193, 0.1192, 0.9505))
FROM_REC709 = {
    'Linear Rec.709': None,
    'ACEScg': _mul(_inverse(_rgb_to_xyz(AP1, ACES_WHITE)), _mul(_bradford(D65, ACES_WHITE), SRGB_TO_XYZ_IEC)),
    'Linear Rec.2020': _mul(_inverse(_rgb_to_xyz(REC2020, D65)), _REC709_TO_XYZ),    # ITU-R BT.2087
}
ACESCG_TO_REC709 = _inverse(FROM_REC709['ACEScg'])


def working_space():
    """The file's working space; 'Linear Rec.709' where Blender has none (before 5.0)."""
    colorspace = getattr(bpy.data, 'colorspace', None)
    return getattr(colorspace, 'working_space', 'Linear Rec.709') if colorspace is not None else 'Linear Rec.709'


def from_rec709(rgb, space):
    """Linear Rec.709 rgb -> the same colour in `space`; an unknown space leaves it as it is (said once)."""
    rgb = [float(c) for c in rgb[:3]]
    if space not in FROM_REC709:
        if space not in _warned:
            _warned.add(space)
            print('Physicalbricks: unknown working colour space ' + str(space) + ' - colours stay Rec.709')
        return rgb
    m = FROM_REC709[space]
    return rgb if m is None else list(_apply(m, rgb))


def to_working(rgb):
    """A linear Rec.709 colour in the file's working space."""
    return from_rec709(rgb, working_space())


def from_acescg(rgb, space=None):
    """Linear ACEScg rgb -> the same colour in `space` (default: the file's working space). Outside Rec.709 a Rec.709 or
    Rec.2020 result can have a negative channel; the caller decides how to clamp."""
    space = space or working_space()
    if space == 'ACEScg':
        return [float(c) for c in rgb[:3]]
    return from_rec709(_apply(ACESCG_TO_REC709, [float(c) for c in rgb[:3]]), space)
