#!/usr/bin/env python3
"""
download_catalog_waveforms_station_xml.py
--------------------------------------
Interactive FDSN downloader: catalog, station metadata, waveforms.

  1. Reads (or creates) CAT/config_cat/config.yaml
  2. Gets events and/or stations — from FDSN or from local files — as the
     mode requires: event | continuous | catalog | stations (see config)
  3. Shows an interactive preview map (folium → fallback: pygmt)
  4. After confirmation (and, for output names already on disk, the choice
     overwrite / another name) saves catalog + station metadata — local
     sources are never re-saved — and then downloads the waveforms

Output layout
─────────────
  CAT/
    config_cat/config.yaml          ← configuration (created if absent)
    {catalog_name}.xml              ← QuakeML catalog
    {catalog_name}.txt              ← human-readable table
    {catalog_name}.pf               ← Pyrocko basic format
  META_DATA/
    {station_file_name}.xml         ← StationXML with instrument response
    {station_file_name}/
      {station_file_name}_{NET}_{STA}.xml    ← one StationXML per station
  DATA/
    {event_label}_yyyy_mm_dd_hh_mm_ss/
      {event_label}_yyyy_mm_dd_hh_mm_ss_{NET}_{STA}.mseed
    CONTINUOUS/
      {event_label}_yyyy_mm_dd_{NET}_{STA}.mseed   ← continuous mode

Dependencies: obspy, pyrocko, pyyaml, folium (or pygmt as fallback)
"""

# ── Standard library ──────────────────────────────────────────────────────────
import os
import re
import sys
import glob
import json
import math
import time
import argparse
import platform
import threading
import subprocess
import webbrowser
import tempfile
import warnings
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Third-party ───────────────────────────────────────────────────────────────
import yaml
from pyrocko import util, model
from obspy.clients.fdsn.client import Client
from obspy.clients.fdsn.header import (
    FDSNException, FDSNNoDataException, FDSNTimeoutException,
    FDSNInternalServerException, FDSNBadGatewayException,
    FDSNServiceUnavailableException, FDSNTooManyRequestsException)
from obspy import UTCDateTime, Stream
from obspy.core.event import Catalog

# Harmless obspy notice printed for every equipment / response identifier
# that is not a URI (INGV StationXML has many: dozens of lines per query)
warnings.filterwarnings('ignore', category=UserWarning,
                        message='Given string seems to not be a valid URI')


# ═════════════════════════════════════════════════════════════════════════════
# PATHS  (script lives in codes/; project root is one level up)
# ═════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR   = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
CONFIG_DIR = os.path.join(WORK_DIR, 'CAT', 'config_cat')
CAT_DIR    = os.path.join(WORK_DIR, 'CAT')
META_DIR    = os.path.join(WORK_DIR, 'META_DATA')
DATA_DIR    = os.path.join(WORK_DIR, 'DATA')


# ═════════════════════════════════════════════════════════════════════════════
# 1 ─ CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════

# Written as a raw string so that all comments are preserved in the file.
DEFAULT_CONFIG = """\
# ══════════════════════════════════════════════════════════════════════════════
#  FDSN DOWNLOAD CONFIGURATION
#  Edit this file, then run  download_catalog_waveforms_station_xml.py
# ══════════════════════════════════════════════════════════════════════════════
#
#  The script has four modes (→ download_mode):
#    "event"      : catalog + station metadata + one waveform excerpt per event
#    "continuous" : station metadata + continuous waveforms between tmin & tmax
#    "catalog"    : the event catalog only
#    "stations"   : the station metadata only
#
#  If an output name (catalog_name, station_file_name) is already used on
#  disk, the script asks whether to overwrite it or to use another name,
#  before anything is saved or downloaded.
#
#  Events and stations can each come from FDSN *or* from LOCAL files already
#  on disk (→ LOCAL SOURCES below).  Whatever is loaded from a local file is
#  used as-is and is NOT re-saved by the script.

# ── Download mode ─────────────────────────────────────────────────────────────

# "event"      → catalog + stations + one waveform excerpt per event
#                  Files: DATA/<event_name>/<event_name>_NET_STA.mseed
# "continuous" → stations + continuous stream for every station, tmin → tmax
#                  Files: DATA/CONTINUOUS/<event_label>_yyyy_mm_dd_NET_STA.mseed
# "catalog"    → the event catalog only (no stations, no waveforms)
#                  Files: CAT/<catalog_name>.xml .txt .pf
# "stations"   → the station metadata only (no events, no waveforms); with
#                the azimuthal selection on, also a way to thin out a local
#                StationXML (existing_stations_xml) without any download
#                  Files: META_DATA/<station_file_name>...  (see below)
# Typical large-event workflow: "stations" (ring + azimuthal selection, check
# the map) and "catalog" first, then "event" with existing_stations_xml and
# existing_catalog_pf pointing to those files: only waveforms are downloaded.
download_mode: "event"

# ── LOCAL SOURCES (both optional) ─────────────────────────────────────────────
#
#   existing_catalog_pf │ existing_stations_xml │ behaviour
#   ────────────────────┼───────────────────────┼─────────────────────────────
#   null                │ null                  │ all from FDSN, all saved
#   set                 │ null                  │ events from file, stations FDSN
#   null                │ set                   │ events from FDSN, stations file
#   set                 │ set                   │ only waveforms use the network

# Event catalog in Pyrocko .pf format (e.g. one generated by this script).
# Only used in "event" mode; ignored in "continuous" mode.
# The event NAMES stored in the file become the DATA/ folder names, so
# waveforms downloaded from different servers/networks accumulate in the
# SAME event folders (files are named ..._NET_STA.mseed → no clashes).
# The event search area / filters below are NOT applied to a local catalog:
# the file is used exactly as it is.
#   null        → download the catalog from FDSN (and save it in CAT/)
#   "file.pf"   → bare filename: looked up inside CAT/
#   "/abs/path" → absolute path used as-is
existing_catalog_pf: null      # e.g.  "my_catalog.pf"  or  null

# Station metadata in StationXML format.
# When set, the station search area and the network/station selection below
# are IGNORED (the inventory is used as stored in the file) and the file is
# not re-saved to META_DATA/.  NOTE: channel and location below are still
# applied to every waveform request, and the azimuthal selection (if on)
# still thins out the stations of the file.
#   null        → query stations from FDSN (and save StationXML in META_DATA/)
#   "file.xml"  → bare filename: looked up inside META_DATA/
#   "/abs/path" → absolute path used as-is
existing_stations_xml: null    # e.g.  "stations_flegrei_INGV_final.xml"  or  null

# ── Output naming ─────────────────────────────────────────────────────────────

# Base name for the catalog files written to CAT/ (no extension).
# Used only when the catalog comes from FDSN (existing_catalog_pf: null).
#   Produces:  CAT/<catalog_name>.xml   .txt   .pf
catalog_name: "my_catalog"

# Short label used as prefix for event names and continuous filenames.
#   event mode      : DATA/<event_label>_yyyy_mm_dd_hh_mm_ss/   (FDSN catalog;
#                     a local catalog keeps the names stored in the file)
#   continuous mode : DATA/CONTINUOUS/<event_label>_yyyy_mm_dd_NET_STA.mseed
event_label: "EV"

# Base name for the station metadata written to META_DATA/ (no extension).
# Used only when the stations come from FDSN (existing_stations_xml: null).
#   Produces:  META_DATA/<station_file_name>.xml            (full inventory)
#              META_DATA/<station_file_name>/
#                  <station_file_name>_NET_STA.xml          (one per station)
# With the azimuthal selection on, you get one file with ALL the stations
# and one with the SELECTED stations only:
#   stations from FDSN:
#              META_DATA/<station_file_name>_all.xml        (all candidates)
#              META_DATA/<station_file_name>.xml            (selected) + the
#              per-station folder (selected)
#   stations from a local file (existing_stations_xml):
#              your local file                              (all — not copied)
#              META_DATA/<station_file_name>.xml            (selected)
#   in both cases:
#              META_DATA/<station_file_name>_selection.txt  (selection report)
station_file_name: "stations"

# ── FDSN server ───────────────────────────────────────────────────────────────

# Data centre for STATIONS and WAVEFORMS.  Common values:
#   IRIS, INGV, GEOFON, ORFEUS, BGR, ETH, RASPISHAKE, NCEDC, SCEDC, GFZ …
# Full list: https://docs.obspy.org/packages/obspy.clients.fdsn.html
fdsn_site: "INGV"

# Data centre for EVENTS.  Only used when the catalog comes from FDSN
# (existing_catalog_pf: null).
# NOTE: IRIS does NOT provide an event service anymore — use USGS (global
# NEIC catalog) or ISC when fdsn_site is IRIS.
#   null   → same as fdsn_site
#   "USGS" → USGS/NEIC global catalog  (best choice when fdsn_site = IRIS)
#   "ISC"  → International Seismological Centre
fdsn_site_events: null

# ── Time window ───────────────────────────────────────────────────────────────

# Format: "YYYY-MM-DD HH:MM:SS".  Used for: the FDSN event query (event
# mode), the FDSN station query, and the continuous download span.
tmin: "2024-01-01 00:00:00"
tmax: "2024-12-31 23:59:59"

# ── Event search area  (event mode, FDSN catalog only) ────────────────────────

# Shape of the geographic search area for the event query.
#   "rectangular"  → uses lat_min / lat_max / lon_min / lon_max
#   "circular"     → uses lat_center / lon_center / radius_km
area_type: "rectangular"

# Rectangular bounding box (decimal degrees)
lat_min:  40.75
lat_max:  40.95
lon_min:  14.00
lon_max:  14.20

# Circular area (decimal degrees / km)
lat_center:  40.83
lon_center:  14.14
radius_km:   15.0

# ── Event filters  (event mode, FDSN catalog only) ────────────────────────────

# Magnitude range.  Use null to disable either bound.
mag_min:  1.5
mag_max:  null

# Depth range in km.  Use null to disable either bound.
depth_min_km:  0.0
depth_max_km:  30.0

# ── Station search area  (FDSN stations only) ─────────────────────────────────

# A circle — or a ring, when radius_km_sta_min > 0 — around lat/lon_center_sta,
# INDEPENDENT from the event search area above.
# Ignored when existing_stations_xml is set.
# Tip: for large events put the centre on the epicentre; it is also the
# reference point of the azimuthal selection below.
lat_center_sta:     40.83
lon_center_sta:     14.14
radius_km_sta_min:  0.0     # inner radius (km); 0 = full circle
radius_km_sta:      50.0    # outer radius (km)

# ── Azimuthal station selection  (optional) ───────────────────────────────────

# Thins out a dense station set (e.g. hundreds of stations up to 1000 km)
# while keeping the azimuthal coverage.  Works on FDSN stations and on a
# local StationXML alike.
# Distance and azimuth of each station are measured from lat/lon_center_sta.
# The area is split into cells = sectors ("spicchi") × rings ("anelli"), and
# each cell keeps at most azi_max_per_cell stations — those closest to the
# centre of the cell, so that the selection stays evenly spread — avoiding
# near-duplicates when possible (e.g. two networks sharing one site).
#   azi_select       : true / false — switch the selection on / off
#   azi_sectors      : number of sectors (12 → 30° each)
#   azi_rings_km     : ring edges in km, e.g. [100, 300, 600, 1000]: stations
#                      closer than the first edge or farther than the last
#                      one are dropped.  null = one single ring (no limit)
#   azi_max_per_cell : maximum number of stations kept in each cell
#   azi_check_data   : true = before choosing, ask the FDSN availability
#                      service which candidates really have data in the time
#                      to download: a station without data is skipped and the
#                      next one of the SAME cell is taken.
#                        event mode : an event counts as recorded when at
#                                     least half of its window has data
#                        continuous / stations mode : data in tmin → tmax
#                      INGV and the other EIDA nodes offer the service;
#                      IRIS / EarthScope retired it: there the check is
#                      skipped with a warning.
#                      The check lasts at most ~5 min (a busy server can be
#                      very slow): stations not checked by then are kept as
#                      candidates, after the verified ones.
# The map shows the grid, the kept stations and (in grey) the dropped ones;
# the summary reports the largest azimuthal gap before / after.
azi_select:        false
azi_sectors:       12
azi_rings_km:      null     # e.g. [100, 300, 600, 1000]
azi_max_per_cell:  2
azi_check_data:    true

# ── Station / channel selection ───────────────────────────────────────────────

# FDSN wildcards: * (any string) and ? (exactly one character).
# network/station restrict the FDSN station query ("*" = all in the area);
# they are ignored when existing_stations_xml is set.
# channel and location are ALSO used for every waveform request, even when
# the stations come from a local file.
# channel accepts comma-separated patterns:  "HH?,BH?"  "HHZ,HHN,HHE"  "*"
network:  "*"
station:  "*"
location: "*"
channel:  "HH?,BH?"

# ── Waveform time window  (event mode) ────────────────────────────────────────

# Seconds BEFORE the event origin time to start the trace.
t_before_s: 60
# Seconds AFTER the event origin time to end the trace.
t_after_s:  300

# ── Event query chunking  (event mode, FDSN catalog only) ─────────────────────

# Event queries are split into blocks of this many days to avoid FDSN limits.
# Reduce if the server returns HTTP 413 or timeout errors on large windows.
chunk_days: 365

# ── Continuous download  (continuous mode only) ───────────────────────────────

# Size of each continuous chunk (hours).  24 = one file per day per station.
# NOTE: sub-daily chunks automatically add _HH_MM to the filenames.
chunk_hours: 24

# Simultaneous download connections.
# Keep it small (3-5): FDSN servers throttle aggressive clients.
parallel_downloads: 4

# ── Map preview ───────────────────────────────────────────────────────────────

# Backend for the interactive preview map.
#   "folium"  → HTML map opened in the browser  (pip install folium)
#   "pygmt"   → static figure via PyGMT          (pip install pygmt)
map_backend: "folium"

# Colour of the event markers (marker SIZE always scales with magnitude).
#   "depth" → shallow = yellow … deep = purple
#   "time"  → oldest = dark … most recent = bright
# In the folium map this is only the initial choice: the legend has a switch
# to change it.  The static pygmt map uses this one.
# In event mode both maps also show a depth–time panel under the map; the
# folium one adds a time-window slider and a Play animation.
map_color_by: "depth"
"""


def load_or_create_config(path: str) -> dict:
    """Return the config dict; create a commented default file if absent."""
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            fh.write(DEFAULT_CONFIG)
        print(f"\n[CONFIG] Default configuration written to:\n  {path}")
        print("  Please review it, then re-run the script.\n")
        sys.exit(0)

    # Overlay the user's file on the built-in defaults, so configs written by
    # older versions of this script keep working when new keys are added.
    # (New keys take the default value until added to the file explicitly.)
    defaults = yaml.safe_load(DEFAULT_CONFIG)
    with open(path) as fh:
        cfg = {**defaults, **(yaml.safe_load(fh) or {})}
    # Unquoted dates are read by YAML as datetime objects: keep them as text
    for key in ('tmin', 'tmax'):
        if cfg[key] is not None and not isinstance(cfg[key], str):
            cfg[key] = str(cfg[key])
    return cfg


# Keys that only accept a fixed set of values
_CHOICES = {
    'download_mode': ('event', 'continuous', 'catalog', 'stations'),
    'area_type':     ('rectangular', 'circular'),
    'map_backend':   ('folium', 'pygmt'),
    'map_color_by':  ('depth', 'time'),
}


def validate_config(cfg: dict) -> None:
    """Exit with a clear message if the configuration is inconsistent.

    Catches typos that would otherwise be accepted silently — e.g. a
    misspelled download_mode used to fall back to "event" without notice.
    """
    errors = []
    for key, choices in _CHOICES.items():
        if cfg.get(key) not in choices:
            errors.append(f"{key}: {cfg.get(key)!r} — must be one of "
                          f"{', '.join(choices)}")
    try:
        if UTCDateTime(cfg['tmin']) >= UTCDateTime(cfg['tmax']):
            errors.append("tmin must be earlier than tmax")
    except Exception as exc:
        errors.append(f"tmin / tmax are not valid dates ({exc})")
    for key in ('t_before_s', 't_after_s'):
        if not isinstance(cfg.get(key), (int, float)) or cfg[key] < 0:
            errors.append(f"{key}: {cfg.get(key)!r} — must be a number ≥ 0")
    for key in ('chunk_days', 'chunk_hours', 'parallel_downloads',
                'radius_km_sta', 'radius_km'):
        if not isinstance(cfg.get(key), (int, float)) or cfg[key] <= 0:
            errors.append(f"{key}: {cfg.get(key)!r} — must be a number > 0")
    def _is_num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    r_min = cfg.get('radius_km_sta_min')
    if not _is_num(r_min) or r_min < 0:
        errors.append(f"radius_km_sta_min: {r_min!r} — must be a number ≥ 0")
    elif _is_num(cfg.get('radius_km_sta')) and r_min >= cfg['radius_km_sta']:
        errors.append("radius_km_sta_min must be smaller than radius_km_sta")
    for key in ('azi_select', 'azi_check_data'):
        if not isinstance(cfg.get(key), bool):
            errors.append(f"{key}: {cfg.get(key)!r} — must be true or false")
    for key, top in (('azi_sectors', 360), ('azi_max_per_cell', 10000)):
        v = cfg.get(key)
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= top:
            errors.append(f"{key}: {v!r} — must be a whole number "
                          f"between 1 and {top}")
    rings = cfg.get('azi_rings_km')
    if rings is not None and not (
            isinstance(rings, list) and len(rings) >= 2
            and all(_is_num(x) and x >= 0 for x in rings)
            and all(a < b for a, b in zip(rings, rings[1:]))):
        errors.append(f"azi_rings_km: {rings!r} — must be null or an "
                      f"increasing list of at least 2 distances in km, "
                      f"e.g. [100, 300, 600, 1000]")
    if cfg.get('area_type') == 'rectangular':
        try:
            if cfg['lat_min'] >= cfg['lat_max'] or cfg['lon_min'] >= cfg['lon_max']:
                errors.append("rectangular area: lat_min / lon_min must be "
                              "smaller than lat_max / lon_max")
        except TypeError:
            errors.append("rectangular area: lat_min, lat_max, lon_min, "
                          "lon_max must all be numbers")
    if errors:
        print("\n  [CONFIG ERROR]")
        for err in errors:
            print(f"    • {err}")
        print()
        sys.exit(1)


def print_config_summary(cfg: dict) -> None:
    w = 62
    print("\n" + "═" * w)
    print("  CONFIGURATION SUMMARY")
    print("═" * w)
    # Only what the selected mode actually uses is shown
    mode         = cfg['download_mode']
    uses_events  = mode in ('event', 'catalog')
    uses_sta     = mode != 'catalog'
    existing_pf  = (cfg.get('existing_catalog_pf') or None) \
        if mode == 'event' else None
    existing_sta = cfg.get('existing_stations_xml') or None
    ev_site      = cfg.get('fdsn_site_events') or cfg['fdsn_site']

    print(f"  ── Mode         : {mode.upper()}")
    if mode in ('event', 'continuous'):
        print(f"  FDSN site       : {cfg['fdsn_site']}  (stations + waveforms)")
    elif mode == 'stations' and not existing_sta:
        print(f"  FDSN site       : {cfg['fdsn_site']}  (stations)")
    if uses_events and not existing_pf and \
            (ev_site != cfg['fdsn_site'] or mode == 'catalog'):
        print(f"  FDSN events     : {ev_site}  (catalog query)")
    print(f"  Time window     : {cfg['tmin']}  →  {cfg['tmax']}")

    if uses_events:
        if existing_pf:
            print(f"  Catalog source  : LOCAL FILE → {existing_pf}")
            print(f"                    (event area and filters are ignored)")
        else:
            def _v(key):   # 'or' would hide legitimate 0 / 0.0 values
                val = cfg.get(key)
                return '–' if val is None else val
            print(f"  Event area      : {cfg['area_type']}")
            if cfg['area_type'] == 'rectangular':
                print(f"    lat [{cfg['lat_min']:.3f} – {cfg['lat_max']:.3f}]  "
                      f"lon [{cfg['lon_min']:.3f} – {cfg['lon_max']:.3f}]")
            else:
                print(f"    centre ({cfg['lat_center']:.4f}, "
                      f"{cfg['lon_center']:.4f})  "
                      f"radius {cfg['radius_km']:.1f} km")
            print(f"  Magnitude       : {_v('mag_min')}  –  {_v('mag_max')}")
            print(f"  Depth           : {_v('depth_min_km')}  –  "
                  f"{_v('depth_max_km')}  km")
            print(f"  Catalog name    : {cfg['catalog_name']}")

    if uses_sta:
        if existing_sta:
            print(f"  Station source  : LOCAL FILE → {existing_sta}")
        else:
            sta_ring = (f"ring {cfg['radius_km_sta_min']:g}–"
                        f"{cfg['radius_km_sta']:g} km"
                        if cfg['radius_km_sta_min'] else
                        f"radius {cfg['radius_km_sta']:g} km")
            print(f"  Station area    : centre ({cfg['lat_center_sta']:.4f}, "
                  f"{cfg['lon_center_sta']:.4f})  {sta_ring}")
            print(f"  Network         : {cfg['network']}   "
                  f"Station: {cfg['station']}")
        print(f"  Channel         : {cfg['channel']}"
              f"   Location: {cfg['location']}")
        if cfg['azi_select']:
            rings = (f"rings {cfg['azi_rings_km']} km" if cfg['azi_rings_km']
                     else "no rings")
            print(f"  Azimuthal sel.  : {cfg['azi_sectors']} sectors × "
                  f"{rings}, max {cfg['azi_max_per_cell']} per cell")
        else:
            print(f"  Azimuthal sel.  : off")
        print(f"  Station file    : {cfg['station_file_name']}")

    if mode == 'event':
        print(f"  Waveform window : -{cfg['t_before_s']} s  /  "
              f"+{cfg['t_after_s']} s")
    if mode == 'continuous':
        print(f"  Chunk size      : {cfg['chunk_hours']} h per file")
        print(f"  Parallel        : {cfg['parallel_downloads']} connections")
    if mode in ('event', 'continuous'):
        print(f"  Event label     : {cfg['event_label']}")
    print(f"  Map backend     : {cfg['map_backend']}"
          + (f"   (events coloured by {cfg['map_color_by']})"
             if uses_events else ''))
    print("═" * w + "\n")


# "key: value   # optional inline comment"
_YAML_KEY_LINE = re.compile(r'^(\s*)([A-Za-z_]\w*)\s*:\s*(.*?)(\s+#.*)?$')


def _yaml_scalar(v) -> str:
    """Format a config value as a YAML scalar."""
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, str):
        return json.dumps(v)          # double-quoted, special chars escaped
    return str(v)


def _update_config_file(path: str, cfg: dict, changed: set) -> None:
    """Write the changed keys back to the config file.

    Only the lines of the changed keys are rewritten: comments (including
    inline ones after a value) and every other line stay exactly as they
    are.  Changed keys missing from the file (newer defaults) are appended.
    """
    with open(path) as fh:
        lines = fh.readlines()
    out, written = [], set()
    for line in lines:
        mo = _YAML_KEY_LINE.match(line.rstrip('\n'))
        if mo and mo.group(2) in changed:
            indent, key, _, comment = mo.groups()
            out.append(f"{indent}{key}: {_yaml_scalar(cfg[key])}"
                       f"{comment or ''}\n")
            written.add(key)
        else:
            out.append(line)
    missing = sorted(changed - written)
    if missing:
        if out and not out[-1].endswith('\n'):
            out.append('\n')
        out.append('\n# ── added by the interactive editor ──\n')
        out += [f"{k}: {_yaml_scalar(cfg[k])}\n" for k in missing]
    with open(path, 'w') as fh:
        fh.writelines(out)


def ask_modify_config(path: str, cfg: dict) -> dict:
    """Optionally let the user change individual parameters interactively."""
    ans = input("Modify a parameter before running? [y/N]: ").strip().lower()
    if ans != 'y':
        return cfg

    keys = list(cfg.keys())
    print(f"  Available parameters: {keys}")
    print("  Empty input keeps the current value; type null to clear it.")
    print("  Type 'done' when finished.\n")

    changed = set()
    while True:
        key = input("  Parameter name (or 'done'): ").strip()
        if key.lower() == 'done':
            break
        if key not in cfg:
            print(f"  ! Unknown key '{key}'.  Choose from: {keys}")
            continue
        old = cfg[key]
        raw = input(f"  {key} [{old}]  →  new value: ").strip()
        if raw == '':
            print(f"  –  {key} unchanged\n")
            continue
        if raw.lower() in ('null', 'none'):
            new = None
        elif isinstance(old, str):
            new = raw.strip('"\'')        # text keys (dates, names) stay text
        else:
            # YAML gives numbers and booleans their type — also for keys whose
            # current value is null (e.g. mag_max, existing_catalog_pf)
            try:
                new = yaml.safe_load(raw)
            except yaml.YAMLError:
                new = raw
        cfg[key] = new
        changed.add(key)
        print(f"  ✓  {key} = {new!r}\n")

    if changed:
        save = input("  Save changes to the config file? [y/N]: ").strip().lower()
        if save == 'y':
            _update_config_file(path, cfg, changed)
            print(f"  Config updated: {path}\n")
    return cfg


# ═════════════════════════════════════════════════════════════════════════════
# 2 ─ EXISTING FILE LOADERS
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_local_path(value: str, base_dir: str) -> str:
    """Return absolute path to a local file.

    Bare filename (no path separator) → looked up in base_dir.
    Anything else → treated as an absolute or relative path.
    """
    if os.sep not in value and '/' not in value:
        return os.path.join(base_dir, value)
    return os.path.abspath(os.path.expanduser(value))      # "~/…" allowed


def _event_name_from_time(label: str, ptime: float) -> str:
    """Build '<label>_yyyy_mm_dd_hh_mm_ss' from a pyrocko timestamp."""
    ts = util.time_to_str(ptime)                    # "yyyy-mm-dd hh:mm:ss.sss"
    return (label + '_'
            + ts[0:4] + '_' + ts[5:7]  + '_' + ts[8:10] + '_'
            + ts[11:13] + '_' + ts[14:16] + '_' + ts[17:19])


def _dedupe_event_names(events) -> None:
    """Make event names unique (in place) by appending _2, _3, …

    Two events in the same second (or a catalog listing an event twice)
    would otherwise share one DATA/ folder, and the waveforms of the second
    one would be skipped as "already on disk".  The events must be sorted
    by time, so that the suffixes are the same on every run.
    """
    seen = {}
    for ev in events:
        n = seen.get(ev.name, 0) + 1
        seen[ev.name] = n
        if n > 1:
            new = f"{ev.name}_{n}"
            print(f"  [WARN] duplicate event name {ev.name} → using {new}")
            ev.name = new


def load_catalog_from_pf(pf_path: str, label: str) -> list:
    """Load an event catalog in Pyrocko .pf format from disk.

    Event names stored in the file are kept as-is — they become the DATA/
    folder names, so waveforms from different servers/networks accumulate
    in the same event folders.  Events without a name get a generated
    '<label>_yyyy_mm_dd_hh_mm_ss' name as fallback.
    """
    if not os.path.isfile(pf_path):
        print(f"\n  [ERROR] File not found: {pf_path}\n")
        sys.exit(1)
    print(f"  File : {pf_path}")
    events = model.load_events(pf_path)
    for ev in events:
        if not ev.name:
            ev.name = _event_name_from_time(label, ev.time)
    events.sort(key=lambda e: e.time)
    _dedupe_event_names(events)
    print(f"  {len(events)} events loaded.\n")
    return events


def load_stations_from_xml(xml_path: str):
    """Load an existing StationXML inventory from disk."""
    from obspy import read_inventory
    if not os.path.isfile(xml_path):
        print(f"\n  [ERROR] File not found: {xml_path}\n")
        sys.exit(1)
    print(f"  File : {xml_path}")
    inv = read_inventory(xml_path)
    print(f"  {len(_unique_stations(inv))} stations across "
          f"{len({net.code for net in inv})} network(s) loaded.\n")
    return inv


def _unique_stations(inv) -> list:
    """Sorted list of (net, sta, lat, lon, site_name), one per station.

    An inventory lists a station once per epoch (e.g. after an equipment
    change), so the same station can appear several times: counting or
    plotting the raw inventory would show it more than once.
    """
    out = {}
    for net in inv or []:
        for sta in net:
            out.setdefault((net.code, sta.code),
                           (net.code, sta.code, sta.latitude, sta.longitude,
                            sta.site.name if sta.site else ''))
    return [out[k] for k in sorted(out)]


# ═════════════════════════════════════════════════════════════════════════════
# 3 ─ FDSN QUERIES
# ═════════════════════════════════════════════════════════════════════════════

def _radius_km_to_deg(km: float) -> float:
    """Approximate conversion: km → degrees (1° ≈ 111.32 km)."""
    return km / 111.32


def _area_kwargs_events(cfg: dict) -> dict:
    """Geographic kwargs for the EVENT query (rectangular or circular)."""
    if cfg['area_type'] == 'rectangular':
        return dict(
            minlatitude=cfg['lat_min'],  maxlatitude=cfg['lat_max'],
            minlongitude=cfg['lon_min'], maxlongitude=cfg['lon_max'],
        )
    else:
        return dict(
            latitude=cfg['lat_center'],
            longitude=cfg['lon_center'],
            maxradius=_radius_km_to_deg(cfg['radius_km']),
        )


def _area_kwargs_stations(cfg: dict) -> dict:
    """Geographic kwargs for the STATION query (circle or ring)."""
    kw = dict(
        latitude=cfg['lat_center_sta'],
        longitude=cfg['lon_center_sta'],
        maxradius=_radius_km_to_deg(cfg['radius_km_sta']),
    )
    if cfg['radius_km_sta_min']:
        kw['minradius'] = _radius_km_to_deg(cfg['radius_km_sta_min'])
    return kw


def query_events(client: Client, cfg: dict):
    """Download the event catalog in time chunks to avoid server limits.

    Returns (catalog, failed): failed lists the time windows that could not
    be downloaded even after retries — the catalog is then incomplete.
    """
    tmin  = UTCDateTime(cfg['tmin'])
    tmax  = UTCDateTime(cfg['tmax'])
    chunk = cfg['chunk_days'] * 86400   # seconds

    geo = _area_kwargs_events(cfg)

    # Optional magnitude / depth filters
    filters = {}
    if cfg.get('mag_min')      is not None: filters['minmagnitude'] = cfg['mag_min']
    if cfg.get('mag_max')      is not None: filters['maxmagnitude'] = cfg['mag_max']
    if cfg.get('depth_min_km') is not None: filters['mindepth']     = cfg['depth_min_km']
    if cfg.get('depth_max_km') is not None: filters['maxdepth']     = cfg['depth_max_km']

    cat    = Catalog()
    failed = []
    t1     = tmin
    while t1 < tmax:
        t2 = min(t1 + chunk, tmax)
        label = f"{t1.strftime('%Y-%m-%d')} → {t2.strftime('%Y-%m-%d')}"
        print(f"  Querying events  {label} … ", end='', flush=True)
        # few and essential requests: as patient as the station query
        tmp, status = _fetch_with_retry(
            lambda: client.get_events(starttime=t1, endtime=t2,
                                      **geo, **filters),
            f"events {label}", attempts=CONNECT_RETRIES)
        if status == 'ok':
            cat += tmp
            print(f"{len(tmp)} events")
        elif status == 'nodata':
            print("0 events")
        else:
            failed.append(label)          # error already printed
        t1 = t2

    # Adjacent windows share their boundary instant: drop events listed twice
    seen, unique = set(), Catalog()
    for ev in cat:
        rid = str(ev.resource_id)
        if rid not in seen:
            seen.add(rid)
            unique.append(ev)

    print(f"\n  ── Total events found: {len(unique)} ──\n")
    if failed:
        print(f"  [WARN] {len(failed)} time window(s) failed after "
              f"{MAX_RETRIES} attempts — the catalog is INCOMPLETE:")
        for label in failed:
            print(f"           {label}")
        print("         Re-run later, or reduce chunk_days.\n")
    return unique, failed


def query_stations(client: Client, cfg: dict) -> object:
    """Download station inventory (includes full instrument response).

    Some data centres host third-party networks whose response metadata is
    malformed and makes obspy fail while parsing the server reply (e.g. a
    PolesZeros stage with an empty NormalizationFrequency).  A single broken
    station would kill the whole inventory, so on a parse failure the query
    falls back to one request per network, and inside a broken network to
    one request per station — keeping everything that parses and reporting
    what had to be skipped.
    """
    tmin = UTCDateTime(cfg['tmin'])
    tmax = UTCDateTime(cfg['tmax'])
    geo  = _area_kwargs_stations(cfg)

    def _fetch(level, **overrides):
        kw = dict(starttime=tmin, endtime=tmax,
                  network=cfg['network'], station=cfg['station'],
                  location=cfg['location'], channel=cfg['channel'],
                  level=level, **geo)
        kw.update(overrides)
        return client.get_stations(**kw)

    print("  Querying stations … ", end='', flush=True)
    try:
        # one-off and essential: more patience than a single waveform request
        inv = _call_with_retry(lambda: _fetch('response'), 'station query',
                               attempts=CONNECT_RETRIES)
        print(f"{len(_unique_stations(inv))} stations across "
              f"{len(inv)} network(s)\n")
        return inv
    except Exception as exc:
        if _is_no_data(exc):
            print("0 stations found\n")
            return None
        # A large inventory is one long reply: on a flaky server smaller
        # replies get through much more easily, so both a malformed reply and
        # a connection that keeps breaking fall back to smaller requests
        reason = ('the connection keeps breaking' if _is_transient(exc)
                  else f'parse failed ({type(exc).__name__})')
        print(f"  {reason} — retrying network by network …")

    # ── fallback 1: light query for the codes, then one request per network ──
    try:
        skeleton = _call_with_retry(lambda: _fetch('station'), 'station list',
                                    attempts=CONNECT_RETRIES)
    except Exception as exc:
        print(f"  [ERR] station query failed entirely: {exc}\n")
        return None

    inv = None
    for net_code in sorted({net.code for net in skeleton}):
        try:
            part = _call_with_retry(
                lambda: _fetch('response', network=net_code),
                f"network {net_code}")
            inv  = part if inv is None else inv + part
        except Exception:
            # ── fallback 2: one request per station of the broken network ────
            sta_codes = sorted({sta.code for net in skeleton
                                if net.code == net_code for sta in net})
            for sta_code in sta_codes:
                try:
                    part = _call_with_retry(
                        lambda: _fetch('response',
                                       network=net_code, station=sta_code),
                        f"{net_code}.{sta_code}")
                    inv  = part if inv is None else inv + part
                except Exception as exc2:
                    if _is_no_data(exc2):
                        reason = 'no data'
                    elif _is_transient(exc2):
                        reason = f'network error ({type(exc2).__name__})'
                    else:
                        reason = 'malformed response metadata on the server'
                    print(f"  [WARN] skipping {net_code}.{sta_code} — {reason}")

    if inv is None:
        print("  0 usable stations found\n")
        return None
    print(f"  Recovered {len(_unique_stations(inv))} stations across "
          f"{len({net.code for net in inv})} network(s)\n")
    return inv


def get_stations(client: Client, cfg: dict) -> object:
    """Return station inventory: from an existing StationXML file or FDSN.

    Controlled by config key 'existing_stations_xml'.
    """
    existing = cfg.get('existing_stations_xml') or None
    if existing:
        print("  Loading stations from existing XML …")
        return load_stations_from_xml(_resolve_local_path(existing, META_DIR))
    return query_stations(client, cfg)


# ── Azimuthal station selection ──────────────────────────────────────────────

def _destination(lat: float, lon: float, az_deg: float, dist_km: float):
    """(lat, lon) reached from (lat, lon) along azimuth az_deg (sphere)."""
    d = dist_km / 6371.0
    la1, lo1, a = (math.radians(x) for x in (lat, lon, az_deg))
    la2 = math.asin(math.sin(la1) * math.cos(d) +
                    math.cos(la1) * math.sin(d) * math.cos(a))
    lo2 = lo1 + math.atan2(math.sin(a) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540.0) % 360.0 - 180.0


def _max_azimuthal_gap(azimuths) -> float:
    """Largest angle (deg) between azimuthally adjacent stations."""
    if len(azimuths) < 2:
        return 360.0
    az = sorted(a % 360.0 for a in azimuths)
    return max([b - a for a, b in zip(az, az[1:])] + [az[0] + 360.0 - az[-1]])


# Two stations of the same cell closer than this (in cell sizes) count as
# near-duplicates: the second one is kept only if the cell has no better one
_MIN_SEP_CELL = 0.2


# ── Data availability (FDSN availability service) ────────────────────────────

_AVAIL_CHUNK      = 10    # stations per availability request: the server
                          # time grows with the stations asked about (INGV
                          # ≈ 0.3 s per station, much more when it is busy)
                          # and hardly with the length of the period
_AVAIL_WORKERS    = 4     # availability requests run in parallel
_AVAIL_TIMEOUT_S  = 120   # per request
_AVAIL_BUDGET_S   = 300   # whole check: once this is over, the stations not
                          # checked yet stay unchecked (kept as candidates,
                          # after the verified ones) — a busy server must not
                          # stall the script for an hour
_AVAIL_JOIN_S     = 86400 # event windows closer than this (e.g. a sequence)
                          # are asked about together, in one time segment
_AVAIL_MAX_WINDOWS = 20   # up to this many segments: one request each,
                          # otherwise one request for the whole span
_EVENT_MIN_COVER  = 0.5   # an event counts as recorded if ≥ 50 % of its
                          # waveform window has data
_PERIOD_MIN_COVER = 0.01  # continuous / stations: below 1 % of tmin → tmax
                          # a station counts as having no data


def _has_data(cov, per_event: bool) -> bool:
    """True when a coverage value means 'this station has data'.

    cov None = could not be checked: the station is given the benefit of
    the doubt (kept as a candidate, after the verified ones).
    """
    if cov is None:
        return True
    return cov > 0 if per_event else cov >= _PERIOD_MIN_COVER


def _availability_url(cfg: dict, client):
    """URL of the FDSN availability service of fdsn_site (or None)."""
    from obspy.clients.fdsn.header import URL_MAPPINGS
    base = getattr(client, 'base_url', None)
    if not base:
        site = cfg['fdsn_site']
        base = URL_MAPPINGS.get(site.upper(), site)
    if not str(base).startswith('http'):
        return None
    return str(base).rstrip('/') + '/fdsnws/availability/1/query'


def _merge_windows(windows: list, join_s: float) -> list:
    """Merge time windows [(t1, t2), …] closer than join_s into segments."""
    segments = []
    for t1, t2 in sorted(windows):
        if segments and t1 - segments[-1][1] <= join_s:
            segments[-1][1] = max(segments[-1][1], t2)
        else:
            segments.append([t1, t2])
    return [tuple(s) for s in segments]


def _fetch_availability(url: str, cfg: dict, stations: list,
                        segments: list, mergegaps: float, progress=None):
    """Data spans {(net, sta): [(start, end), …]} (epoch seconds).

    stations  : [(net, sta), …], asked about in this order (most useful
                first: if the time runs out, the last ones stay unchecked)
    segments  : time intervals [(t1, t2), …] to ask about
    mergegaps : gaps shorter than this (s) are merged by the server
    progress  : optional callback progress(done, total) after each block
    One GET request per (segment, block of stations) — POST is broken on
    some servers, e.g. INGV — run in parallel.  A block matching too many
    streams (HTTP 413) or timing out is split in two.  After _AVAIL_BUDGET_S
    no new request is sent.  Raises LookupError when the server has no
    availability service.

    Returns (spans, unchecked, late): unchecked is the set of stations that
    could not be checked — a flaky or busy server does not cancel the whole
    check — and late is True when the time budget ran out.
    """
    import urllib.request
    import urllib.parse
    import urllib.error

    deadline = time.monotonic() + _AVAIL_BUDGET_S
    late = threading.Event()      # time budget exhausted
    stop = threading.Event()      # Ctrl-C / fatal error: send nothing more

    def iso(t):
        return UTCDateTime(t).strftime('%Y-%m-%dT%H:%M:%S')

    def one_block(t1, t2, block):
        """(spans, unchecked stations) of one block; splits it if needed."""
        found, failed, pending = {}, set(), [block]
        while pending:
            chunk = pending.pop()
            left  = deadline - time.monotonic()
            if left <= 0:
                late.set()
            if stop.is_set() or left <= 0:
                failed.update(chunk)
                continue
            query = url + '?' + urllib.parse.urlencode(dict(
                network=','.join(sorted({n for n, _ in chunk})),
                station=','.join(sorted({s for _, s in chunk})),
                location=cfg['location'] or '--', channel=cfg['channel'],
                starttime=iso(t1), endtime=iso(t2), format='text',
                merge='quality,samplerate,overlap',
                mergegaps=f'{mergegaps:.0f}', nodata='204'))

            def fetch():
                try:
                    with urllib.request.urlopen(
                            query, timeout=min(_AVAIL_TIMEOUT_S,
                                               max(left, 10.0))) as resp:
                        return resp.status, resp.read().decode('utf-8',
                                                               'replace')
                except urllib.error.HTTPError as exc:
                    if exc.code >= 500 or exc.code == 429:
                        raise               # transient: retried
                    return exc.code, ''     # an answer, not a network error
                except (TimeoutError, urllib.error.URLError) as exc:
                    # Too slow: retrying the same request would only waste
                    # the same time again — ask about fewer stations instead
                    if isinstance(exc, TimeoutError) or isinstance(
                            getattr(exc, 'reason', None), TimeoutError):
                        return 'timeout', ''
                    raise

            try:
                status, body = _call_with_retry(fetch, 'availability',
                                                verbose=False)
            except Exception as exc:
                # A server that cannot be reached is not split (it would only
                # multiply the failing requests): these stations stay
                # unchecked, the rest of the check goes on.
                if not _is_transient(exc):
                    raise
                failed.update(chunk)
                continue
            if status in (413, 'timeout') and len(chunk) > 1:
                half = len(chunk) // 2
                pending += [chunk[:half], chunk[half:]]
                continue
            if status == 'timeout':
                failed.update(chunk)
                continue
            if status in (404, 501):
                raise LookupError(f'HTTP {status}')
            if status not in (200, 204):
                raise RuntimeError(f'HTTP {status}')
            wanted = set(chunk)             # net × sta lists may match more
            for line in body.splitlines():
                parts = line.split()
                if len(parts) < 6 or line.startswith('#'):
                    continue
                if (parts[0], parts[1]) in wanted:
                    found.setdefault((parts[0], parts[1]), []).append(
                        (UTCDateTime(parts[-2]).timestamp,
                         UTCDateTime(parts[-1]).timestamp))
        return found, failed

    blocks = [stations[i:i + _AVAIL_CHUNK]
              for i in range(0, len(stations), _AVAIL_CHUNK)]
    # block by block, all the segments of a block together: the stations
    # asked about first are completely checked first
    tasks  = [(t1, t2, b) for b in blocks for t1, t2 in segments]
    spans, unchecked = {}, set()
    pool = ThreadPoolExecutor(max_workers=_AVAIL_WORKERS)
    try:
        futures = [pool.submit(one_block, *task) for task in tasks]
        for done, fut in enumerate(as_completed(futures), 1):
            found, failed = fut.result()
            for key, sp in found.items():
                spans.setdefault(key, []).extend(sp)
            unchecked |= failed
            if progress:
                progress(done, len(tasks))
    except BaseException:
        # 404, Ctrl-C …: drop the queued requests, send nothing more
        stop.set()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    if unchecked and len(unchecked) == len(stations) and not late.is_set():
        raise ConnectionError('every availability request failed')
    return spans, unchecked, late.is_set()


def _covered(spans: list, t1: float, t2: float) -> float:
    """Seconds of t1 → t2 covered by the union of the spans."""
    total, reached = 0.0, t1
    for a, b in sorted(spans):
        a, b = max(a, reached), min(b, t2)
        if b > a:
            total  += b - a
            reached = b
    return total


def data_coverage(inv, cfg: dict, client, windows: list, per_event: bool,
                  stations=None, progress=None):
    """Coverage of the candidate stations, from the availability service.

    windows   : [(t1, t2), …] epoch seconds — the event waveform windows
                (per_event) or the single period tmin → tmax
    per_event : coverage = fraction of the windows with ≥ 50 % data
                otherwise = covered fraction of the single window
    stations  : [(net, sta), …] to check, most useful first (default: all
                the stations of inv)
    progress  : optional callback progress(done, total)
    Returns ({(net, sta): coverage}, note or None), or (None, reason) when
    the check could not be done.  coverage None = station not checked.
    """
    url = _availability_url(cfg, client)
    if url is None:
        return None, f"no FDSN URL known for '{cfg['fdsn_site']}'"
    if stations is None:
        stations = [(n, s) for n, s, *_ in _unique_stations(inv)]
    t_first = min(w[0] for w in windows)
    t_last  = max(w[1] for w in windows)
    if per_event:
        # Ask only about the (short) event windows; windows close in time
        # (a sequence) share one request — the server time grows with the
        # number of requests, hardly with the length of each.  Too many
        # segments left: the whole span at once.
        segments = _merge_windows(windows, _AVAIL_JOIN_S)
        if len(segments) > _AVAIL_MAX_WINDOWS:
            segments = [(t_first, t_last)]
        mergegaps = 10.0
    else:
        segments = [(t_first, t_last)]
        # over a long period only the rough coverage matters: merging short
        # gaps keeps the server's answer small (≤ 1 day for ≥ 200 days)
        mergegaps = min(86400.0, max(10.0, (t_last - t_first) / 200))
    try:
        spans, unchecked, late = _fetch_availability(
            url, cfg, stations, segments, mergegaps, progress)
    except LookupError:
        return None, (f"{cfg['fdsn_site']} does not offer the availability "
                      f"service")
    except Exception as exc:
        return None, f"availability request failed ({type(exc).__name__})"
    cov = {}
    for key in stations:
        if key in unchecked:
            cov[key] = None                   # could not be checked
            continue
        sp = spans.get(key, [])
        if per_event:
            recorded = sum(1 for a, b in windows
                           if _covered(sp, a, b) >= _EVENT_MIN_COVER * (b - a))
            cov[key] = recorded / len(windows)
        else:
            a, b = windows[0]
            cov[key] = _covered(sp, a, b) / (b - a)
    why = (f"the server is too slow, the check stops after "
           f"{_AVAIL_BUDGET_S / 60:.0f} min" if late else "network errors")
    note = (f"{len(unchecked)} station(s) could not be checked ({why}): "
            f"kept as candidates, after the verified ones"
            if unchecked else None)
    return cov, note


# ── Azimuthal station selection ──────────────────────────────────────────────

def _cell_rows(inv, cfg: dict):
    """Distance, azimuth and sector × ring cell of every station of inv.

    Returns (rows, ring edges in km, rings_given).  Each row has net, sta,
    lat, lon, dist_km, az and cell (sector, ring) — None outside the rings,
    with status 'outside rings' — plus, inside a cell, cx / cy (position
    relative to the cell centre, in cell sizes) and off_centre.
    """
    from obspy.geodetics import gps2dist_azimuth

    lat0, lon0 = cfg['lat_center_sta'], cfg['lon_center_sta']
    n_sec = cfg['azi_sectors']
    width = 360.0 / n_sec

    rows = []
    for net, sta, lat, lon, _ in _unique_stations(inv):
        dist_m, az, _ = gps2dist_azimuth(lat0, lon0, lat, lon)
        rows.append(dict(net=net, sta=sta, lat=lat, lon=lon,
                         dist_km=dist_m / 1000.0, az=az % 360.0,
                         cell=None, status=''))

    rings_given = bool(cfg['azi_rings_km'])
    edges = (list(cfg['azi_rings_km']) if rings_given else
             [0.0, max((r['dist_km'] for r in rows), default=0.0) + 1e-6])

    for r in rows:
        d = r['dist_km']
        ring = next((i for i in range(len(edges) - 1)
                     if edges[i] <= d < edges[i + 1]), None)
        if ring is None and d == edges[-1]:
            ring = len(edges) - 2                  # outer edge is inclusive
        if ring is None:
            r['status'] = 'outside rings'
            continue
        sector = min(int(r['az'] // width), n_sec - 1)
        r['cell'] = (sector, ring)
        # position inside the cell, in cell sizes, relative to its centre
        r['cx'] = ((r['az'] - (sector + 0.5) * width + 180.0) % 360.0
                   - 180.0) / width
        r['cy'] = ((d - 0.5 * (edges[ring] + edges[ring + 1]))
                   / (edges[ring + 1] - edges[ring]))
        r['off_centre'] = math.hypot(r['cx'], r['cy'])
    return rows, edges, rings_given


def _check_order(inv, cfg: dict) -> list:
    """Stations to ask the availability service about, most useful first.

    Round-robin over the cells — first the station closest to the centre of
    every cell, then the second one of every cell, … — so that, if the
    check stops early, what is missing are the stations least likely to be
    kept.  Stations outside the rings are dropped anyway: not asked about.
    """
    rows, _, _ = _cell_rows(inv, cfg)
    cells = {}
    for r in rows:
        if r['cell'] is not None:
            cells.setdefault(r['cell'], []).append(r)
    ranked = []
    for members in cells.values():
        members.sort(key=lambda r: (r['off_centre'], r['net'], r['sta']))
        ranked += [(rank, r['off_centre'], r['net'], r['sta'])
                   for rank, r in enumerate(members)]
    return [(net, sta) for _, _, net, sta in sorted(ranked)]


def select_stations_azimuthal(inv, cfg: dict, coverage=None,
                              per_event: bool = False, n_windows: int = 1):
    """Keep at most azi_max_per_cell stations in each sector × ring cell.

    Distance and azimuth are measured from lat/lon_center_sta.  With a data
    check (coverage given) stations without data are skipped, so the next
    station of the same cell takes their place, and stations with more data
    come first.  Then the stations closest to the cell centre are kept, so
    that the selection stays evenly spread, avoiding near-duplicates of a
    station already kept when possible.  Returns (selected inventory or
    None, report); the report describes every candidate and feeds the
    summary, the map and the selection file.
    """
    from copy import deepcopy

    lat0, lon0 = cfg['lat_center_sta'], cfg['lon_center_sta']
    n_sec = cfg['azi_sectors']
    k_max = cfg['azi_max_per_cell']

    rows, edges, rings_given = _cell_rows(inv, cfg)
    cells = {}
    for r in rows:
        key = (r['net'], r['sta'])
        checked = coverage is not None and key in coverage
        r['cov'] = coverage[key] if checked else None
        if not checked:
            r['data_txt'] = '-'             # no data check (for this one)
        elif r['cov'] is None:
            r['data_txt'] = '?'             # check failed for this one
        elif per_event:
            r['data_txt'] = f"{round(r['cov'] * n_windows)}/{n_windows} ev"
        else:
            r['data_txt'] = f"{r['cov']:.0%}"
        if r['cell'] is None:
            continue                        # outside the rings
        if r['cov'] is not None and not _has_data(r['cov'], per_event):
            r['status'] = 'no data'          # the next one of the cell wins
            continue
        cells.setdefault(r['cell'], []).append(r)

    def near(a, b):
        return math.hypot(a['cx'] - b['cx'], a['cy'] - b['cy']) < _MIN_SEP_CELL

    def preference(r):
        # more data first (rounded to 10 %, so that tiny differences do not
        # override the geometry; unchecked stations come after the verified
        # ones), then closest to the cell centre
        data = round(r['cov'], 1) if r['cov'] is not None else 0.0
        return (-data, r['off_centre'], r['net'], r['sta'])

    chosen = set()
    for members in cells.values():
        members.sort(key=preference)
        picked = []
        # 1st pass: in order of preference, skipping near-duplicates of a
        # station already kept (e.g. two networks sharing one site);
        # 2nd pass: take those back only if the cell would stay below k_max
        for r in members:
            if len(picked) < k_max and not any(near(r, p) for p in picked):
                picked.append(r)
        for r in members:
            if len(picked) < k_max and r not in picked:
                picked.append(r)
        for r in members:
            r['status'] = 'selected' if r in picked else 'cell full'
        chosen.update((r['net'], r['sta']) for r in picked)

    # Keep every epoch / channel of the chosen stations, drop the others
    sel = deepcopy(inv)
    for net in sel.networks:
        net.stations = [s for s in net.stations if (net.code, s.code) in chosen]
    sel.networks = [n for n in sel.networks if n.stations]

    report = dict(
        rows=rows, edges=edges, rings_given=rings_given,
        n_sectors=n_sec, max_per_cell=k_max, lat0=lat0, lon0=lon0,
        n_cells=n_sec * (len(edges) - 1), n_filled=len(cells),
        n_selected=len(chosen), data_check=None,
        gap_before=_max_azimuthal_gap([r['az'] for r in rows]),
        gap_after=_max_azimuthal_gap(
            [r['az'] for r in rows if r['status'] == 'selected']),
    )
    return (sel if chosen else None), report


def apply_station_selection(inv, cfg: dict, client=None, windows=None,
                            per_event: bool = False):
    """Run the azimuthal selection (and its data check) when switched on.

    windows / per_event : time to check for data — see data_coverage().
    Returns (inventory to use, report or None).
    """
    if not cfg['azi_select'] or inv is None:
        return inv, None

    coverage, check = None, 'off (azi_check_data: false)'
    if cfg['azi_check_data'] and windows:
        what = (f"{len(windows)} event window(s)" if per_event
                else "tmin → tmax")
        head = f"  Checking which candidates have data ({what}) … "
        t0   = time.monotonic()

        def progress(done, total):
            # a live counter: a slow server must not look like a frozen script
            print(f"\r{head}{done}/{total} requests  "
                  f"({time.monotonic() - t0:.0f} s)", end='', flush=True)

        print(head, end='', flush=True)
        coverage, note = data_coverage(inv, cfg, client, windows, per_event,
                                       _check_order(inv, cfg), progress)
        print('\r' + head, end='')
        if coverage is None:
            check = f"skipped — {note}"
            print(f"{' ' * 30}\n  [WARN] Data check skipped: {note}.\n"
                  f"         The selection uses the station metadata only.")
        else:
            n_ok = sum(c is not None and _has_data(c, per_event)
                       for c in coverage.values())
            check = (f"availability service of {cfg['fdsn_site']}: "
                     f"{n_ok} of {len(coverage)} candidates have data")
            print(f"{n_ok} of {len(coverage)} have data  "
                  f"({time.monotonic() - t0:.0f} s){' ' * 10}")
            if note:
                check += f" — INCOMPLETE: {note}"
                print(f"  [WARN] Data check incomplete: {note}.")

    sel, rep = select_stations_azimuthal(
        inv, cfg, coverage, per_event, len(windows) if windows else 1)
    rep['data_check'] = check
    rows    = rep['rows']
    n_full  = sum(r['status'] == 'cell full' for r in rows)
    n_out   = sum(r['status'] == 'outside rings' for r in rows)
    n_empty = sum(r['status'] == 'no data' for r in rows)
    rings   = (f"{len(rep['edges']) - 1} ring(s) {rep['edges']} km"
               if rep['rings_given'] else "no rings")
    print(f"  Azimuthal selection: {rep['n_sectors']} sectors × {rings}, "
          f"max {rep['max_per_cell']} per cell")
    print(f"    candidates : {len(rows):4d} stations   "
          f"(max azimuthal gap {rep['gap_before']:.0f}°)")
    print(f"    selected   : {rep['n_selected']:4d} stations   "
          f"(max azimuthal gap {rep['gap_after']:.0f}°)")
    print(f"    cells      : {rep['n_filled']} of {rep['n_cells']} "
          f"contain stations with data" if coverage is not None else
          f"    cells      : {rep['n_filled']} of {rep['n_cells']} "
          f"contain stations")
    print(f"    dropped    : {n_full} (cell already full), {n_empty} (no "
          f"data), {n_out} (outside the rings)\n")
    if sel is None:
        print("  [WARN] No station left after the selection: check "
              "azi_rings_km, the channel and the time window.\n")
    return sel, rep


def save_selection_report(rep: dict, cfg: dict) -> None:
    """Write META_DATA/<station_file_name>_selection.txt."""
    os.makedirs(META_DIR, exist_ok=True)
    path = os.path.join(META_DIR, cfg['station_file_name'] + '_selection.txt')
    order = {'selected': 0, 'cell full': 1, 'no data': 2, 'outside rings': 3}
    rows = sorted(rep['rows'], key=lambda r: (order.get(r['status'], 4),
                                              r['az']))
    with open(path, 'w') as fh:
        fh.write(f"# Azimuthal station selection — reference point "
                 f"{rep['lat0']:.4f} N, {rep['lon0']:.4f} E\n")
        source = (f"local file {cfg['existing_stations_xml']}"
                  if cfg.get('existing_stations_xml') else
                  f"FDSN {cfg['fdsn_site']}, channel {cfg['channel']}, "
                  f"{cfg['radius_km_sta_min']:g}–{cfg['radius_km_sta']:g} km")
        fh.write(f"# candidates from: {source}\n")
        fh.write(f"# data check: {rep.get('data_check') or 'off'}\n")
        fh.write(f"# {rep['n_sectors']} sectors of "
                 f"{360.0 / rep['n_sectors']:g}°, ring edges (km): "
                 f"{rep['edges'] if rep['rings_given'] else 'none'}, "
                 f"max {rep['max_per_cell']} station(s) per cell\n")
        fh.write(f"# {rep['n_selected']} of {len(rows)} stations selected; "
                 f"max azimuthal gap {rep['gap_before']:.1f}° (all) → "
                 f"{rep['gap_after']:.1f}° (selected)\n")
        fh.write(f"{'NET':<4} {'STA':<6} {'dist_km':>8} {'az_deg':>7} "
                 f"{'sector':>6} {'ring':>4} {'data':>9}  status\n")
        for r in rows:
            sec, ring = (r['cell'][0] + 1, r['cell'][1] + 1) if r['cell'] \
                else ('-', '-')
            fh.write(f"{r['net']:<4} {r['sta']:<6} {r['dist_km']:8.1f} "
                     f"{r['az']:7.1f} {sec:>6} {ring:>4} {r['data_txt']:>9}  "
                     f"{r['status']}\n")
    print(f"  Saved: {path}")


# ── Network helpers: connection, retry policy, atomic file writes ────────────

MAX_RETRIES  = 3     # total attempts per request
RETRY_WAIT_S = 5.0   # pause after the 1st failure, then 10 s, …
# Connecting happens once per run, so it can afford more patience: short
# server hiccups (tens of seconds) should not stop the whole run
CONNECT_RETRIES = 5  # attempts, with pauses of 5, 10, 20, 30 s

# Server / network conditions that usually pass by themselves
_TRANSIENT_FDSN = (FDSNTimeoutException, FDSNInternalServerException,
                   FDSNBadGatewayException, FDSNServiceUnavailableException,
                   FDSNTooManyRequestsException)


def _is_no_data(exc: Exception) -> bool:
    """True when the server reply means 'no data available', not a failure."""
    return isinstance(exc, FDSNNoDataException) or 'No data' in str(exc)


def _is_transient(exc: Exception) -> bool:
    """True for errors worth retrying: connection resets, timeouts, HTTP
    429 / 5xx.  Bad requests, missing data and unparseable server replies
    are not retried — repeating the same request cannot fix them."""
    if _is_no_data(exc):
        return False
    if isinstance(exc, _TRANSIENT_FDSN + (OSError, http.client.HTTPException)):
        return True
    # obspy wraps connection-level errors (e.g. ConnectionResetError) and
    # unlisted HTTP codes into a generic FDSNException
    msg = str(exc)
    return isinstance(exc, FDSNException) and (
        'Unknown Error' in msg or 'Unknown HTTP code: 5' in msg)


def _call_with_retry(fn, what: str, attempts: int = MAX_RETRIES,
                     verbose: bool = True):
    """Call fn(), retrying transient errors with a growing pause.

    Any other exception, and the last transient one, is re-raised.
    verbose=False retries silently (the caller reports the outcome).
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts or not _is_transient(exc):
                raise
            wait = RETRY_WAIT_S * attempt
            if verbose:
                print(f"  [RETRY]  {what}  attempt {attempt}/{attempts} "
                      f"failed ({type(exc).__name__}) — retrying in "
                      f"{wait:.0f} s")
            time.sleep(wait)


def _fetch_with_retry(fetch, what: str, attempts: int = MAX_RETRIES):
    """Run fetch() with retries; return (result, status).

    status is 'ok', 'nodata' (a valid server answer, returned at once) or
    'error' (after printing what went wrong).
    """
    try:
        return _call_with_retry(fetch, what, attempts), 'ok'
    except Exception as exc:
        if _is_no_data(exc):
            return None, 'nodata'
        print(f"  [ERR]    {what}  {type(exc).__name__}: {exc}")
        return None, 'error'


def _probe_service(client: Client, service: str):
    """Fetch the description (WADL) of one FDSN service directly.

    Returns the service parameters, 'absent' when the server answers that
    the service does not exist (e.g. HTTP 404: IRIS has no event service),
    or None when the request failed for network reasons.
    """
    import urllib.request
    import urllib.error
    from obspy.clients.fdsn.wadl_parser import WADLParser
    try:
        url = client._build_url(service, 'application.wadl')
        headers = dict(getattr(client, 'request_headers', None) or {})
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=20) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        return 'absent' if exc.code in (400, 404, 410, 501) else None
    except Exception:
        return None
    try:
        return WADLParser(data).parameters
    except Exception:
        return None


def _connect(site: str, needed: tuple) -> Client:
    """Create an FDSN client that really offers the needed services.

    obspy discovers a server's services (event / station / dataselect) in
    background threads.  A connection reset during that discovery leaves the
    client silently without that service, and the first query then fails
    with "The current client does not have an event service".  Moreover
    obspy caches that (failed) discovery for the whole process.  So:
      • the services are checked explicitly, and the services found are
        accumulated over several attempts (a flaky server drops a different
        request each time), clearing obspy's cache between attempts;
      • a service still missing is asked for directly: an explicit "does
        not exist" (HTTP 404) stops with a clear message, while a service
        that only could not be reached is assumed to be the standard FDSN
        one (queries have their own retries) instead of aborting the run.
    The tracebacks printed by obspy's background threads are hidden.
    """
    from copy import deepcopy
    from obspy.clients.fdsn.header import DEFAULT_SERVICES

    previous_hook = threading.excepthook
    threading.excepthook = lambda args: None
    found, absent, client, last_error = {}, set(), None, ''
    try:
        for attempt in range(1, CONNECT_RETRIES + 1):
            if attempt > 1:
                cache = getattr(Client, '_Client__service_discovery_cache',
                                None)
                if isinstance(cache, dict):
                    cache.clear()
            try:
                client = Client(site)
                found.update(client.services)
            except ValueError as exc:
                # unknown data-centre name or malformed URL: a config error,
                # retrying cannot help
                print(f"\n\n  [ERROR] {exc}\n          '{site}' is neither a "
                      f"known data-centre name (e.g. INGV, IRIS, GEOFON, "
                      f"ORFEUS) nor a valid FDSN URL: check fdsn_site / "
                      f"fdsn_site_events in the config.\n")
                sys.exit(1)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if client is not None:
                for service in [s for s in needed if s not in found]:
                    params = _probe_service(client, service)
                    if params == 'absent':
                        absent.add(service)
                    elif params is not None:
                        found[service] = params
            missing = [s for s in needed if s not in found and s not in absent]
            if client is not None and (absent or not missing):
                break                     # done, or definitely not offered
            if attempt < CONNECT_RETRIES:
                wait = min(30.0, RETRY_WAIT_S * 2 ** (attempt - 1))
                what = (f"no answer for the {', '.join(missing)} service"
                        if client is not None else f"cannot connect "
                        f"({last_error})")
                print(f"\n  [RETRY]  {site}: {what} — retrying in "
                      f"{wait:.0f} s", end=' ', flush=True)
                time.sleep(wait)
    finally:
        threading.excepthook = previous_hook

    if client is None:
        print(f"\n\n  [ERROR] Cannot connect to {site}: {last_error}")
        print("          Check the internet connection or try again later.\n")
        sys.exit(1)
    if absent:
        print(f"\n\n  [ERROR] {site} does not offer: {', '.join(sorted(absent))}")
        if 'event' in absent:
            print("          For the catalog set fdsn_site_events (e.g. "
                  "\"USGS\") or use a local catalog (existing_catalog_pf).")
        print()
        sys.exit(1)

    for key, value in found.items():
        client.services.setdefault(key, value)
    unreachable = [s for s in needed if s not in found]
    for service in unreachable:
        client.services[service] = deepcopy(DEFAULT_SERVICES[service])
    if unreachable:
        print(f"\n  [WARN] {site}: the {', '.join(unreachable)} service "
              f"description never arrived (network errors) — assuming the "
              f"standard FDSN service.", end=' ')
    return client


def _atomic_write(st, out_path: str) -> None:
    """Write miniSEED to a temp file, then rename into place.

    An interrupted run can never leave a truncated .mseed behind that a
    later run would mistake for complete and skip.
    """
    tmp_path = out_path + '.part'
    try:
        st.write(tmp_path, format='MSEED')
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):        # write failed or was interrupted
            os.remove(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# 4 ─ PREVIEW MAP
# ═════════════════════════════════════════════════════════════════════════════

def _points_from_obspy(cat) -> list:
    """Normalize an obspy Catalog into plain dicts for the preview map."""
    pts = []
    for ev in cat:
        try:
            origin = ev.preferred_origin() or ev.origins[0]
        except IndexError:
            continue
        if origin.latitude is None or origin.longitude is None:
            continue
        try:
            mag = (ev.preferred_magnitude() or ev.magnitudes[0]).mag
        except (IndexError, AttributeError):
            mag = None
        pts.append(dict(
            lat=origin.latitude, lon=origin.longitude,
            depth_km=(origin.depth or 0.0) / 1000.0,
            mag=mag,
            t=origin.time.timestamp,
            time_str=origin.time.strftime('%Y-%m-%d  %H:%M:%S'),
            name='',                  # FDSN events are named only when saved
        ))
    return pts


def _points_from_pyrocko(events) -> list:
    """Normalize pyrocko events (local .pf catalog) for the preview map."""
    return [dict(
        lat=ev.lat, lon=ev.lon,
        depth_km=(ev.depth or 0.0) / 1000.0,
        mag=ev.magnitude,                       # may be None in .pf files
        t=ev.time,
        time_str=util.time_to_str(ev.time)[:19],
        name=ev.name or '',
    ) for ev in events]


# ── Marker size: magnitude ────────────────────────────────────────────────────

_R_MIN_PX  = 4.0         # radius of the smallest event of the catalog (px)
_R_MAX_PX  = 22.0        # upper limit for the largest one (px)
_R_GROWTH  = 2.0         # max radius factor per magnitude unit (area × 4)
_PX_TO_CM  = 2.54 / 96   # screen pixel → cm, for the static pygmt map
_PANEL_PX  = 270         # height of the depth–time panel under the map (px)


def _mag_radius_fn(points):
    """Return (radius(mag) in px, magnitudes to show in the size legend).

    The radius grows exponentially with magnitude, so the marker AREA grows
    by a constant factor per magnitude unit (as the radiated energy does).
    The rate adapts to the catalog — the largest event reaches _R_MAX_PX —
    but radii never grow faster than _R_GROWTH per unit, so a narrow
    magnitude range is not blown up.  Events without magnitude get the
    smallest size (drawn with a dashed outline).
    """
    mags = [p['mag'] for p in points if p['mag'] is not None]
    if not mags:
        return (lambda m: _R_MIN_PX), []
    lo, hi = min(mags), max(mags)
    rate = _R_GROWTH if hi - lo < 1e-6 else min(
        _R_GROWTH, (_R_MAX_PX / _R_MIN_PX) ** (1.0 / (hi - lo)))

    def radius(m):
        return _R_MIN_PX if m is None else _R_MIN_PX * rate ** (m - lo)

    ints = list(range(math.ceil(lo), math.floor(hi) + 1))
    if len(ints) >= 2:
        step = max(1, math.ceil((len(ints) - 1) / 4))     # at most ~5 entries
        legend = [float(i) for i in ints[::step]]
    else:
        legend = sorted({round(lo, 1), round(hi, 1)})
    return radius, legend


# ── Marker colour: depth or origin time ──────────────────────────────────────

# Perceptually uniform colour maps (matplotlib viridis / plasma) as stops
_VIRIDIS = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e',
            '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725']
_PLASMA  = ['#0d0887', '#46039f', '#7201a8', '#9c179e', '#bd3786',
            '#d8576b', '#ed7953', '#fb9f3a', '#fdca26', '#f0f921']


def _colour_scales(points) -> dict:
    """Colour scales for depth and origin time (folium map payload).

    Stops and tick labels run from the top of the colour bar downwards:
      depth : viridis, shallow = yellow (top) → deep = purple.  With 20+
              events the 2nd–98th percentile range is used, so a few
              outliers do not squeeze every other event into one colour;
              the clipped ends are labelled ≤ / ≥.
      time  : plasma, oldest = dark (top) → most recent = bright.
    """
    import numpy as np

    def _range(values, robust, pad):
        v = np.asarray(values, float)
        lo, hi = float(v.min()), float(v.max())
        clip_lo = clip_hi = False
        if robust and v.size >= 20:
            p_lo, p_hi = (float(x) for x in np.percentile(v, [2, 98]))
            clip_lo, clip_hi = p_lo > lo, p_hi < hi
            lo, hi = p_lo, p_hi
        if hi - lo < 1e-9:               # single event or identical values
            lo, hi = lo - pad, hi + pad
        return lo, hi, clip_lo, clip_hi

    def _ticks(lo, hi, n=5):
        return [lo + i * (hi - lo) / (n - 1) for i in range(n)]

    d_lo, d_hi, clip_lo, clip_hi = _range(
        [p['depth_km'] for p in points], True, 0.5)
    span = d_hi - d_lo
    dec  = 2 if span < 1 else (1 if span < 10 else 0)
    d_labels = [f"{x:.{dec}f}" for x in _ticks(d_lo, d_hi)]
    if clip_lo:
        d_labels[0] = '≤ ' + d_labels[0]
    if clip_hi:
        d_labels[-1] = '≥ ' + d_labels[-1]

    t_lo, t_hi, _, _ = _range([p['t'] for p in points], False, 1800.0)
    span = t_hi - t_lo
    fmt  = ('%Y-%m-%d' if span >= 5 * 86400 else
            '%m-%d %H:%M' if span >= 6 * 3600 else '%H:%M:%S')
    t_labels = [util.time_to_str(x, format=fmt) for x in _ticks(t_lo, t_hi)]

    return {
        'depth': dict(lo=d_lo, hi=d_hi, ticks=d_labels, title='Depth (km)',
                      stops=_VIRIDIS[::-1]),
        'time':  dict(lo=t_lo, hi=t_hi, ticks=t_labels,
                      title='Origin time (UTC)', stops=_PLASMA),
    }


_GRID_COLOUR    = '#EF6C00'   # azimuthal selection grid (sectors / rings)
_DROPPED_COLOUR = '#9E9E9E'   # stations dropped by the azimuthal selection
_NODATA_COLOUR  = '#E57373'   # … because they have no data (data check)


def _selection_drawing(selection):
    """Stations dropped by the selection, and the outer grid circle.

    Returns (dropped stations as (net, sta, lat, lon, site) tuples,
    extra circles [(lat, lon, r_km)] to include in the map frame).
    """
    if not selection:
        return [], []
    dropped = [(r['net'], r['sta'], r['lat'], r['lon'], '')
               for r in selection['rows'] if r['status'] != 'selected']
    return dropped, [(selection['lat0'], selection['lon0'],
                      selection['edges'][-1])]


def _dropped_colour(selection, net: str, sta: str) -> str:
    """Grey for stations dropped by the geometry, red for 'no data'."""
    for r in selection['rows']:
        if r['net'] == net and r['sta'] == sta:
            return _NODATA_COLOUR if r['status'] == 'no data' \
                else _DROPPED_COLOUR
    return _DROPPED_COLOUR


def _selection_legend_rows(selection) -> list:
    """Legend rows (HTML) for the dropped stations and the selection grid."""
    if not selection:
        return []
    rows = [f'<span style="color:{_DROPPED_COLOUR};font-size:12px">▲</span>'
            f'&nbsp;Dropped station (cell full / outside rings)']
    if any(r['status'] == 'no data' for r in selection['rows']):
        rows.append(f'<span style="color:{_NODATA_COLOUR};font-size:12px">'
                    f'▲</span>&nbsp;No data — replaced by the next station '
                    f'of its cell')
    rows.append(f'<span style="color:{_GRID_COLOUR}">┄ ┄</span>'
                f'&nbsp;Azimuthal grid ({selection["n_selected"]} of '
                f'{len(selection["rows"])} kept)')
    return rows


def _grid_lines(selection, steps: int = 40):
    """Sector boundaries of the azimuthal grid as great-circle polylines."""
    lat0, lon0, edges = selection['lat0'], selection['lon0'], selection['edges']
    width = 360.0 / selection['n_sectors']
    lines = []
    for k in range(selection['n_sectors']):
        az = k * width
        lines.append((az, [_destination(lat0, lon0, az, edges[0] +
                                        (edges[-1] - edges[0]) * j / steps)
                           for j in range(steps + 1)]))
    return lines


def _map_bounds(ev_points, stations, cfg, event_area, station_area,
                extra_circles=()):
    """(south, west, north, east) enclosing everything drawn on the map."""
    lats, lons = [], []

    def add_circle(lat, lon, r_km):
        dlat = r_km / 111.32
        dlon = dlat / max(math.cos(math.radians(lat)), 0.05)
        lats.extend([lat - dlat, lat + dlat])
        lons.extend([lon - dlon, lon + dlon])

    for p in ev_points or []:
        lats.append(p['lat'])
        lons.append(p['lon'])
    for _, _, lat, lon, _ in stations:
        lats.append(lat)
        lons.append(lon)
    if ev_points is not None and event_area:
        if cfg['area_type'] == 'rectangular':
            lats += [cfg['lat_min'], cfg['lat_max']]
            lons += [cfg['lon_min'], cfg['lon_max']]
        else:
            add_circle(cfg['lat_center'], cfg['lon_center'], cfg['radius_km'])
    for lat, lon, r_km in extra_circles:
        add_circle(lat, lon, r_km)
    if station_area or not lats:
        add_circle(cfg['lat_center_sta'], cfg['lon_center_sta'],
                   cfg['radius_km_sta'])
    return min(lats), min(lons), max(lats), max(lons)


# JavaScript framing of the folium map (see _build_folium_map)
_FIT_BOUNDS_JS = """
{% macro script(this, kwargs) %}
(function () {
  var map = {{ this._parent.get_name() }};
  var bounds = {{ this.bounds }};
  var touched = false;
  ['mousedown', 'touchstart', 'wheel', 'keydown'].forEach(function (ev) {
    map.getContainer().addEventListener(ev, function () { touched = true; },
                                        { passive: true });
  });
  function frame() {
    if (touched) { return; }
    map.invalidateSize();
    map.fitBounds(bounds, { padding: [20, 20], maxZoom: 13 });
  }
  frame();
  window.addEventListener('load', frame);
  map.on('resize', frame);
})();
{% endmacro %}
"""


# JavaScript event layer of the folium map, rendered by a branca MacroElement
# after the map and the "Events" feature group exist.  From a JSON payload
# (see _build_folium_map) it draws:
#   • the event markers on the map
#   • the legend, with the depth / time colour switch
#   • the panel below the map (when payload.panel is true): depth–time plot
#     linked to the map, time-window slider and Play animation
# NB: this is a Jinja template — never write "{#" in the JS.
_EVENT_LAYER_JS = """
{% macro script(this, kwargs) %}
(function () {
  var map = {{ this._parent.get_name() }};
  var group = {{ this.group_name }};
  var cfg = {{ this.payload }};
  /* EV[i] = [lat, lon, depth_km, mag | null, epoch_s, radius_px, time_str, name] */
  var EV = cfg.events;
  var mode = cfg.mode;
  var chart = null, hiRing = null;

  /* ── helpers ──────────────────────────────────────────────────────────── */
  function rgb(hex) {
    return [1, 3, 5].map(function (k) { return parseInt(hex.substr(k, 2), 16); });
  }
  function cmap(stops, x) {
    if (!(x > 0)) { x = 0; }              /* also catches NaN */
    if (x > 1) { x = 1; }
    var n = stops.length - 1;
    var i = Math.min(Math.floor(x * n), n - 1), f = x * n - i;
    var a = rgb(stops[i]), b = rgb(stops[i + 1]);
    return 'rgb(' + [0, 1, 2].map(function (k) {
      return Math.round(a[k] + f * (b[k] - a[k]));
    }).join(',') + ')';
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function colourOf(e) {
    var s = cfg[mode], v = (mode === 'depth') ? e[2] : e[4];
    return cmap(s.stops, (v - s.lo) / (s.hi - s.lo));
  }
  function magText(e) { return (e[3] === null) ? '?' : e[3].toFixed(1); }
  function tipText(e) {
    return 'M ' + magText(e) + ' · ' + e[2].toFixed(1) + ' km · ' + esc(e[6]);
  }
  function fmtTime(t, fmt) {               /* UTC, from epoch seconds */
    var s = new Date(t * 1000).toISOString();
    if (fmt === 'year')  { return s.slice(0, 4); }
    if (fmt === 'month') { return s.slice(0, 7); }
    if (fmt === 'day')   { return s.slice(0, 10); }
    if (fmt === 'hm')    { return s.slice(11, 16); }
    if (fmt === 'dhm')   { return s.slice(5, 10) + ' ' + s.slice(11, 16); }
    return s.slice(0, 10) + ' ' + s.slice(11, 16);
  }
  function svgEl(tag, attrs, parent) {
    var el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) { el.setAttribute(k, attrs[k]); }
    if (parent) { parent.appendChild(el); }
    return el;
  }

  /* ── map markers ──────────────────────────────────────────────────────── */
  var markers = EV.map(function (e, i) {
    var mk = L.circleMarker([e[0], e[1]], {
      radius: e[5], color: '#222', weight: 0.7, opacity: 0.9,
      fillOpacity: 0.85, dashArray: (e[3] === null) ? '3,3' : null
    });
    mk.bindPopup(
      (e[7] ? '<b>' + esc(e[7]) + '</b><br>' : '') +
      esc(e[6]) + ' UTC<br>Magnitude : ' + magText(e) +
      '<br>Depth : ' + e[2].toFixed(2) + ' km' +
      '<br>Lat / Lon : ' + e[0].toFixed(4) + ' / ' + e[1].toFixed(4),
      { maxWidth: 260 });
    mk.bindTooltip(tipText(e));
    mk.on('mouseover', function () { if (chart) { chart.highlight(i); } });
    mk.on('mouseout', function () { if (chart) { chart.highlight(-1); } });
    group.addLayer(mk);
    return mk;
  });

  /* red ring on the map around the event hovered in the panel */
  function ringOn(i) {
    ringOff();
    if (!map.hasLayer(group)) { return; }
    hiRing = L.circleMarker([EV[i][0], EV[i][1]], {
      radius: EV[i][5] + 4, color: '#e53935', weight: 3, fill: false,
      interactive: false
    }).addTo(map);
  }
  function ringOff() {
    if (hiRing) { map.removeLayer(hiRing); hiRing = null; }
  }

  /* ── panel: depth–time plot + time-window slider + animation ──────────── */
  function buildTimeline() {
    var H = cfg.panel_px, SH = H - 40;
    var M = { left: 58, right: 20, top: 10 };
    var CH = SH - 78;                 /* height of the depth–time plot */
    var SY = M.top + CH + 44;         /* centre line of the slider */

    var panel = document.createElement('div');
    panel.style.cssText = 'position:relative;height:' + H + 'px;' +
      'box-sizing:border-box;padding:6px 10px 0;border-top:1px solid #bbb;' +
      'background:#fafafa;font:12px/1.4 sans-serif;user-select:none;' +
      '-webkit-user-select:none';
    var mc = map.getContainer();
    mc.parentNode.insertBefore(panel, mc.nextSibling);

    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:10px;' +
      'height:28px;white-space:nowrap;overflow:hidden';
    bar.innerHTML =
      '<button class="tl-play" style="width:78px;cursor:pointer">▶ Play</button>' +
      '<label>speed <select class="tl-speed">' +
      '<option value="0.5">0.5×</option><option value="1" selected>1×</option>' +
      '<option value="2">2×</option><option value="4">4×</option>' +
      '</select></label>' +
      '<select class="tl-anim" title="Animation type">' +
      '<option value="window">sliding window</option>' +
      '<option value="cumul">cumulative</option></select>' +
      '<button class="tl-reset" style="cursor:pointer">Show all</button>' +
      '<span class="tl-info" style="font-weight:bold"></span>' +
      '<span style="margin-left:auto;color:#777;overflow:hidden;' +
      'text-overflow:ellipsis" title="Drag on the plot or on the slider to ' +
      'choose a time window; double-click the plot to show all events">' +
      'drag to select a time window · double-click: all</span>';
    panel.appendChild(bar);
    var playBtn  = bar.querySelector('.tl-play');
    var speedSel = bar.querySelector('.tl-speed');
    var animSel  = bar.querySelector('.tl-anim');
    var info     = bar.querySelector('.tl-info');

    var svg = svgEl('svg', { height: SH }, panel);
    svg.style.cssText = 'display:block;width:100%;touch-action:none';
    var tip = document.createElement('div');
    tip.style.cssText = 'position:absolute;display:none;pointer-events:none;' +
      'white-space:nowrap;background:rgba(255,255,255,.95);' +
      'border:1px solid #999;border-radius:4px;padding:2px 6px';
    panel.appendChild(tip);

    /* axis ranges (loops, not Math.min.apply: fine for any catalog size) */
    var tMin = Infinity, tMax = -Infinity, dLo = Infinity, dHi = -Infinity;
    EV.forEach(function (e) {
      tMin = Math.min(tMin, e[4]); tMax = Math.max(tMax, e[4]);
      dLo = Math.min(dLo, e[2]);   dHi = Math.max(dHi, e[2]);
    });
    /* margins large enough for the biggest markers at the edges */
    if (tMax - tMin < 60) { tMin -= 1800; tMax += 1800; }
    var D0 = tMin - 0.03 * (tMax - tMin), D1 = tMax + 0.03 * (tMax - tMin);
    if (dHi - dLo < 0.1) { dLo -= 0.5; dHi += 0.5; }
    var dPad = 0.12 * (dHi - dLo);
    dLo -= dPad; dHi += dPad;

    var W = 0, w0 = D0, w1 = D1;      /* svg width, time window */
    var inside = [], dots = [], el = {}, hiDot = null;
    var playing = false, raf = null, lastTs = null, drag = null;

    function PW() { return W - M.left - M.right; }
    function X(t) { return M.left + (t - D0) / (D1 - D0) * PW(); }
    function T(x) { return D0 + (x - M.left) / PW() * (D1 - D0); }
    function Y(d) { return M.top + (d - dLo) / (dHi - dLo) * CH; }
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function setA(node, attrs) {
      for (var k in attrs) { node.setAttribute(k, attrs[k]); }
    }

    function niceStep(span, n) {
      var raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
      var f = raw / mag;
      return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
    }
    function depthTicks() {
      var st = niceStep(dHi - dLo, 4), out = [];
      for (var d = Math.ceil(dLo / st) * st; d <= dHi + 1e-9; d += st) {
        out.push(Math.round(d / st) * st);
      }
      return out;
    }
    function timeTicks() {
      var span = D1 - D0, out = [], i, t;
      var raw = span / Math.max(2, Math.floor(PW() / 110));
      var steps = [60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400,
                   172800, 604800, 1209600];
      for (i = 0; i < steps.length; i++) {
        if (steps[i] >= raw) {
          var st = steps[i];
          var fmt = st >= 86400 ? 'day' : (span < 86400 ? 'hm' : 'dhm');
          for (t = Math.ceil(D0 / st) * st; t <= D1; t += st) {
            out.push({ t: t, label: fmtTime(t, fmt) });
          }
          return out;
        }
      }
      /* months / years: calendar-aligned steps */
      var months = [1, 2, 3, 6, 12, 24, 60, 120], ms = 120;
      for (i = 0; i < months.length; i++) {
        if (months[i] * 2629746 >= raw) { ms = months[i]; break; }
      }
      var d0 = new Date(D0 * 1000);
      var idx = d0.getUTCFullYear() * 12 + d0.getUTCMonth() + 1;
      idx = Math.ceil(idx / ms) * ms;
      for (;; idx += ms) {
        t = Date.UTC(Math.floor(idx / 12), idx % 12, 1) / 1000;
        if (t > D1) { break; }
        out.push({ t: t, label: fmtTime(t, ms >= 12 ? 'year' : 'month') });
      }
      return out;
    }

    function draw() {
      W = svg.getBoundingClientRect().width || (panel.clientWidth - 20);
      W = Math.max(W, M.left + M.right + 100);
      while (svg.firstChild) { svg.removeChild(svg.firstChild); }

      var clip = svgEl('clipPath', { id: 'tl-clip' }, svg);
      svgEl('rect', { x: M.left, y: M.top, width: PW(), height: CH }, clip);
      svgEl('rect', { x: M.left, y: M.top, width: PW(), height: CH,
                      fill: '#fff', stroke: '#999', 'data-role': 'plot' }, svg);
      depthTicks().forEach(function (d) {
        var y = Y(d);
        svgEl('line', { x1: M.left, x2: M.left + PW(), y1: y, y2: y,
                        stroke: '#eee', 'pointer-events': 'none' }, svg);
        svgEl('text', { x: M.left - 6, y: y + 4, 'text-anchor': 'end',
                        'font-size': 11, fill: '#333' }, svg).textContent =
          String(+d.toFixed(3));
      });
      svgEl('text', { x: 14, y: M.top + CH / 2, 'text-anchor': 'middle',
                      'font-size': 11, fill: '#333',
                      transform: 'rotate(-90 14 ' + (M.top + CH / 2) + ')' },
            svg).textContent = 'Depth (km)';
      timeTicks().forEach(function (tk) {
        var x = X(tk.t);
        if (x < M.left || x > M.left + PW()) { return; }
        svgEl('line', { x1: x, x2: x, y1: M.top, y2: M.top + CH,
                        stroke: '#eee', 'pointer-events': 'none' }, svg);
        svgEl('line', { x1: x, x2: x, y1: M.top + CH, y2: M.top + CH + 4,
                        stroke: '#666' }, svg);
        svgEl('text', { x: x, y: M.top + CH + 16, 'text-anchor': 'middle',
                        'font-size': 11, fill: '#333' }, svg).textContent =
          tk.label;
      });
      svgEl('text', { x: M.left + PW(), y: M.top + CH + 29,
                      'text-anchor': 'end', 'font-size': 10, fill: '#777' },
            svg).textContent = 'origin time (UTC)';

      /* events: same order as on the map (biggest first) */
      var g = svgEl('g', { 'clip-path': 'url(#tl-clip)' }, svg);
      dots = EV.map(function (e, i) {
        var c = svgEl('circle', { cx: X(e[4]), cy: Y(e[2]),
                                  r: Math.max(2, 0.7 * e[5]), stroke: '#222',
                                  'stroke-width': 0.6, 'data-role': 'ev',
                                  'data-i': i, style: 'cursor:pointer' }, g);
        if (e[3] === null) { c.setAttribute('stroke-dasharray', '2,2'); }
        return c;
      });

      /* time window: shading outside it, edges, slider */
      var shade = { y: M.top, height: CH, fill: '#777', 'fill-opacity': 0.15,
                    'pointer-events': 'none' };
      el.shL = svgEl('rect', shade, svg);
      el.shR = svgEl('rect', shade, svg);
      var edge = { y1: M.top, y2: M.top + CH, stroke: '#1565C0',
                   'stroke-width': 1.2, 'pointer-events': 'none' };
      el.lnL = svgEl('line', edge, svg);
      el.lnR = svgEl('line', edge, svg);
      svgEl('rect', { x: M.left, y: SY - 3, width: PW(), height: 6, rx: 3,
                      fill: '#d6d6d6', 'data-role': 'track' }, svg);
      el.band = svgEl('rect', { y: SY - 5, height: 10, rx: 4, fill: '#1565C0',
                                'fill-opacity': 0.55, 'data-role': 'band',
                                style: 'cursor:grab' }, svg);
      var handle = { y: SY - 11, width: 10, height: 22, rx: 3, fill: '#fff',
                     stroke: '#1565C0', 'stroke-width': 2,
                     style: 'cursor:ew-resize' };
      el.h0 = svgEl('rect', handle, svg);
      el.h1 = svgEl('rect', handle, svg);
      el.h0.setAttribute('data-role', 'h0');
      el.h1.setAttribute('data-role', 'h1');

      hiDot = null;
      recolour();
      update(true);
    }

    /* show / hide map markers without changing their drawing order */
    function showMarker(i) {
      var p = markers[i]._path;
      if (p) { p.style.display = inside[i] ? '' : 'none'; }
    }
    /* Leaflet recreates the paths when the Events layer is switched on again */
    group.on('add', function () {
      for (var i = 0; i < EV.length; i++) { showMarker(i); }
    });

    function update(force) {
      var x0 = X(w0), x1 = X(w1), L0 = M.left, R0 = M.left + PW();
      setA(el.shL, { x: L0, width: Math.max(0, x0 - L0) });
      setA(el.shR, { x: x1, width: Math.max(0, R0 - x1) });
      setA(el.lnL, { x1: x0, x2: x0 });
      setA(el.lnR, { x1: x1, x2: x1 });
      setA(el.band, { x: x0, width: Math.max(2, x1 - x0) });
      setA(el.h0, { x: x0 - 5 });
      setA(el.h1, { x: x1 - 5 });
      var n = 0;
      for (var i = 0; i < EV.length; i++) {
        var inn = EV[i][4] >= w0 && EV[i][4] <= w1;
        if (inn) { n++; }
        if (force || inn !== inside[i]) {
          inside[i] = inn;
          dots[i].setAttribute('fill-opacity', inn ? 0.85 : 0.12);
          dots[i].setAttribute('stroke-opacity', inn ? 0.9 : 0.2);
          showMarker(i);
        }
      }
      var all = (w0 <= D0 && w1 >= D1);
      var fmt = (D1 - D0 >= 3 * 86400) ? 'day' : 'full';
      info.textContent = (all ? 'whole catalog' :
        fmtTime(w0, fmt) + ' → ' + fmtTime(w1, fmt)) +
        '  ·  ' + n + ' / ' + EV.length + ' events';
    }

    function recolour() {
      dots.forEach(function (c, i) { c.setAttribute('fill', colourOf(EV[i])); });
    }

    function highlight(i) {
      if (hiDot) { hiDot.parentNode.removeChild(hiDot); hiDot = null; }
      if (i < 0 || !dots[i]) { return; }
      hiDot = svgEl('circle', { cx: X(EV[i][4]), cy: Y(EV[i][2]),
                                r: Math.max(2, 0.7 * EV[i][5]) + 3,
                                fill: 'none', stroke: '#e53935',
                                'stroke-width': 2, 'pointer-events': 'none' },
                    svg);
    }

    function openEvent(i) {
      if (!map.hasLayer(group)) { return; }
      var ll = markers[i].getLatLng();
      if (!map.getBounds().contains(ll)) { map.panTo(ll); }
      markers[i].openPopup();
    }

    function showAll() { stop(); w0 = D0; w1 = D1; update(false); }

    /* ── animation ── */
    function play() {
      var span = D1 - D0;
      if (animSel.value === 'window') {
        var width = w1 - w0;
        if (width > 0.9 * span) { width = span / 10; w1 = D1; }
        if (w1 >= D1) { w0 = D0; w1 = D0 + width; }   /* (re)start */
      } else {
        /* (re)start from the first event, then add events as time passes */
        if (w1 >= D1 || w1 - D0 > 0.9 * span) { w1 = tMin; }
        w0 = D0;
      }
      playing = true;
      playBtn.textContent = '❚❚ Pause';
      lastTs = null;
      update(false);
      raf = requestAnimationFrame(step);
    }
    function step(ts) {
      if (!playing) { return; }
      if (lastTs !== null) {
        /* the whole time span is crossed in 15 s at speed 1× */
        var dt = (ts - lastTs) / 1000 * parseFloat(speedSel.value) *
                 (D1 - D0) / 15;
        var width = w1 - w0;
        w1 = Math.min(D1, w1 + dt);
        if (animSel.value === 'window') { w0 = w1 - width; }
        update(false);
        if (w1 >= D1) { stop(); return; }
      }
      lastTs = ts;
      raf = requestAnimationFrame(step);
    }
    function stop() {
      playing = false;
      if (raf) { cancelAnimationFrame(raf); raf = null; }
      playBtn.textContent = '▶ Play';
    }
    playBtn.addEventListener('click', function () {
      if (playing) { stop(); } else { play(); }
    });
    bar.querySelector('.tl-reset').addEventListener('click', showAll);

    /* ── mouse: drag handles / window, brush on the plot, click an event ── */
    function svgX(ev) { return ev.clientX - svg.getBoundingClientRect().left; }
    svg.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0) { return; }
      stop();
      var role = ev.target.getAttribute('data-role') || 'plot';
      drag = { role: role, x: svgX(ev), w0: w0, w1: w1, moved: false,
               i: +ev.target.getAttribute('data-i') };
      svg.setPointerCapture(ev.pointerId);
      if (role === 'band') { el.band.style.cursor = 'grabbing'; }
      tip.style.display = 'none';
      ev.preventDefault();
    });
    svg.addEventListener('pointermove', function (ev) {
      if (!drag) { return; }
      var x = svgX(ev), minW = (D1 - D0) / 400;
      if (Math.abs(x - drag.x) > 3) { drag.moved = true; }
      if (!drag.moved) { return; }
      if (drag.role === 'h0') {
        w0 = clamp(T(x), D0, w1 - minW);
      } else if (drag.role === 'h1') {
        w1 = clamp(T(x), w0 + minW, D1);
      } else if (drag.role === 'band') {
        var width = drag.w1 - drag.w0;
        w0 = clamp(drag.w0 + T(x) - T(drag.x), D0, D1 - width);
        w1 = w0 + width;
      } else {                  /* plot, event or slider track: new window */
        var a = clamp(T(drag.x), D0, D1), b = clamp(T(x), D0, D1);
        w0 = Math.min(a, b);
        w1 = Math.min(D1, Math.max(a, b, w0 + minW));
      }
      update(false);
    });
    svg.addEventListener('pointerup', function () {
      if (!drag) { return; }
      if (!drag.moved && drag.role === 'ev') { openEvent(drag.i); }
      el.band.style.cursor = 'grab';
      drag = null;
    });
    svg.addEventListener('pointercancel', function () { drag = null; });
    svg.addEventListener('dblclick', showAll);

    /* ── hover: tooltip in the panel + ring on the map ── */
    svg.addEventListener('mouseover', function (ev) {
      if (drag || ev.target.getAttribute('data-role') !== 'ev') { return; }
      var i = +ev.target.getAttribute('data-i');
      highlight(i);
      ringOn(i);
      tip.innerHTML = tipText(EV[i]);
      tip.style.display = 'block';
      var pr = panel.getBoundingClientRect();
      tip.style.left = Math.max(0, Math.min(ev.clientX - pr.left + 12,
                                            pr.width - tip.offsetWidth - 4)) + 'px';
      tip.style.top = Math.max(0, ev.clientY - pr.top - 32) + 'px';
    });
    svg.addEventListener('mouseout', function (ev) {
      if (ev.target.getAttribute('data-role') !== 'ev') { return; }
      highlight(-1);
      ringOff();
      tip.style.display = 'none';
    });

    /* redraw when the window size changes (and once the page is laid out) */
    var pending = false;
    function redraw() {
      if (pending) { return; }
      pending = true;
      requestAnimationFrame(function () { pending = false; draw(); });
    }
    window.addEventListener('resize', redraw);
    window.addEventListener('load', redraw);
    draw();

    return { highlight: highlight, recolour: recolour };
  }

  if (cfg.panel) { chart = buildTimeline(); }

  function colourbar(mode) {
    var s = cfg[mode], H = 120, n = s.ticks.length;
    var h = '<div style="margin-top:8px"><b>' + s.title + '</b></div>' +
      '<div style="position:relative;width:160px;height:' + (H + 14) + 'px">' +
      '<div style="position:absolute;left:0;top:7px;width:14px;height:' + H +
      'px;border:1px solid #888;background:linear-gradient(to bottom,' +
      s.stops.join(',') + ')"></div>';
    s.ticks.forEach(function (lab, i) {
      var y = 7 + i * H / (n - 1);
      h += '<div style="position:absolute;left:15px;top:' + y +
           'px;width:5px;border-top:1px solid #555"></div>' +
           '<div style="position:absolute;left:24px;top:' + (y - 9) +
           'px;white-space:nowrap">' + esc(lab) + '</div>';
    });
    return h + '</div>';
  }

  function sizeLegend() {
    function item(r, label, dashed) {
      var d = 2 * r + 2;
      return '<div style="text-align:center">' +
        '<svg width="' + d + '" height="' + d + '"><circle cx="' + (r + 1) +
        '" cy="' + (r + 1) + '" r="' + r + '" fill="#cfcfcf" stroke="#222"' +
        ' stroke-width="0.7"' + (dashed ? ' stroke-dasharray="3,3"' : '') +
        '/></svg><div>' + label + '</div></div>';
    }
    var h = '<div style="margin-top:8px"><b>Magnitude</b></div>' +
      '<div style="display:flex;align-items:flex-end;gap:10px;margin-top:2px">';
    cfg.sizes.forEach(function (s) { h += item(s[1], 'M ' + s[0], false); });
    if (cfg.unknown_mag) { h += item(cfg.r_min, 'M ?', true); }
    return h + '</div>';
  }

  var legend = L.control({ position: 'bottomleft' });
  legend.onAdd = function () {
    var div = L.DomUtil.create('div');
    div.style.cssText = 'background:white;padding:10px 14px;border-radius:8px;' +
      'border:1px solid #ccc;font:12px/1.5 sans-serif;' +
      'overflow-y:auto;box-shadow:2px 2px 6px rgba(0,0,0,.2)';
    div.innerHTML = '<b>Colour events by</b><br>' +
      '<label style="cursor:pointer"><input type="radio" name="evcolour"' +
      ' value="depth"> depth</label>&nbsp;&nbsp;' +
      '<label style="cursor:pointer"><input type="radio" name="evcolour"' +
      ' value="time"> origin time</label>' +
      '<div class="evcolourbar"></div>' + sizeLegend() + cfg.extra;
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);
    return div;
  };
  legend.addTo(map);

  var box = legend.getContainer();
  /* keep the legend inside the map, which is shorter when the panel is on */
  function fitLegend() {
    box.style.maxHeight = Math.max(120, map.getSize().y - 30) + 'px';
  }
  fitLegend();
  map.on('resize', fitLegend);

  function setMode(m) {
    mode = m;
    markers.forEach(function (mk, i) {
      mk.setStyle({ fillColor: colourOf(EV[i]) });
    });
    if (chart) { chart.recolour(); }
    box.querySelector('.evcolourbar').innerHTML = colourbar(mode);
    box.querySelector('input[value="' + mode + '"]').checked = true;
  }
  box.querySelectorAll('input[name="evcolour"]').forEach(function (inp) {
    inp.addEventListener('change', function () { setMode(this.value); });
  });
  setMode(cfg.mode);
})();
{% endmacro %}
"""


def _build_folium_map(ev_points, inv, cfg: dict, event_area: bool = True,
                      station_area: bool = True, selection=None):
    """Build the folium map.

    ev_points    : list of normalized event dicts, or None in continuous mode
    event_area   : draw the configured event search area (False when the
                   catalog comes from a local file — the area does not apply)
    station_area : draw the station search area (False when the stations
                   come from a local file)
    selection    : report of the azimuthal selection (None when off): the
                   grid and the dropped stations are drawn as well

    Events are drawn by a JavaScript layer (_EVENT_LAYER_JS): size scales
    with magnitude, colour shows depth or origin time (switch in the legend).
    Under the map a panel shows depth vs time, linked to the map, with a
    time-window slider and a Play animation.  Drawing in JavaScript also
    keeps the HTML light for catalogs with thousands of events (no
    per-event folium objects).
    """
    import folium
    from branca.element import MacroElement
    from jinja2 import Template

    is_continuous = (ev_points is None)
    stations = _unique_stations(inv)
    dropped, extra = _selection_drawing(selection)
    south, west, north, east = _map_bounds(ev_points, stations + dropped, cfg,
                                           event_area, station_area, extra)
    sel_info = ({(r['net'], r['sta']): r for r in selection['rows']}
                if selection else {})

    # Base layers (switchable from the layer panel, top right).  All of these
    # are free and need no API key.  Only OpenStreetMap has show=True: folium
    # would otherwise display the LAST layer added at start-up.
    # zoom_snap: fractional zoom levels, so that the framing is tight also
    # for large areas (e.g. a 1000 km station ring)
    m = folium.Map(location=[(south + north) / 2, (west + east) / 2],
                   zoom_start=9, tiles=None, zoom_snap=0.25)
    if ev_points:
        # Leave room under the map for the depth–time panel
        m.get_root().header.add_child(folium.Element(
            f"<style>#{m.get_name()} {{ height: calc(100% - {_PANEL_PX}px) "
            f"!important; }}</style>"))
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(m)
    folium.TileLayer(
        tiles=('https://server.arcgisonline.com/ArcGIS/rest/services/'
               'World_Imagery/MapServer/tile/{z}/{y}/{x}'),
        attr='Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics',
        name='Satellite (Esri)', show=False,
    ).add_to(m)
    folium.TileLayer(
        tiles='https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        attr=('Map data &copy; OpenStreetMap contributors, SRTM | '
              'Map style &copy; OpenTopoMap (CC-BY-SA)'),
        name='Topographic (OpenTopoMap)', show=False,
        max_zoom=17,
    ).add_to(m)
    folium.TileLayer(
        tiles=('https://server.arcgisonline.com/ArcGIS/rest/services/'
               'World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}'),
        attr='Tiles &copy; Esri &mdash; Source: Esri',
        name='Shaded relief (Esri)', show=False,
        max_zoom=13,
    ).add_to(m)

    # ── event search area boundary (FDSN event query only) ────────────────────
    if not is_continuous and event_area:
        if cfg['area_type'] == 'rectangular':
            folium.Rectangle(
                bounds=[[cfg['lat_min'], cfg['lon_min']],
                        [cfg['lat_max'], cfg['lon_max']]],
                color='#607D8B', weight=2, dash_array='6',
                fill=False, tooltip='Event search area',
            ).add_to(m)
        else:
            folium.Circle(
                location=[cfg['lat_center'], cfg['lon_center']],
                radius=cfg['radius_km'] * 1000,
                color='#607D8B', weight=2, dash_array='6',
                fill=False, tooltip='Event search area',
            ).add_to(m)

    # ── station search area boundary (FDSN station query only) ────────────────
    if station_area:
        for r_km in (cfg['radius_km_sta_min'], cfg['radius_km_sta']):
            if r_km > 0:
                folium.Circle(
                    location=[cfg['lat_center_sta'], cfg['lon_center_sta']],
                    radius=r_km * 1000,
                    color='#1565C0', weight=2, dash_array='4',
                    fill=False, tooltip=f'Station search area ({r_km:g} km)',
                ).add_to(m)

    # ── azimuthal selection grid: sector boundaries and ring edges ────────────
    if selection:
        grid = folium.FeatureGroup(name='Azimuthal grid')
        if selection['rings_given']:
            for edge in selection['edges']:
                if edge > 0:
                    folium.Circle(
                        location=[selection['lat0'], selection['lon0']],
                        radius=edge * 1000, color=_GRID_COLOUR, weight=1.8,
                        opacity=0.9, dash_array='5,6', fill=False,
                        tooltip=f'Ring edge {edge:g} km',
                    ).add_to(grid)
        for az, pts in _grid_lines(selection):
            folium.PolyLine(pts, color=_GRID_COLOUR, weight=1.8, opacity=0.9,
                            dash_array='5,6',
                            tooltip=f'Sector boundary {az:g}°').add_to(grid)
        grid.add_to(m)

    # ── events: size = magnitude, colour = depth / time (JavaScript layer) ────
    if ev_points:
        radius, legend_mags = _mag_radius_fn(ev_points)
        ev_group = folium.FeatureGroup(
            name=f'Events ({len(ev_points)})').add_to(m)
        # Biggest events first, so that smaller ones stay visible on top
        order = sorted(ev_points, key=lambda p: -radius(p['mag']))
        rows = (['<span style="color:#1565C0;font-size:15px">▲</span>'
                 '&nbsp;Station'] if stations or dropped else [])
        if event_area:
            rows.append('<span style="color:#607D8B">─ ─</span>'
                        '&nbsp;Event search area')
        if station_area:
            rows.append('<span style="color:#1565C0">─ ─</span>'
                        '&nbsp;Station search area')
        rows += _selection_legend_rows(selection)
        payload = dict(
            mode=cfg['map_color_by'],
            events=[[p['lat'], p['lon'], round(p['depth_km'], 3), p['mag'],
                     p['t'], round(radius(p['mag']), 2), p['time_str'],
                     p['name']] for p in order],
            sizes=[[f"{v:g}", round(radius(v), 2)] for v in legend_mags],
            unknown_mag=any(p['mag'] is None for p in ev_points),
            r_min=_R_MIN_PX,
            panel=True,
            panel_px=_PANEL_PX,
            extra='<div style="margin-top:10px">' + '<br>'.join(rows) + '</div>',
            **_colour_scales(ev_points),
        )
        layer = MacroElement()
        layer._template = Template(_EVENT_LAYER_JS)
        layer.group_name = ev_group.get_name()
        # "</" inside a string would close the <script> block early
        layer.payload = json.dumps(payload).replace('</', '<\\/')
        layer.add_to(m)

    # ── stations (CSS triangle markers, drawn above the events) ──────────────
    def triangle_icon(colour, half):
        # Upward-pointing triangle via CSS border trick
        return folium.DivIcon(
            html=(f'<div style="width:0;height:0;'
                  f'border-left:{half}px solid transparent;'
                  f'border-right:{half}px solid transparent;'
                  f'border-bottom:{2 * half}px solid {colour};"></div>'),
            icon_size=(2 * half, 2 * half),
            icon_anchor=(half, 2 * half),
        )

    def station_popup(net_code, sta_code, lat, lon, site):
        r = sel_info.get((net_code, sta_code))
        geo = (f"<br>Distance : {r['dist_km']:.0f} km<br>"
               f"Azimuth : {r['az']:.0f}°" if r else '')
        if r and r.get('data_txt', '-') != '-':
            geo += f"<br>Data : {r['data_txt']}"
        why = (f"<br><i>dropped: {r['status']}</i>"
               if r and r['status'] != 'selected' else '')
        return folium.Popup(f"<b>{net_code}.{sta_code}</b><br>{site or ''}<br>"
                            f"Lat / Lon : {lat:.4f} / {lon:.4f}{geo}{why}",
                            max_width=220)

    if dropped:          # drawn first, so the selected ones stay on top
        drop_group = folium.FeatureGroup(
            name=f'Dropped stations ({len(dropped)})')
        for net_code, sta_code, lat, lon, site in dropped:
            colour = _dropped_colour(selection, net_code, sta_code)
            why = 'no data' if colour == _NODATA_COLOUR else 'dropped'
            folium.Marker(
                location=[lat, lon], icon=triangle_icon(colour, 5),
                popup=station_popup(net_code, sta_code, lat, lon, site),
                tooltip=f"{net_code}.{sta_code} ({why})",
            ).add_to(drop_group)
        drop_group.add_to(m)

    sta_group = folium.FeatureGroup(name=f'Stations ({len(stations)})')
    for net_code, sta_code, lat, lon, site in stations:
        folium.Marker(
            location=[lat, lon], icon=triangle_icon('#1565C0', 8),
            popup=station_popup(net_code, sta_code, lat, lon, site),
            tooltip=f"{net_code}.{sta_code}",
        ).add_to(sta_group)
    sta_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Frame everything drawn (events, stations, areas).  Done in JavaScript
    # rather than with m.fit_bounds(): a one-off fit at script time uses
    # whatever size the window has at that instant (wrong in a background
    # tab or while the window is still opening), so the fit is repeated on
    # page load and on resize until the user moves the map.
    framing = MacroElement()
    framing._template = Template(_FIT_BOUNDS_JS)
    framing.bounds = json.dumps([[south, west], [north, east]])
    framing.add_to(m)

    # ── no events (continuous / stations modes): info panel ───────────────────
    # (the event modes have the JavaScript legend instead)
    if is_continuous:
        area_row = ('<br><span style="color:#1565C0">─ ─</span>'
                    '&nbsp;Station search area' if station_area else '')
        area_row += ''.join('<br>' + row
                            for row in _selection_legend_rows(selection))
        if cfg['download_mode'] == 'continuous':
            n_files = len(stations) * len(_continuous_chunks(cfg))
            info = (f"<b>Continuous download</b><br>"
                    f"{cfg['tmin'][:10]} → {cfg['tmax'][:10]}<br>"
                    f"Stations  : {len(stations)}<br>"
                    f"Chunk     : {cfg['chunk_hours']} h / file<br>"
                    f"Est. files: ~{n_files}<br>")
        else:
            of = (f" (of {len(selection['rows'])} candidates)"
                  if selection else '')
            info = (f"<b>Station metadata</b><br>"
                    f"Stations  : {len(stations)}{of}<br>"
                    f"Channel   : {cfg['channel']}<br>")
        panel_html = f"""
    <div style="
        position: fixed; bottom: 30px; left: 30px; z-index: 1000;
        background: white; padding: 12px 16px; border-radius: 8px;
        border: 1px solid #ccc; font-size: 12px; line-height: 1.9;
        box-shadow: 2px 2px 6px rgba(0,0,0,.2);">
      {info}
      <span style="color:#1565C0;font-size:16px">▲</span>&nbsp;Station{area_row}
    </div>"""
        m.get_root().html.add_child(folium.Element(panel_html))

    return m


def _build_pygmt_map(ev_points, inv, cfg: dict, event_area: bool = True,
                     station_area: bool = True, show: bool = True,
                     selection=None):
    """Static fallback map.  ev_points=None signals continuous mode.

    Same conventions as the folium map: size scales with magnitude, colour
    shows depth or time (config key map_color_by), with a colour bar, and a
    depth–time panel under the map (no time slider: the image is static).
    """
    import pygmt
    import numpy as np

    stations = _unique_stations(inv)
    dropped, extra = _selection_drawing(selection)
    south, west, north, east = _map_bounds(ev_points, stations + dropped, cfg,
                                           event_area, station_area, extra)
    pad    = max(0.05, 0.05 * max(north - south, east - west))
    region = [west - pad, east + pad, south - pad, north + pad]

    fig = pygmt.Figure()
    fig.basemap(region=region, projection='M15c', frame='a')
    fig.coast(land='gray90', water='lightblue',
              shorelines='1/0.4p,black',
              resolution='h' if north - south < 5 else 'i')

    def circle(lat, lon, r_km, pen):
        # geodesic circle: exact also for radii of hundreds of km
        pts = [_destination(lat, lon, a, r_km) for a in range(0, 361, 2)]
        fig.plot(x=[p[1] for p in pts], y=[p[0] for p in pts], pen=pen)

    # Search areas (only those that were actually used for a query)
    if ev_points is not None and event_area:
        if cfg['area_type'] == 'rectangular':
            fig.plot(
                x=[cfg['lon_min'], cfg['lon_max'],
                   cfg['lon_max'], cfg['lon_min'], cfg['lon_min']],
                y=[cfg['lat_min'], cfg['lat_min'],
                   cfg['lat_max'], cfg['lat_max'], cfg['lat_min']],
                pen='1p,gray50,dashed',
            )
        else:
            circle(cfg['lat_center'], cfg['lon_center'], cfg['radius_km'],
                   '1p,gray50,dashed')
    if station_area:
        for r_km in (cfg['radius_km_sta_min'], cfg['radius_km_sta']):
            if r_km > 0:
                circle(cfg['lat_center_sta'], cfg['lon_center_sta'], r_km,
                       '1p,royalblue,dashed')

    # Azimuthal selection grid and the stations it dropped
    if selection:
        grid_pen = f'0.6p,{_GRID_COLOUR},dotted'
        if selection['rings_given']:
            for edge in selection['edges']:
                if edge > 0:
                    circle(selection['lat0'], selection['lon0'], edge,
                           grid_pen)
        for _, pts in _grid_lines(selection):
            fig.plot(x=[p[1] for p in pts], y=[p[0] for p in pts],
                     pen=grid_pen)
        for colour in (_DROPPED_COLOUR, _NODATA_COLOUR):
            group = [s for s in dropped
                     if _dropped_colour(selection, s[0], s[1]) == colour]
            if group:
                fig.plot(x=[s[3] for s in group], y=[s[2] for s in group],
                         style='t0.2c', fill=colour, pen='0.3p,gray40')

    # Events: biggest first so that smaller ones stay visible on top
    if ev_points:
        radius, _ = _mag_radius_fn(ev_points)
        pts = sorted(ev_points, key=lambda p: -radius(p['mag']))
        # Same colour ranges as the folium map (robust depth range included)
        scale = _colour_scales(pts)[cfg['map_color_by']]
        lo, hi = scale['lo'], scale['hi']
        if cfg['map_color_by'] == 'depth':
            vals  = [p['depth_km'] for p in pts]
            label = 'Depth (km)'
        else:
            t0    = lo
            vals  = [(p['t'] - t0) / 86400.0 for p in pts]
            lo, hi = 0.0, (hi - t0) / 86400.0
            label = 'Days since ' + util.time_to_str(t0, format='%Y-%m-%d')
        # background=True: values beyond a clipped end take the end colour
        pygmt.makecpt(cmap='viridis' if cfg['map_color_by'] == 'depth'
                      else 'plasma', series=[lo, hi], background=True,
                      reverse=(cfg['map_color_by'] == 'depth'))
        fig.plot(x=[p['lon'] for p in pts], y=[p['lat'] for p in pts],
                 size=[2 * radius(p['mag']) * _PX_TO_CM for p in pts],
                 fill=vals, cmap=True, style='cc', pen='0.3p,gray20')
        # Triangles at the colour-bar ends that were clipped (≤ / ≥)
        ends = (('b' if scale['ticks'][0].startswith('≤') else '') +
                ('f' if scale['ticks'][-1].startswith('≥') else ''))
        fig.colorbar(position='JBC+e' + ends if ends else 'JBC',
                     frame=['af', f'x+l"{label}"'])

    # Stations
    if stations:
        fig.plot(x=[s[3] for s in stations], y=[s[2] for s in stations],
                 style='t0.35c', fill='royalblue', pen='0.5p,navy')

    # Depth–time panel under the map and its colour bar (same sizes and
    # colours as the map; depth increases downwards)
    if ev_points:
        t_lo  = min(p['t'] for p in pts)
        t_hi  = max(p['t'] for p in pts)
        # margins large enough for the biggest markers at the edges
        t_pad = max(1800.0, 0.04 * (t_hi - t_lo))
        depths = [p['depth_km'] for p in pts]
        d_lo, d_hi = min(depths), max(depths)
        d_pad = max(0.2, 0.15 * (d_hi - d_lo))
        iso   = lambda t: util.time_to_str(t, format='%Y-%m-%dT%H:%M:%S')
        fig.shift_origin(yshift='-7c')
        fig.basemap(region=[iso(t_lo - t_pad), iso(t_hi + t_pad),
                            d_lo - d_pad, d_hi + d_pad],
                    projection='X15c/-4c',
                    frame=['WSen', 'xaf+l"Origin time (UTC)"',
                           'yaf+l"Depth (km)"'])
        fig.plot(x=np.array([np.datetime64(int(round(p['t'] * 1000)), 'ms')
                             for p in pts]),
                 y=depths,
                 size=[2 * max(2.0, 0.7 * radius(p['mag'])) * _PX_TO_CM
                       for p in pts],
                 fill=vals, cmap=True, style='cc', pen='0.3p,gray20')

    if show:
        fig.show()
    return fig


def show_preview_map(ev_points, inv, cfg: dict, event_area: bool = True,
                     station_area: bool = True, selection=None) -> None:
    """Display the preview map; tries folium first, then pygmt.

    ev_points    : normalized event dicts (see _points_from_*), or None in
                   continuous mode
    event_area   : draw the event search area (False for a local .pf)
    station_area : draw the station search area (False for a local XML)
    selection    : azimuthal selection report, or None when it is off
    """
    backend = cfg['map_backend']

    if backend == 'folium':
        try:
            m = _build_folium_map(ev_points, inv, cfg, event_area,
                                  station_area, selection)
            tmp = tempfile.NamedTemporaryFile(
                suffix='.html', delete=False,
                prefix='seismic_preview_',
            )
            tmp.close()   # release handle before folium writes to the path
            m.save(tmp.name)
            print(f"  Map saved to: {tmp.name}")
            # macOS: use the native 'open' command (webbrowser.open is unreliable
            # for file:// URLs when launched from a terminal)
            if platform.system() == 'Darwin':
                subprocess.run(['open', tmp.name])
            else:
                webbrowser.open(f'file://{tmp.name}')
            return
        except ImportError:
            print("  [WARN] folium not installed – falling back to pygmt.")
            backend = 'pygmt'

    if backend == 'pygmt':
        try:
            _build_pygmt_map(ev_points, inv, cfg, event_area, station_area,
                             selection=selection)
            return
        except ImportError:
            print("  [WARN] pygmt not installed either. No map shown.")


# ═════════════════════════════════════════════════════════════════════════════
# 5 ─ SAVE CATALOG
# ═════════════════════════════════════════════════════════════════════════════

def _obspy_ev_to_pyrocko(ev, label: str) -> model.Event | None:
    """Convert an obspy Event to a pyrocko model.Event.

    The event name follows the convention:  <label>_yyyy_mm_dd_hh_mm_ss
    which is also used as the DATA subfolder name and waveform file prefix.
    """
    try:
        origin = ev.preferred_origin() or ev.origins[0]
    except IndexError:
        return None
    if origin.latitude is None or origin.longitude is None:
        return None

    try:
        mag = (ev.preferred_magnitude() or ev.magnitudes[0]).mag
    except (IndexError, AttributeError):
        mag = None

    # Both obspy and pyrocko count seconds since 1970-01-01 UTC
    ptime = origin.time.timestamp

    return model.Event(
        name=_event_name_from_time(label, ptime),
        time=ptime,
        lat=float(origin.latitude),
        lon=float(origin.longitude),
        depth=float(origin.depth) if origin.depth is not None else 0.0,
        magnitude=float(mag) if mag is not None else None,
    )


def save_catalog(cat: Catalog, cfg: dict) -> list:
    """Save catalog in QuakeML, Pyrocko .pf and plain-text formats.

    Returns the list of pyrocko model.Event objects (used for waveform naming).
    """
    os.makedirs(CAT_DIR, exist_ok=True)
    base  = os.path.join(CAT_DIR, cfg['catalog_name'])
    label = cfg['event_label']

    # ── QuakeML (.xml) ───────────────────────────────────────────────────────
    xml_path = base + '.xml'
    cat.write(xml_path, format='QUAKEML')
    print(f"  Saved: {xml_path}")

    # ── Pyrocko basic format (.pf) ───────────────────────────────────────────
    pf_events = []
    for ev in cat:
        pev = _obspy_ev_to_pyrocko(ev, label)
        if pev is not None:
            pf_events.append(pev)
    pf_events.sort(key=lambda e: e.time)
    _dedupe_event_names(pf_events)

    pf_path = base + '.pf'
    model.dump_events(pf_events, pf_path)   # default format='basic'
    print(f"  Saved: {pf_path}")

    # ── Human-readable table (.txt) ──────────────────────────────────────────
    txt_path = base + '.txt'
    with open(txt_path, 'w') as fh:
        header = (f"{'#':>5}  {'Time (UTC)':23}  {'Lat':>9}  {'Lon':>9}  "
                  f"{'Depth(km)':>9}  {'Mag':>5}  Name\n")
        fh.write(header)
        fh.write('─' * (len(header) - 1) + '\n')
        for i, pev in enumerate(pf_events, 1):
            t   = util.time_to_str(pev.time)
            dep = pev.depth / 1000.0 if pev.depth is not None else 0.0
            mag = f"{pev.magnitude:.2f}" if pev.magnitude is not None else '   –'
            fh.write(f"{i:>5}  {t:23}  {pev.lat:>9.4f}  {pev.lon:>9.4f}  "
                     f"{dep:>9.2f}  {mag:>5}  {pev.name}\n")
    print(f"  Saved: {txt_path}")

    return pf_events


# ═════════════════════════════════════════════════════════════════════════════
# 6 ─ SAVE STATION METADATA
# ═════════════════════════════════════════════════════════════════════════════

# ── Output names already in use: overwrite or choose another name ────────────

def _catalog_set(name: str) -> list:
    """Every file of a catalog saved under this name."""
    return [os.path.join(CAT_DIR, name + ext) for ext in ('.xml', '.txt', '.pf')]


def _station_set(name: str) -> list:
    """Every station file this script may have written under this name."""
    base = os.path.join(META_DIR, name)
    files = [base + '.xml', base + '_all.xml', base + '_selection.txt']
    files += sorted(glob.glob(os.path.join(glob.escape(base),
                                           glob.escape(name) + '_*.xml')))
    return files


def _resolve_name(kind: str, cfg: dict, key: str, set_fn, protected: set):
    """Make sure the output name cfg[key] can be written.

    If files of that name already exist, ask whether to overwrite them or to
    use another name (the new name is used for this run only).  A name that
    would overwrite one of the input files (protected) is always refused.
    Returns the existing files to delete before saving — so that no stale
    file of the old set survives — or None if the user aborts.
    """
    while True:
        name     = cfg[key]
        files    = set_fn(name)
        hit      = [f for f in files if os.path.abspath(f) in protected]
        existing = [f for f in files if os.path.exists(f)]
        if hit:
            print(f"\n  [!] The {kind} name '{name}' would overwrite the "
                  f"input file {os.path.relpath(hit[0], WORK_DIR)}.")
        elif not existing:
            return []
        else:
            print(f"\n  [EXISTS] {kind} '{name}' is already on disk:")
            for f in existing[:6]:
                print(f"           {os.path.relpath(f, WORK_DIR)}")
            if len(existing) > 6:
                print(f"           … and {len(existing) - 6} more")
            ans = input("  Overwrite it? [y = overwrite / n = save under "
                        "another name]: ").strip().lower()
            if ans == 'y':
                return existing
        while True:
            new = input(f"  New {kind} name (empty = abort): ").strip()
            if not new:
                return None
            if '/' in new or os.sep in new or new in ('.', '..'):
                print("  ! Please type a plain name, not a path.")
                continue
            break
        cfg[key] = new
        print(f"  → this run will use '{new}' "
              f"(the config file is not changed)")


def resolve_output_names(cfg: dict, save_cat: bool, save_sta: bool):
    """Check catalog and station output names before anything is written.

    Returns the list of old files to delete, or None if the user aborted.
    """
    protected = set()
    for key, base in (('existing_catalog_pf', CAT_DIR),
                      ('existing_stations_xml', META_DIR)):
        if cfg.get(key):
            protected.add(os.path.abspath(_resolve_local_path(cfg[key], base)))
    to_delete = []
    for wanted, kind, key, set_fn in (
            (save_cat, 'catalog', 'catalog_name', _catalog_set),
            (save_sta, 'station set', 'station_file_name', _station_set)):
        if not wanted:
            continue
        old = _resolve_name(kind, cfg, key, set_fn, protected)
        if old is None:
            return None
        to_delete += old
    return to_delete


def remove_old_outputs(files: list) -> None:
    """Delete the files of an output set that is being overwritten."""
    for f in files:
        if os.path.isfile(f):
            os.remove(f)
    if files:
        print(f"  Removed {len(files)} old file(s) being overwritten.")


def save_station_metadata(inv, inv_all, selection, cfg: dict,
                          local_sta: bool) -> None:
    """Save the station metadata of this run and the selection report.

    FDSN stations: StationXML (+ per-station files); with the azimuthal
    selection also <name>_all.xml with every candidate.  Local StationXML:
    the file itself is never copied; with the selection on, the SELECTED
    stations are written to <name>.xml (they are a new subset of it).
    """
    if not local_sta:
        print("  Saving station metadata …")
        save_stations(inv, cfg, inv_all if selection else None)
    elif selection and inv is not None:
        os.makedirs(META_DIR, exist_ok=True)
        path = os.path.join(META_DIR, cfg['station_file_name'] + '.xml')
        inv.write(path, format='STATIONXML')
        print(f"  Saved: {path}   ({len(_unique_stations(inv))} selected "
              f"stations; all the stations are in your local file)")
    else:
        print("  [SKIP] Station metadata loaded from local file — "
              "not re-saved.")
    if selection:
        save_selection_report(selection, cfg)


def save_stations(inv, cfg: dict, inv_all=None) -> None:
    """Write station metadata (with response) to META_DATA/.

    Outputs:
      META_DATA/<name>.xml                  ← inventory in a single file
      META_DATA/<name>/<name>_NET_STA.xml   ← one StationXML per station
      META_DATA/<name>_all.xml              ← all candidates, when inv is the
                                              result of the azimuthal
                                              selection (inv_all given)
    """
    if inv is None:
        print("  [SKIP] No inventory to save.")
        return
    os.makedirs(META_DIR, exist_ok=True)
    name = cfg['station_file_name']

    if inv_all is not None:
        path = os.path.join(META_DIR, name + '_all.xml')
        inv_all.write(path, format='STATIONXML')
        print(f"  Saved: {path}   (all {len(_unique_stations(inv_all))} "
              f"candidates)")

    # ── full inventory, single file ──────────────────────────────────────────
    path = os.path.join(META_DIR, name + '.xml')
    inv.write(path, format='STATIONXML')
    print(f"  Saved: {path}")

    # ── one file per station ─────────────────────────────────────────────────
    sta_dir = os.path.join(META_DIR, name)
    os.makedirs(sta_dir, exist_ok=True)
    seen = set()   # a station may appear multiple times (epochs) — write once
    for net in inv:
        for sta in net:
            key = (net.code, sta.code)
            if key in seen:
                continue
            seen.add(key)
            sub = inv.select(network=net.code, station=sta.code)
            sta_path = os.path.join(sta_dir, f"{name}_{net.code}_{sta.code}.xml")
            sub.write(sta_path, format='STATIONXML')
    print(f"  Saved: {len(seen)} per-station files in {sta_dir}/")


# ═════════════════════════════════════════════════════════════════════════════
# 7 ─ EVENT WAVEFORM DOWNLOAD
# ═════════════════════════════════════════════════════════════════════════════

_WF_BLOCK = 10    # stations per bulk waveform request: small replies get
                  # through a busy server more easily, and a failing request
                  # costs only its own stations, not the whole event


def _fetch_event_bulk(client: Client, keys: list, loc: str,
                      chan_patterns: list, t1, t2, what: str):
    """Waveforms of the stations keys [(net, sta), …] between t1 and t2.

    Bulk requests of _WF_BLOCK stations; a block that still fails after the
    retries is split in two, down to single stations, so that one station
    the server cannot deliver does not take the others with it.
    Returns (stream, set of stations whose request failed).
    """
    pending = [keys[i:i + _WF_BLOCK] for i in range(0, len(keys), _WF_BLOCK)]
    st, failed = Stream(), set()
    while pending:
        part = pending.pop(0)
        bulk = [(net, sta, loc, ch, t1, t2)
                for net, sta in part for ch in chan_patterns]
        label = (f"{what} {part[0][0]}.{part[0][1]}" if len(part) == 1 else
                 f"{what} ({len(part)} stations)")
        got, status = _fetch_with_retry(
            lambda: client.get_waveforms_bulk(bulk), label)
        if status == 'ok' and got is not None:
            st += got
        elif status == 'error':
            if len(part) > 1:
                half = len(part) // 2
                print(f"  [SPLIT]  retrying as {half} + {len(part) - half} "
                      f"stations")
                pending[:0] = [part[:half], part[half:]]
            else:
                failed.add(part[0])
    return st, failed


def download_waveforms(pf_events: list, inv, client: Client, cfg: dict) -> None:
    """Download event waveforms: one miniSEED file per (event, station) pair.

    The stations still missing on disk are fetched with bulk requests
    (client.get_waveforms_bulk → one HTTP round-trip for _WF_BLOCK stations
    instead of one per station); the returned stream is split per station
    at save time.  Existing files are skipped, so an interrupted run resumes
    where it left.
    """
    if inv is None:
        print("  [SKIP] No inventory available – cannot download waveforms.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)

    tbef = cfg['t_before_s']
    taft = cfg['t_after_s']
    # In FDSN bulk requests an empty location code must be written as "--"
    loc  = cfg['location'] or '--'
    # FDSN bulk lines take ONE channel pattern each → split "HH?,BH?" up front
    chan_patterns = [c.strip() for c in cfg['channel'].split(',')]

    stations = [(net, sta) for net, sta, *_ in _unique_stations(inv)]

    n_ev = len(pf_events)
    n_dl = n_skip = n_nodata = n_err = 0

    for idx, pev in enumerate(pf_events, 1):
        # Event folder name = pev.name  (already contains label + timestamp)
        ev_name = pev.name
        ev_dir  = os.path.join(DATA_DIR, ev_name)
        t0      = UTCDateTime(pev.time)
        t1, t2  = t0 - tbef, t0 + taft

        print(f"\n[{idx:>4}/{n_ev}]  {ev_name}")
        os.makedirs(ev_dir, exist_ok=True)

        # Bulk requests holding only the stations still missing on disk
        targets = {}                       # (net, sta) → output file path
        for net_code, sta_code in stations:
            out_path = os.path.join(
                ev_dir, f"{ev_name}_{net_code}_{sta_code}.mseed")
            if os.path.isfile(out_path):
                n_skip += 1
                continue
            targets[(net_code, sta_code)] = out_path

        skipped_here = len(stations) - len(targets)
        if not targets:
            print(f"  [SKIP]   all {len(stations)} station(s) already on disk")
            continue
        if skipped_here:
            print(f"  [SKIP]   {skipped_here} station(s) already on disk")

        st, failed = _fetch_event_bulk(client, list(targets), loc,
                                       chan_patterns, t1, t2, ev_name)
        n_err += len(failed)
        if len(st) == 0 and not failed:
            print(f"  [–]      no data for the {len(targets)} "
                  f"requested station(s)")
            n_nodata += len(targets)
            continue

        # Split the bulk stream per station and save one file each
        for (net_code, sta_code), out_path in targets.items():
            if (net_code, sta_code) in failed:
                continue                   # error already printed
            sub = st.select(network=net_code, station=sta_code)
            if len(sub) == 0:
                print(f"  [–]      {net_code}.{sta_code}  no data")
                n_nodata += 1
                continue
            _atomic_write(sub, out_path)
            print(f"  [OK]     {net_code}.{sta_code}  ({len(sub)} trace(s))")
            n_dl += 1

    print(f"\n{'─' * 54}")
    print(f"  Waveform files downloaded  : {n_dl}")
    print(f"  Waveform files skipped     : {n_skip}  (already on disk)")
    print(f"  No data                    : {n_nodata}")
    print(f"  Errors                     : {n_err}")
    print(f"{'─' * 54}\n")


# ═════════════════════════════════════════════════════════════════════════════
# 8 ─ CONTINUOUS WAVEFORM DOWNLOAD
# ═════════════════════════════════════════════════════════════════════════════

def _continuous_chunks(cfg: dict) -> list:
    """Time chunks (t1, t2) of the continuous download.

    Chunks sit on a fixed grid — multiples of chunk_hours counted from
    1970-01-01 00:00 UTC, i.e. midnight-aligned for daily chunks — and are
    always complete, also where tmin / tmax fall inside a chunk.  So a file
    name always means the same time span, and runs with different tmin /
    tmax never mistake a partial file for a complete one when resuming.
    """
    chunk = cfg['chunk_hours'] * 3600.0
    tmax  = UTCDateTime(cfg['tmax']).timestamp
    t     = (UTCDateTime(cfg['tmin']).timestamp // chunk) * chunk
    chunks = []
    while t < tmax:
        chunks.append((UTCDateTime(t), UTCDateTime(t + chunk)))
        t += chunk
    return chunks


def download_continuous(inv, client: Client, cfg: dict) -> None:
    """Download continuous waveforms in fixed-size time chunks, in parallel.

    Output: DATA/CONTINUOUS/{event_label}_yyyy_mm_dd_{NET}_{STA}.mseed
            (chunks that are not whole days add _HH_MM after the date)
    Existing files are skipped, so an interrupted run resumes where it left.
    """
    if inv is None:
        print("  [SKIP] No inventory – cannot download waveforms.")
        return

    chunk = cfg['chunk_hours'] * 3600   # seconds
    label = cfg['event_label']
    chan  = cfg['channel']
    loc   = cfg['location']
    n_workers = max(1, int(cfg['parallel_downloads']))

    cont_dir = os.path.join(DATA_DIR, 'CONTINUOUS')
    os.makedirs(cont_dir, exist_ok=True)

    stations = [(net, sta) for net, sta, *_ in _unique_stations(inv)]

    # Chunks that are not whole days need HH_MM in the filename, otherwise
    # several chunks would map to one file and be skipped as "already on disk"
    t_fmt = '%Y_%m_%d' if chunk % 86400 == 0 else '%Y_%m_%d_%H_%M'

    # Build the full task list up front, skipping files already on disk
    tasks  = []
    n_skip = 0
    for t1, t2 in _continuous_chunks(cfg):
        date_str = t1.strftime(t_fmt)
        for net_code, sta_code in stations:
            fname    = f"{label}_{date_str}_{net_code}_{sta_code}.mseed"
            out_path = os.path.join(cont_dir, fname)
            if os.path.isfile(out_path):
                n_skip += 1
            else:
                tasks.append((t1, t2, net_code, sta_code, out_path))

    print(f"  {len(tasks)} file(s) to download  "
          f"({n_skip} already on disk, {n_workers} parallel connections)")

    n_dl = n_nodata = n_err = 0

    def _fetch_one(task):
        """Worker: download one (chunk, station) pair and save it."""
        tt1, tt2, net_code, sta_code, out_path = task
        what = f"{net_code}.{sta_code} {tt1.strftime('%Y-%m-%d %H:%M')}"
        st, status = _fetch_with_retry(
            lambda: client.get_waveforms(
                network=net_code, station=sta_code,
                location=loc, channel=chan,
                starttime=tt1, endtime=tt2),
            what)
        if status == 'ok' and st is not None and len(st) > 0:
            _atomic_write(st, out_path)
            return task, len(st), 'saved'
        if status == 'error':
            return task, 0, 'error'
        return task, 0, 'nodata'

    pool    = ThreadPoolExecutor(max_workers=n_workers)
    futures = [pool.submit(_fetch_one, t) for t in tasks]
    done    = 0
    try:
        for fut in as_completed(futures):
            (tt1, _, net_code, sta_code, _), ntr, outcome = fut.result()
            done += 1
            tag   = f"[{done:>5}/{len(tasks)}]"
            stamp = tt1.strftime('%Y-%m-%d %H:%M')
            if outcome == 'saved':
                n_dl += 1
                print(f"  {tag} [OK]  {stamp}  {net_code}.{sta_code}  "
                      f"({ntr} trace(s))")
            elif outcome == 'nodata':
                n_nodata += 1
                print(f"  {tag} [–]   {stamp}  {net_code}.{sta_code}  no data")
            else:
                n_err += 1   # details already printed by the retry helper
        pool.shutdown(wait=True)
    except KeyboardInterrupt:
        # Drop everything still queued; running requests finish on their own.
        # Already-saved files are skipped on the next run (resumable).
        pool.shutdown(wait=False, cancel_futures=True)
        print(f"\n  Interrupted — {n_dl} file(s) saved so far. "
              f"Re-run to resume from where it stopped.")
        raise SystemExit(1)

    print(f"\n{'─' * 54}")
    print(f"  Files downloaded : {n_dl}")
    print(f"  Files skipped    : {n_skip}  (already on disk)")
    print(f"  No data          : {n_nodata}")
    print(f"  Errors           : {n_err}")
    print(f"{'─' * 54}\n")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    # ── Command-line argument: config file name or path ───────────────────────
    parser = argparse.ArgumentParser(
        description='FDSN seismic data downloader (catalog + stations + waveforms)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  python download_catalog_waveforms_station_xml.py\n'
            '  python download_catalog_waveforms_station_xml.py campi_flegrei.yaml\n'
            '  python download_catalog_waveforms_station_xml.py /abs/path/my_config.yaml\n\n'
            'If only a filename is given (no path separators), the script looks\n'
            f'for it inside  CAT/config_cat/  (i.e. {CONFIG_DIR}).'
        ),
    )
    parser.add_argument(
        'config',
        nargs='?',
        default='config.yaml',
        metavar='CONFIG_FILE',
        help='config filename or absolute path  (default: config.yaml)',
    )
    args = parser.parse_args()

    # Resolve config path: bare filename → CONFIG_DIR; otherwise use as-is
    cfg_arg = args.config
    if os.sep not in cfg_arg and '/' not in cfg_arg:
        config_path = os.path.join(CONFIG_DIR, cfg_arg)
    else:
        config_path = os.path.abspath(cfg_arg)

    w = 64
    print("\n" + "═" * w)
    print("  FDSN SEISMIC DATA DOWNLOADER  –  ObsPy + Pyrocko")
    print("═" * w)
    print(f"  Config: {config_path}\n")

    # ── 1. Configuration ──────────────────────────────────────────────────────
    cfg = load_or_create_config(config_path)
    validate_config(cfg)
    print_config_summary(cfg)
    cfg = ask_modify_config(config_path, cfg)
    validate_config(cfg)

    mode      = cfg['download_mode']
    local_sta = bool(cfg.get('existing_stations_xml'))
    local_cat = mode == 'event' and bool(cfg.get('existing_catalog_pf'))

    # What the selected mode uses
    uses_events    = mode in ('event', 'catalog')
    uses_stations  = mode in ('event', 'continuous', 'stations')
    uses_waveforms = mode in ('event', 'continuous')

    # ── 2. Connect to FDSN — only to the services this run really uses ───────
    # Main client: stations (unless local) and waveforms.  The catalog comes
    # from fdsn_site_events (e.g. IRIS → USGS) or from a local file.
    ev_site     = cfg.get('fdsn_site_events') or cfg['fdsn_site']
    need_events = uses_events and not local_cat
    needed = ()
    if uses_stations and not local_sta:
        needed += ('station',)
    if uses_waveforms:
        needed += ('dataselect',)
    if need_events and ev_site == cfg['fdsn_site']:
        needed += ('event',)

    client = event_client = None
    if needed:
        print(f"\n  Connecting to {cfg['fdsn_site']} …", end=' ', flush=True)
        client = event_client = _connect(cfg['fdsn_site'], needed)
        print("Connected.")
    if need_events and ev_site != cfg['fdsn_site']:
        print(f"  Connecting to {ev_site} (events) …", end=' ', flush=True)
        event_client = _connect(ev_site, ('event',))
        print("Connected.")
    if not needed and not need_events:
        if uses_stations and cfg['azi_select'] and cfg['azi_check_data']:
            print("\n  Local files only — just the data check will ask "
                  f"{cfg['fdsn_site']}.")
        else:
            print("\n  Local files only — no FDSN connection needed.")
    print()

    n_steps = {'event': 4, 'continuous': 3, 'catalog': 2, 'stations': 2}[mode]
    counter = iter(range(1, n_steps + 1))

    def step(text):
        print(f"[STEP {next(counter)}/{n_steps}]  {text}")

    # ── 3. Events: local .pf file OR FDSN query ───────────────────────────────
    cat = pf_events = ev_points = None
    failed, n_events = [], 0
    if uses_events:
        if local_cat:
            step("Loading catalog from local .pf file …")
            pf_events = load_catalog_from_pf(
                _resolve_local_path(cfg['existing_catalog_pf'], CAT_DIR),
                cfg['event_label'])
            ev_points = _points_from_pyrocko(pf_events)
            n_events  = len(pf_events)
        else:
            step(f"Querying event catalog from {ev_site} …")
            cat, failed = query_events(event_client, cfg)
            ev_points   = _points_from_obspy(cat)
            n_events    = len(cat)

        if n_events == 0:
            if failed:
                print(f"\n  The catalog could not be downloaded: "
                      f"{len(failed)} time window(s) failed with network "
                      f"errors.\n  The server ({ev_site}) may be busy or "
                      f"temporarily down: try again later.\n")
                sys.exit(1)
            print("\n  No events found. Check your parameters and try again.\n")
            sys.exit(0)

        # A local catalog is not limited to tmin–tmax, but the FDSN station
        # query is: stations active only outside that window would be missed
        if local_cat and not local_sta:
            t_lo = UTCDateTime(cfg['tmin']).timestamp
            t_hi = UTCDateTime(cfg['tmax']).timestamp
            n_out = sum(1 for ev in pf_events if not t_lo <= ev.time <= t_hi)
            if n_out:
                print(f"  [WARN] {n_out} of {n_events} events fall outside "
                      f"tmin → tmax ({cfg['tmin']} → {cfg['tmax']}),\n"
                      f"         the window used for the FDSN station query: "
                      f"stations active only at\n"
                      f"         those times may be missing.  Widen tmin / "
                      f"tmax to cover the whole catalog.\n")

    # ── 4. Stations (+ optional azimuthal selection) ──────────────────────────
    inv_all = inv = selection = None
    n_sta = 0
    if uses_stations:
        step("Loading station inventory …")
        inv_all = get_stations(client, cfg)
        # Time to check for data (azimuthal selection with azi_check_data):
        # the waveform window of every event, or the whole period
        if mode == 'event':
            windows = [(p['t'] - cfg['t_before_s'], p['t'] + cfg['t_after_s'])
                       for p in ev_points]
        else:
            windows = [(UTCDateTime(cfg['tmin']).timestamp,
                        UTCDateTime(cfg['tmax']).timestamp)]
        inv, selection = apply_station_selection(
            inv_all, cfg, client, windows, per_event=(mode == 'event'))
        n_sta = len(_unique_stations(inv))
        if mode == 'stations' and inv_all is None:
            print("\n  No stations found. Check your parameters and try "
                  "again.\n")
            sys.exit(0)

    # ── 5. Preview map ────────────────────────────────────────────────────────
    step(f"Building preview map ({cfg['map_backend']}) …\n")
    show_preview_map(ev_points if uses_events else None, inv, cfg,
                     event_area=need_events,
                     station_area=uses_stations and not local_sta,
                     selection=selection)

    # ── 6. Summary and confirmation ───────────────────────────────────────────
    save_cat = cat is not None              # only catalogs from FDSN
    save_sta = uses_stations and (
        (not local_sta and inv_all is not None) or selection is not None)

    print(f"\n  Summary:")
    print(f"    Mode      : {mode.upper()}")
    if uses_events:
        cat_src = ("local file — will NOT be re-saved" if local_cat
                   else f"FDSN {ev_site}")
        if failed:
            cat_src += f" — INCOMPLETE, {len(failed)} time window(s) failed"
        print(f"    Events    : {n_events}   [{cat_src}]")
    if uses_stations:
        sta_src = ("local file — will NOT be re-saved" if local_sta
                   else f"FDSN {cfg['fdsn_site']}")
        print(f"    Stations  : {n_sta}   [{sta_src}]")
        if selection:
            print(f"                (azimuthal selection: {n_sta} of "
                  f"{len(selection['rows'])}, max gap "
                  f"{selection['gap_after']:.0f}°)")
    if mode == 'event':
        print(f"    Window    : -{cfg['t_before_s']} s  /  "
              f"+{cfg['t_after_s']} s")
    if mode == 'continuous':
        chunks = _continuous_chunks(cfg)
        c_from = chunks[0][0].strftime('%Y-%m-%d %H:%M')
        c_to   = chunks[-1][1].strftime('%Y-%m-%d %H:%M')
        print(f"    Period    : {cfg['tmin']}  →  {cfg['tmax']}")
        print(f"                (complete chunks: {c_from} → {c_to})")
        print(f"    Chunks    : {len(chunks)} × {cfg['chunk_hours']} h"
              f"   (~{n_sta * len(chunks)} files total)")
        print(f"    Parallel  : {cfg['parallel_downloads']} connections")

    outputs = []
    if save_cat:
        outputs.append(f"CAT/{cfg['catalog_name']}.xml .txt .pf")
    if save_sta:
        name = cfg['station_file_name']
        if not local_sta:
            outputs.append(f"META_DATA/{name}.xml + META_DATA/{name}/"
                           + (" (selected)" if selection else ""))
            if selection:
                outputs.append(f"META_DATA/{name}_all.xml (all candidates)")
        elif selection and inv is not None:
            outputs.append(f"META_DATA/{name}.xml (selected)")
        if selection:
            outputs.append(f"META_DATA/{name}_selection.txt")
    if mode == 'event':
        outputs.append("DATA/<event_name>/  (event waveforms)")
    if mode == 'continuous':
        outputs.append("DATA/CONTINUOUS/  (continuous waveforms)")
    if not outputs:
        print("\n  Nothing to save with these settings (preview only).\n")
        sys.exit(0)
    print("    Output    : " + "\n                ".join(outputs))

    question = {'event':      'Proceed with the download?',
                'continuous': 'Proceed with the download?',
                'catalog':    'Save the catalog?',
                'stations':   'Save the station metadata?'}[mode]
    ans = input(f"\n  {question} [y/N]: ").strip().lower()
    if ans != 'y':
        print("\n  Aborted. Nothing was saved.\n")
        sys.exit(0)

    # ── 7. Output names already on disk: overwrite or use another name ────────
    old_files = resolve_output_names(cfg, save_cat, save_sta)
    if old_files is None:
        print("\n  Aborted. Nothing was saved.\n")
        sys.exit(0)
    print(f"\n{'─' * w}")
    remove_old_outputs(old_files)

    # ── 8. Catalog and station metadata first: saved before any waveform ─────
    if uses_events:
        if save_cat:
            print("  Saving catalog …")
            pf_events = save_catalog(cat, cfg)
        else:
            print("  [SKIP] Catalog loaded from local file — not re-saved.")
    if uses_stations:
        if uses_events:
            print(f"\n{'─' * w}")
        save_station_metadata(inv, inv_all, selection, cfg, local_sta)

    # ── 9. Waveforms ──────────────────────────────────────────────────────────
    if mode == 'event':
        print(f"\n{'─' * w}")
        step("Downloading event waveforms …")
        download_waveforms(pf_events, inv, client, cfg)
    elif mode == 'continuous':
        print(f"\n{'─' * w}")
        step("Downloading continuous waveforms …")
        download_continuous(inv, client, cfg)

    print(f"{'═' * w}")
    print("  All done.\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        # Waveforms are written atomically: whatever is on disk is complete
        print("\n\n  Interrupted.  Files saved so far are complete — "
              "re-run with the same config to resume.\n")
        sys.exit(130)
