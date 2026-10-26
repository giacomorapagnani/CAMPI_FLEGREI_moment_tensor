'''
Colour maps shared by the viewer (sent to the browser) and the figure
export (written as GMT CPT files), so that colours are identical in both.

Each map is a list of 17 equally spaced anchors (sampled from matplotlib),
linearly interpolated in RGB.
'''

import numpy as num

_ANCHORS = {
    'viridis': '440154 48186a 472d7b 424086 3b528b 33638d 2c728e 26828e 21918c 1fa088 28ae80 3fbc73 5ec962 84d44b addc30 d8e219 fde725',  # noqa
    'plasma': '0d0887 310597 4c02a1 6600a7 7e03a8 9511a1 aa2395 bc3587 cc4778 da5a6a e66c5c f0804e f89540 fdac33 fdc527 f8df25 f0f921',  # noqa
    'inferno': '000004 0b0724 210c4a 3d0965 57106e 71196e 8a226a a32c61 bc3754 d24644 e45a31 f1731d f98e09 fcac11 f9cb35 f2ea69 fcffa4',  # noqa
    'magma': '000004 0a0822 1d1147 36106b 51127c 6a1c81 832681 9c2e7f b73779 d0416f e75263 f56b5c fc8961 fea772 fec488 fde2a3 fcfdbf',  # noqa
    'cividis': '00224e 002e6a 1a386f 32436d 434e6c 535a6d 61656f 6f7073 7d7c78 8c8878 9b9476 aba072 bcae6c cdbb63 dec958 f0d846 fee838',  # noqa
    'turbo': '30123b 4040a2 466be3 4294ff 28bceb 18ddc2 32f298 6dfe62 a4fc3c cdec34 eecf3a fdac34 fb7e21 eb500e d02f05 a91601 7a0403',  # noqa
    'RdYlBu': 'a50026 c41e27 de402e f16640 f98e52 fdb567 fed485 feeca2 feffc0 ebf7e4 d1ecf4 b0dcea 8ec2dc 6da4cc 4f81ba 3d5ba7 313695',  # noqa
    'Spectral': '9e0142 c1274a dd4a4c f06744 f98e52 fdb567 fed481 feec9f ffffbe eff9a6 d6ee9b b1dfa3 86cfa5 5eb9a9 3d95b8 4471b2 5e4fa2',  # noqa
    'coolwarm': '3b4cc0 4e68d8 6282ea 779af7 8db0fe a3c2fe b9d0f9 ccd9ed dddcdc ecd3c5 f5c4ac f7b093 f4987a eb7d62 dd5f4b ca3b37 b40426',  # noqa
    'jet': '000080 0000c8 0000ff 0040ff 0080ff 00c0ff 16ffe1 49ffad 7dff7a b1ff46 e4ff13 ffd000 ff9400 ff5900 ff1e00 c40000 800000',  # noqa
    'gray': '000000 101010 202020 303030 404040 505050 606060 707070 808080 909090 a0a0a0 b0b0b0 c0c0c0 d0d0d0 e0e0e0 f0f0f0 ffffff',  # noqa
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
