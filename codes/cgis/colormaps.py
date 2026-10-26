'''
Colour maps shared by the viewer (sent to the browser) and the figure
export (written as GMT CPT files), so that colours are identical in both.

Each map is a list of 17 equally spaced anchors (sampled from matplotlib,
or computed for the pastel maps), linearly interpolated in RGB.
'''

import numpy as num

_ANCHORS = {
    'viridis': '440154 48186a 472d7b 424086 3b528b 33638d 2c728e 26828e 21918c 1fa088 28ae80 3fbc73 5ec962 84d44b addc30 d8e219 fde725',  # noqa
    'cividis': '00224e 002e6a 1a386f 32436d 434e6c 535a6d 61656f 6f7073 7d7c78 8c8878 9b9476 aba072 bcae6c cdbb63 dec958 f0d846 fee838',  # noqa
    'RdYlBu': 'a50026 c41e27 de402e f16640 f98e52 fdb567 fed485 feeca2 feffc0 ebf7e4 d1ecf4 b0dcea 8ec2dc 6da4cc 4f81ba 3d5ba7 313695',  # noqa
    'coolwarm': '3b4cc0 4e68d8 6282ea 779af7 8db0fe a3c2fe b9d0f9 ccd9ed dddcdc ecd3c5 f5c4ac f7b093 f4987a eb7d62 dd5f4b ca3b37 b40426',  # noqa
    'gray': '000000 101010 202020 303030 404040 505050 606060 707070 808080 909090 a0a0a0 b0b0b0 c0c0c0 d0d0d0 e0e0e0 f0f0f0 ffffff',  # noqa
    # pastel: mono-colour (light -> deep) and bi-colour, interpolated in
    # CIELAB / CIE LCh
    'pastello_giallo': 'f6e8ba f2e2b2 eedda9 ebd7a1 e7d198 e3cc90 e0c688 dcc180 d9bb78 d5b56f d1b067 ceaa5f cba457 c79f4f c49947 c0943f bd8e37',  # noqa
    'pastello_blu_intenso': 'cfdef1 c5d7ed bbcfe8 b1c8e4 a7c1df 9db9db 93b2d6 89abd2 7ea4cd 749dc9 6995c5 5f8ec0 5387bc 4781b7 3a7ab3 2a73af 136caa',  # noqa
    'pastello_verde': 'd4eacf cbe3c7 c2ddc0 bad7b8 b1d0b1 a8caa9 9fc3a2 97bd9a 8eb793 86b08c 7daa85 75a47e 6c9e76 649770 5b9169 538b62 4a855b',  # noqa
    'pastello_rosso': 'f7d3cc f4cac3 f0c2b9 edb9b0 e9b1a7 e6a89e e2a095 de978c da8f83 d6867a d17e71 cd7569 c86d61 c46458 bf5c50 ba5348 b54a40',  # noqa
    'pastello_blu_corallo': '6a95c9 7895cb 8695cd 9494cd a194cc ad93ca b993c8 c493c4 cd93c0 d693bb de94b5 e496af ea98aa ee9aa4 f19d9e f2a198 f3a593',  # noqa
    'pastello_verde_pesca': '5aa79a 61aa97 69ad93 72af90 7bb28d 84b489 8eb686 98b884 a3b982 adbb80 b8bc7f c2bd7f cdbd80 d8be82 e2be85 ecbf89 f6bf8e',  # noqa
}

CMAPS = {
    name: [tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) for h in s.split()]
    for (name, s) in _ANCHORS.items()}

DEFAULT_DEPTH_CMAP = 'RdYlBu'
DEFAULT_TIME_CMAP = 'viridis'

# Topography palettes for exported maps: (low elevation, high elevation).
TOPO_PALETTES = {
    'gray': ((250, 250, 250), (70, 70, 70)),
    'brown': ((250, 240, 230), (160, 82, 45)),
    'green': ((240, 255, 240), (107, 142, 35)),
    'sand': ((255, 255, 240), (210, 180, 140)),
}


def anchors(name, reverse=False):
    if name not in CMAPS:
        raise ValueError('unknown colour map: %s' % name)
    a = num.array(CMAPS[name], dtype=float)
    return a[::-1] if reverse else a


def map_values(values, vmin, vmax, name, reverse=False):
    '''RGB (N, 3) uint8 colours for ``values``; NaN values come out gray.'''
    a = anchors(name, reverse)
    values = num.atleast_1d(num.asarray(values, dtype=float))
    finite = num.isfinite(values)
    span = vmax - vmin
    if not num.isfinite(span) or span <= 0.:
        x = num.full(values.shape, 0.5)
    else:
        x = num.clip((num.where(finite, values, vmin) - vmin) / span, 0., 1.)
    pos = x * (len(a) - 1)
    i0 = num.clip(num.floor(pos).astype(int), 0, len(a) - 2)
    f = (pos - i0)[:, None]
    rgb = a[i0] * (1. - f) + a[i0 + 1] * f
    rgb[~finite] = (160, 160, 160)
    return num.round(rgb).astype(num.uint8)


def hex_color(rgb):
    return '#%02x%02x%02x' % tuple(int(c) for c in rgb)


def write_cpt(path, name, vmin, vmax, reverse=False):
    '''
    Continuous GMT CPT with the same anchors as the viewer. Values outside
    the range take the end colours (B/F), as in the viewer.
    '''
    a = anchors(name, reverse)
    if not (num.isfinite(vmin) and num.isfinite(vmax)) or vmax <= vmin:
        vmin, vmax = (vmin - 0.5, vmin + 0.5) if num.isfinite(vmin) \
            else (0., 1.)
    n = len(a) - 1
    zs = vmin + (vmax - vmin) * num.arange(n + 1) / n

    def c(rgb):
        return '%d/%d/%d' % tuple(int(round(v)) for v in rgb)

    with open(path, 'w') as f:
        for i in range(n):
            f.write('%.10g %s %.10g %s\n' % (zs[i], c(a[i]), zs[i+1], c(a[i+1])))
        f.write('B %s\nF %s\nN 160/160/160\n' % (c(a[0]), c(a[-1])))
    return vmin, vmax


def write_topo_cpt(path, palette, zmax, water_rgb, zmin=None):
    '''
    Topography CPT: land from 0 to ``zmax`` with the chosen palette; when
    ``zmin`` < 0 (bathymetry) the sea goes from a darker tone of the water
    colour to the water colour at sea level.
    '''
    lo, hi = TOPO_PALETTES.get(palette, TOPO_PALETTES['gray'])
    lo = num.array(lo, float)
    hi = num.array(hi, float)
    water = num.array(water_rgb, float)
    zmax = max(float(zmax), 1.0)
    n = 8

    def c(rgb):
        return '%d/%d/%d' % tuple(int(round(v)) for v in rgb)

    with open(path, 'w') as f:
        if zmin is not None and zmin < 0.:
            deep = water * 0.55
            m = 6
            for i in range(m):
                z0 = zmin * (1. - i / m)
                z1 = zmin * (1. - (i + 1) / m)
                c0 = deep + (water - deep) * i / m
                c1 = deep + (water - deep) * (i + 1) / m
                f.write('%.6g %s %.6g %s\n' % (z0, c(c0), z1, c(c1)))
        for i in range(n):
            z0 = zmax * i / n
            z1 = zmax * (i + 1) / n
            c0 = lo + (hi - lo) * i / n
            c1 = lo + (hi - lo) * (i + 1) / n
            f.write('%.6g %s %.6g %s\n' % (z0, c(c0), z1, c(c1)))
        f.write('B %s\nF %s\nN %s\n' % (
            c(water * 0.55 if zmin is not None and zmin < 0 else lo),
            c(hi), c(water)))


def parse_hex(color, default=(128, 128, 128)):
    try:
        s = str(color).strip().lstrip('#')
        if len(s) == 3:
            s = ''.join(ch * 2 for ch in s)
        return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return default
