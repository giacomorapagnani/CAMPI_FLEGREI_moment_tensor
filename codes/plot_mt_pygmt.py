"""
Plot moment tensors from two catalogues using PyGMT.
- catalogue_flegrei_MT_final.pf            → red DC beachballs
- catalogue_flegrei_MT_final_VLP_reloc.pf  → white full-MT beachballs (black outline)
Only events common to both catalogues (matched by name) are plotted.
Black arrows connect each MT_final location to its relocated counterpart.

Tunable options are grouped in the OPTIONS block below.
"""

import re, subprocess, os, tempfile
import numpy as np
import pandas as pd
import pygmt

# ── OPTIONS ───────────────────────────────────────────────────────────────────

MECA_SCALE          = "1.3c"   # beachball diameter (cm) for the reference magnitude
SHOW_EVENT_LABELS   = False    # write the event date next to each beachball
SHOW_STATION_LABELS = True     # write the station code next to each triangle
SHOW_INSET          = True     # small Italy locator map (top-right)

TOPO_TIF = "/Users/giaco/UNI/PhD_CODE/QGIS/topo_flegrei/w45090_s10.tif"
CAT_DC   = "CAT/catalogue_flegrei_MT_final.pf"
CAT_VLP  = "CAT/catalogue_flegrei_MT_final_VLP_reloc.pf"
STATIONS = "META_DATA/stations_flegrei_INGV_final.pf"


# ── helpers ──────────────────────────────────────────────────────────────────

def parse_catalog(path):
    """Return dict {name: {lat, lon, depth, moment, mnn, mee, mdd, mne, mnd, med}}."""
    events = {}
    for block in open(path).read().split("--------------------------------------------"):
        block = block.strip()
        if not block:
            continue
        g = lambda k: (re.search(rf"^{k}\s*=\s*(.+)$", block, re.MULTILINE) or [None, None])[1]
        name = g("name")
        if name is None:
            continue
        name = name.strip()
        events[name] = {
            "lat":    float(g("latitude")),
            "lon":    float(g("longitude")),
            "depth":  float(g("depth")) / 1000,        # m → km
            "moment": float(g("moment")),
            **{k: float(g(k)) for k in ("mnn", "mee", "mdd", "mne", "mnd", "med")},
        }
    return events


def parse_stations(path):
    """Return list of (net.sta, lat, lon) from a pyrocko station file."""
    stations = []
    for line in open(path):
        p = line.split()
        if len(p) == 5:                                # header line: sta lat lon elev dep
            try:
                stations.append((p[0].rstrip("."), float(p[1]), float(p[2])))
            except ValueError:
                pass
    return stations


def build_meca_df(cat, names):
    """
    DataFrame for pygmt.meca (mt convention).
    Pyrocko NED → GMT USE: mrr=mdd, mtt=mnn, mff=mee, mrt=mnd, mrf=-med, mtf=-mne.
    Moments converted N·m → dyne·cm (×1e7) as GMT expects CGS.
    """
    rows = []
    for n in names:
        ev = cat[n]
        c   = 1e7
        exp = int(np.floor(np.log10(abs(ev["moment"] * c))))
        sc  = 10 ** exp
        rows.append({
            "longitude": ev["lon"], "latitude": ev["lat"], "depth": ev["depth"],
            "mrr": ev["mdd"] * c / sc, "mtt": ev["mnn"] * c / sc, "mff": ev["mee"] * c / sc,
            "mrt": ev["mnd"] * c / sc, "mrf": -ev["med"] * c / sc, "mtf": -ev["mne"] * c / sc,
            "exponent": exp,
        })
    return pd.DataFrame(rows)


def name_to_date(name):
    _, y, m, d, *_ = name.split("_")
    return f"{y}-{m}-{d}"


# ── load data ────────────────────────────────────────────────────────────────

cat_dc  = parse_catalog(CAT_DC)
cat_vlp = parse_catalog(CAT_VLP)
common  = sorted(set(cat_dc) & set(cat_vlp))
print(f"Common events: {len(common)}")

stations = parse_stations(STATIONS)

df_dc  = build_meca_df(cat_dc,  common)
df_vlp = build_meca_df(cat_vlp, common)

# arrows: from MT_final → VLP_reloc position
arr = np.array([(cat_dc[n]["lon"], cat_dc[n]["lat"],
                 cat_vlp[n]["lon"], cat_vlp[n]["lat"]) for n in common])

# ── map region & projection ──────────────────────────────────────────────────

all_lon = list(df_dc["longitude"]) + list(df_vlp["longitude"])
all_lat = list(df_dc["latitude"])  + list(df_vlp["latitude"])
pad = 0.03
region = [min(all_lon) - pad, max(all_lon) + pad, min(all_lat) - pad, max(all_lat) + pad]
proj   = "M14c"
clon, clat = np.mean(region[:2]), np.mean(region[2:])

# ── figure ───────────────────────────────────────────────────────────────────

fig = pygmt.Figure()
pygmt.config(MAP_FRAME_TYPE="plain", FONT_ANNOT_PRIMARY="9p,Helvetica",
             MAP_FRAME_PEN="0.6p,black", MAP_TICK_LENGTH_PRIMARY="2p")

# topography: reproject UTM-32N → WGS84 once, clip, plot as dark hillshaded greys
topo_wgs84 = "/tmp/topo_flegrei_wgs84.tif"
if not os.path.exists(topo_wgs84):
    subprocess.run(["gdalwarp", "-t_srs", "EPSG:4326", TOPO_TIF, topo_wgs84],
                   check=True, capture_output=True)

grid = pygmt.grdcut(grid=topo_wgs84, region=region)
zmin, zmax = float(grid.min()), float(grid.max())

# dark-grey CPT (elevation mapped to grey 60→140; hillshade adds the relief)
gray_cpt = "/tmp/topo_gray.cpt"
with open(gray_cpt, "w") as f:
    f.write(f"{zmin} 60 60 60 {zmax} 140 140 140\nB 45 45 45\nF 160 160 160\nN 128 128 128\n")

fig.grdimage(grid=grid, region=region, projection=proj, cmap=gray_cpt, shading=True,
             frame=["WSen", "xa0.05f0.025", "ya0.05f0.025"])

# ── arrows (above topography, below beachballs) ──────────────────────────────
az  = np.degrees(np.arctan2(arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1]))
lng = np.hypot(arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1])
fig.plot(x=arr[:, 0], y=arr[:, 1], style="v0.32c+e+a40+gblack",
         pen="1.4p,black", direction=[az, lng])

# ── beachballs ───────────────────────────────────────────────────────────────
# DC only → red compression, no outline
fig.meca(spec=df_dc, scale=MECA_SCALE, component="dc",
         compressionfill="red", extensionfill="white", pen="0p,red")
# full MT → white fill, black outline + black nodal lines
fig.meca(spec=df_vlp, scale=MECA_SCALE,
         compressionfill="white", extensionfill="white",
         outline="1p,black", pen="1p,black")

# ── stations ─────────────────────────────────────────────────────────────────
fig.plot(x=[s[2] for s in stations], y=[s[1] for s in stations],
         style="i0.24c", fill="yellow", pen="0.6p,black")
if SHOW_STATION_LABELS:
    for sta, lat, lon in stations:
        fig.text(x=lon, y=lat, text=sta, font="4.5p,Helvetica,white",
                 justify="BL", offset="0.06c/0.06c")

# ── event labels (optional) ──────────────────────────────────────────────────
if SHOW_EVENT_LABELS:
    for n in common:
        fig.text(x=cat_dc[n]["lon"], y=cat_dc[n]["lat"], text=name_to_date(n),
                 font="5p,Helvetica,black", justify="BC", offset="0c/0.4c")

# ── km scale bar (bottom-right) ──────────────────────────────────────────────
fig.basemap(map_scale="jBR+w2k+o0.5c/0.5c+f+u")

# ── Italy locator inset (optional, top-right) ────────────────────────────────
if SHOW_INSET:
    with fig.inset(position="jTR+w3c/3.6c+o0.15c", box="+gwhite+p0.6p"):
        fig.coast(region=[6, 19, 36.5, 47.5], projection="M3c",
                  land="gray60", water="white", shorelines="0.2p,black", frame=False)
        fig.plot(x=clon, y=clat, style="a0.35c", fill="red", pen="0.4p,black")

# ── legend (bottom-left) ─────────────────────────────────────────────────────
mw = [(np.log10(cat_dc[n]["moment"]) - 9.1) / 1.5 for n in common]

legend_spec = (
    "H 8p,Helvetica,black Focal mechanisms\n"
    "G 0.1c\n"
    "S 0.3c c 0.22c red - 0.6c DC (MT_final)\n"
    "G 0.05c\n"
    "S 0.3c c 0.22c white 1p,black 0.6c Full MT (VLP reloc)\n"
    "G 0.05c\n"
    "S 0.3c i 0.2c yellow 0.6p,black 0.6c Station\n"
    "G 0.1c\n"
    f"L 7p,Helvetica,black L Mw {min(mw):.1f}-{max(mw):.1f}\n"
)
with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
    tf.write(legend_spec)
    legend_file = tf.name
fig.legend(spec=legend_file, position="JBL+o0.2c", box="+gwhite@20+p0.5p")
os.unlink(legend_file)

# ── save ─────────────────────────────────────────────────────────────────────
os.makedirs("PLOTS/MAPS", exist_ok=True)
fig.savefig("PLOTS/MAPS/map_focal_mechanisms_pygmt.pdf", dpi=300)
fig.savefig("PLOTS/MAPS/map_focal_mechanisms_pygmt.png", dpi=300)
print("Saved PLOTS/MAPS/map_focal_mechanisms_pygmt.pdf/.png")
