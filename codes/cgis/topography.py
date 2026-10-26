'''
Global topography with pyrocko.dataset.topo: SRTMGL3 (3 arcsec, ~90 m, land
between 60S and 60N) with automatic decimation for large regions, ETOPO1
(1 arcmin) for bathymetry or outside the SRTM coverage. Tiles are
downloaded by pyrocko on first use and cached (~/.pyrocko/topo).
'''

import math
import threading

import numpy as num

from . import geo

SRTM_NAMES = ('SRTMGL3', 'SRTMGL3_D2', 'SRTMGL3_D4', 'SRTMGL3_D8')
ETOPO_NAMES = ('ETOPO1', 'ETOPO1_D2', 'ETOPO1_D4', 'ETOPO1_D8')

_lock = threading.Lock()


class TopoError(Exception):
    pass


def _topo():
    from pyrocko.dataset import topo
    return topo


def _spacing(name):
    dem = _topo().dem(name)
    return 360. / (dem.nx - 1)


def _choose(names, region, target_spacing):
    '''Coarsest dataset not coarser than ``target_spacing`` (degrees).'''
    topo = _topo()
    cands = [n for n in names if topo.dem(n).covers(region)]
    if not cands:
        return None
    ok = [n for n in cands if _spacing(n) <= target_spacing]
    return ok[-1] if ok else cands[0]


def _normalize_region(region):
    west, east, south, north = [float(x) for x in region]
    south = max(-89.99, south)
    north = min(89.99, north)
    if not (east > west and north > south):
        raise TopoError('invalid region: %s' % (region,))
    if east - west > 360.:
        west, east = -180., 180.
    return west, east, south, north


def _get_tile(name, region):
    topo = _topo()
    try:
        t = topo.get(name, region)
    except Exception as e:
        raise TopoError('topografia %s non disponibile: %s' % (name, e))
    return t


def _bilinear(xs, ys, data, qx, qy):
    '''Bilinear interpolation on a regular ascending grid, NaN outside.'''
    qx = num.asarray(qx, dtype=float)
    qy = num.asarray(qy, dtype=float)
    nx, ny = len(xs), len(ys)
    out = num.full(qx.shape, num.nan)
    if nx < 2 or ny < 2:
        return out
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    fx = (qx - xs[0]) / dx
    fy = (qy - ys[0]) / dy
    inside = (fx >= 0) & (fx <= nx - 1) & (fy >= 0) & (fy <= ny - 1)
    if not inside.any():
        return out
    fx = fx[inside]
    fy = fy[inside]
    ix = num.clip(num.floor(fx).astype(int), 0, nx - 2)
    iy = num.clip(num.floor(fy).astype(int), 0, ny - 2)
    tx = fx - ix
    ty = fy - iy
    d = data.astype(float)
    v = (d[iy, ix] * (1 - tx) * (1 - ty) + d[iy, ix + 1] * tx * (1 - ty)
         + d[iy + 1, ix] * (1 - tx) * ty + d[iy + 1, ix + 1] * tx * ty)
    out[inside] = v
    return out


def grid(region, max_cells=1200, bathymetry=False):
    '''
    Topography grid covering ``region`` = (west, east, south, north).

    Returns ``(lons, lats, z, name)`` with ascending coordinates and z in
    metres (float32). Without ``bathymetry`` the sea is NaN.
    '''
    region = _normalize_region(region)
    west, east, south, north = region
    target = max(east - west, north - south) / max(50, int(max_cells))

    with _lock:
        land_name = _choose(SRTM_NAMES, region, target)
        if land_name is not None:
            t = _get_tile(land_name, region)
            if t is None:
                raise TopoError('no SRTM data for region %s' % (region,))
            xs, ys = t.x(), t.y()
            z = t.data.astype(num.float32)
            z[z < -1000.] = num.nan            # voids
            sea = z == 0.
            name = land_name
            if bathymetry:
                oname = _choose(ETOPO_NAMES, region, max(target, 1. / 60.))
                if oname is not None:
                    to = _get_tile(oname, region)
                    if to is not None:
                        gx, gy = num.meshgrid(xs, ys)
                        zo = _bilinear(to.x(), to.y(), to.data, gx[sea],
                                       gy[sea])
                        z[sea] = num.minimum(num.nan_to_num(zo, nan=0.), 0.)
                        name += '+' + oname
            else:
                z[sea] = num.nan
        else:
            oname = _choose(ETOPO_NAMES, region, target)
            if oname is None:
                raise TopoError('no topography covers region %s' % (region,))
            t = _get_tile(oname, region)
            if t is None:
                raise TopoError('no ETOPO1 data for region %s' % (region,))
            xs, ys = t.x(), t.y()
            z = t.data.astype(num.float32)
            if not bathymetry:
                z[z <= 0.] = num.nan
            name = oname

    return num.asarray(xs, float), num.asarray(ys, float), z, name


def profile(lat1, lon1, lat2, lon2, n=400, bathymetry=False):
    '''
    Elevation along the section A->B: ``(s_km, elev_m, source)``.
    Points over the sea are 0 m (or the ETOPO1 depth with bathymetry).
    '''
    length_km, azimuth = geo.section_frame(lat1, lon1, lat2, lon2)
    n = int(min(max(n, 20), 4000))
    s = num.linspace(0., length_km, n)
    lats, lons = geo.section_points(lat1, lon1, azimuth, s)
    pad = 0.02
    region = (lons.min() - pad, lons.max() + pad,
              lats.min() - pad, lats.max() + pad)
    step_deg = (length_km / n) / 111.19
    cells = max(region[1] - region[0], region[3] - region[2]) \
        / max(step_deg, 1e-6)
    xs, ys, z, name = grid(region, max_cells=min(cells, 6000),
                           bathymetry=bathymetry)
    if not bathymetry:
        z = num.where(num.isfinite(z), z, 0.)
    elev = _bilinear(xs, ys, z, lons, lats)
    return s, elev, name


def nice_max(z):
    '''Upper end of the topography colour scale.'''
    z = num.asarray(z, dtype=float)
    z = z[num.isfinite(z) & (z > 0)]
    if z.size == 0:
        return 100.
    top = float(num.percentile(z, 99.5))
    step = 10. ** math.floor(math.log10(max(top, 1.)))
    return max(100., math.ceil(top * 1.25 / step) * step)
