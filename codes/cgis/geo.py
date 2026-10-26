'''
Geometry of cross-sections with pyrocko.orthodrome.

Positions are expressed in the spherical azimuthal equidistant frame
centred on the section start A (azimuth from pyrocko ``azimuth_numpy``,
great-circle distance on the pyrocko earth radius), whose exact inverse is
pyrocko ``ne_to_latlon``. Section length, azimuth, along-profile distance
``s`` and signed distance ``d`` from the profile (positive on the right of
A->B) are therefore mutually consistent, and the viewer uses the same
formulas to draw the corridor.
'''

import math

import numpy as num

from pyrocko import orthodrome as od


class GeoError(Exception):
    pass


def _check_latlon(lat, lon):
    if not (math.isfinite(lat) and math.isfinite(lon)
            and -90. <= lat <= 90.):
        raise GeoError('coordinate non valide: %s, %s' % (lat, lon))


def latlon_to_ne(lat0, lon0, lats, lons):
    '''North/east offsets (m) from (lat0, lon0), inverse of ne_to_latlon.'''
    lats = num.asarray(lats, dtype=float)
    lons = num.asarray(lons, dtype=float)
    la0 = math.radians(lat0)
    la = num.radians(lats)
    dla = la - la0
    dlo = num.radians(lons - lon0)
    h = num.sin(dla / 2.)**2 + math.cos(la0) * num.cos(la) \
        * num.sin(dlo / 2.)**2
    dist = 2. * num.arcsin(num.sqrt(num.clip(h, 0., 1.))) * od.earthradius
    azi = num.radians(od.azimuth_numpy(
        num.full(lats.shape, float(lat0)), num.full(lats.shape, float(lon0)),
        lats, lons))
    return dist * num.cos(azi), dist * num.sin(azi)


def section_frame(lat1, lon1, lat2, lon2):
    '''Return (length_km, azimuth_deg) of the section A->B.'''
    for la, lo in ((lat1, lon1), (lat2, lon2)):
        _check_latlon(la, lo)
    n, e = latlon_to_ne(lat1, lon1, [lat2], [lon2])
    n, e = float(n[0]), float(e[0])
    length_km = math.hypot(n, e) / 1000.
    if not length_km > 0.:
        raise GeoError('gli estremi della sezione coincidono')
    azimuth = math.degrees(math.atan2(e, n)) % 360.
    return length_km, azimuth


def project(lat1, lon1, lat2, lon2, lats, lons):
    '''
    Project points on the section A->B.

    Returns ``(s_km, d_km, length_km, azimuth_deg)`` where ``s`` is the
    distance along the profile from A and ``d`` the signed distance from
    the profile line (positive to the right of A->B).
    '''
    length_km, azimuth = section_frame(lat1, lon1, lat2, lon2)
    lats = num.asarray(lats, dtype=float)
    lons = num.asarray(lons, dtype=float)
    if lats.size == 0:
        return num.zeros(0), num.zeros(0), length_km, azimuth
    n, e = latlon_to_ne(lat1, lon1, lats, lons)
    phi = math.radians(azimuth)
    c, s = math.cos(phi), math.sin(phi)
    s_km = (n * c + e * s) / 1000.
    d_km = (-n * s + e * c) / 1000.
    return s_km, d_km, length_km, azimuth


def section_points(lat1, lon1, azimuth_deg, s_km, d_km=0.):
    '''Inverse of :func:`project`: lat/lon of points given in (s, d).'''
    s_km = num.atleast_1d(num.asarray(s_km, dtype=float))
    d_km = num.broadcast_to(num.asarray(d_km, dtype=float), s_km.shape)
    phi = math.radians(azimuth_deg)
    c, s = math.cos(phi), math.sin(phi)
    north = (s_km * c - d_km * s) * 1000.
    east = (s_km * s + d_km * c) * 1000.
    lats, lons = od.ne_to_latlon(lat1, lon1, north, east)
    return num.asarray(lats, dtype=float), num.asarray(lons, dtype=float)


def corridor_polygon(lat1, lon1, lat2, lon2, width_km):
    '''Corners (lats, lons) of the section corridor of total width.'''
    length_km, azimuth = section_frame(lat1, lon1, lat2, lon2)
    h = 0.5 * float(width_km)
    return section_points(lat1, lon1, azimuth,
                          [0., length_km, length_km, 0., 0.],
                          [-h, -h, h, h, -h])


def nice_step(span, target=5):
    '''A "nice" tick step (1, 2, 2.5, 5 x 10^n) for ~target intervals.'''
    if not span > 0.:
        return 1.
    raw = span / target
    mag = 10. ** math.floor(math.log10(raw))
    for m in (1., 2., 2.5, 5., 10.):
        if raw <= m * mag:
            return m * mag
    return 10. * mag


def nice_floor(x):
    """Largest value 1, 2 or 5 x 10^n not larger than ``x``."""
    if not x > 0.:
        return 1.
    mag = 10. ** math.floor(math.log10(x))
    for m in (5., 2., 1.):
        if m * mag <= x:
            return m * mag
    return mag
