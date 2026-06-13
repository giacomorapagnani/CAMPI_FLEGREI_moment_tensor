import pygmt
import numpy as np
import os
import xarray as xr
import rioxarray
from pyrocko import model
import pyrocko.moment_tensor as pmt

workdir = '../'
catdir = os.path.join(workdir, 'CAT')
metadatadir = os.path.join(workdir, 'META_DATA')
plotdir = os.path.join(workdir, 'PLOTS', 'MAPS')
os.makedirs(plotdir, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════════════

filename = 'catalogue_flegrei_MT_final_reloc'
# catalogue_flegrei_MT_final_VLP_reloc
# catalogue_flegrei_MT_final_DC  /  catalogue_flegrei_MT_final_FULL

#   'local'  → Tinitaly 10 m DEM (land-only, high-res)
#   'pygmt'  → GMT built-in 01s relief (~30 m, includes bathymetry)
topo_source = 'local'
tif_path    = '/Users/giaco/UNI/PhD_CODE/QGIS/topo_flegrei/w45090_s10.tif'
water_color = '#A8B4BC'   # sea / NaN colour — change freely

#   'depth_gray'  → grayscale by depth (shallow = light, deep = dark)
#   'fixed'       → uniform fill set by fixed_color
color_mode  = 'depth_gray'
fixed_color = '#606060'

switch_deviatoric = True
switch_timestamps = False
switch_sta_names  = False

switch_pozzuoli = False
if switch_pozzuoli:
    minlon, maxlon = 14.07, 14.175
    minlat, maxlat = 40.79,  40.845
    map_name = 'pozzuoli'
else:
    minlon, maxlon = 14.07, 14.175
    minlat, maxlat = 40.775, 40.855
    map_name = 'gulf'

region     = [minlon, maxlon, minlat, maxlat]
projection = "M6i"

# ═══════════════════════════════════════════════════════════════
#  LOAD CATALOGUE
# ═══════════════════════════════════════════════════════════════
fm_events = model.load_events(os.path.join(catdir, filename + '.pf'))
fm_events = [ev for ev in fm_events if ev.moment_tensor is not None]

depths_km = np.array([ev.depth / 1000 for ev in fm_events])
depth_min = max(0.0, depths_km.min() - 0.3)
depth_max = depths_km.max() + 0.3

# ═══════════════════════════════════════════════════════════════
#  DEPTH → GREY  (pure Python, independent of GMT CPT state)
#  shallow → light grey (200/200/200),  deep → dark grey (50/50/50)
# ═══════════════════════════════════════════════════════════════
def depth_to_gray(depth_km):
    t = np.clip((depth_km - depth_min) / (depth_max - depth_min), 0.0, 1.0)
    g = int(round(200 - t * 150))   # 200 (light) → 50 (dark)
    return f"{g}/{g}/{g}"


# ═══════════════════════════════════════════════════════════════
#  MAGNITUDE → SIZE  (M2 ≈ 0.45c, M3 ≈ 0.60c, M4 ≈ 0.75c)
# ═══════════════════════════════════════════════════════════════
def mag_to_size(mag):
    return max(0.15, 0.45 + 0.15 * (mag - 2.0))

# ═══════════════════════════════════════════════════════════════
#  FIGURE SETUP
# ═══════════════════════════════════════════════════════════════
fig = pygmt.Figure()
pygmt.config(
    FORMAT_GEO_MAP     = "ddd.xxF",
    FONT_ANNOT_PRIMARY = "9p,Helvetica,black",
    MAP_FRAME_PEN      = "0p,white@100",
)
fig.basemap(region=region, projection=projection,
            frame='a0.05', map_scale='x3c/-0.7c+w3')

# ═══════════════════════════════════════════════════════════════
#  TOPOGRAPHY
# ═══════════════════════════════════════════════════════════════
if topo_source == 'local':
    pygmt.config(COLOR_NAN=water_color)   # NaN (sea) cells → water_color

    buf     = 0.02
    raw     = rioxarray.open_rasterio(tif_path, masked=True).squeeze()
    raw_wgs = raw.rio.reproject('EPSG:4326')
    clipped = raw_wgs.rio.clip_box(
        minx=minlon - buf, miny=minlat - buf,
        maxx=maxlon + buf, maxy=maxlat + buf,
    )
    topo = xr.DataArray(
        data=clipped.values.astype('float32'),
        coords={'lat': clipped.y.values, 'lon': clipped.x.values},
        dims=['lat', 'lon'],
    )
    pygmt.makecpt(cmap="gray", series=[0, 600, 10], reverse=True)
    fig.grdimage(grid=topo, cmap=True, shading="+a315+ne0.6",
                 region=region, projection=projection)
    pygmt.config(COLOR_NAN="white")       # reset so other elements are unaffected

else:   # identical to original script 11
    topo = pygmt.datasets.load_earth_relief(resolution="01s", region=region)
    fig.grdimage(grid=topo, region=region, projection=projection,
                 shading="+a45+ne0.5", cmap="gray")
    fig.coast(shorelines="1/0.5p,black", resolution="f", water="#EBEBEE")

# ═══════════════════════════════════════════════════════════════
#  DEPTH COLORBAR
#  We write the CPT ourselves and pass the file explicitly to
#  fig.colorbar() — this bypasses all GMT internal CPT state issues.
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  FOCAL MECHANISMS
#  compressionfill is computed from depth in Python — no GMT CPT needed.
# ═══════════════════════════════════════════════════════════════
for ev in fm_events:
    size = mag_to_size(ev.magnitude)

    if switch_deviatoric:
        msix = pmt.to6(ev.moment_tensor.m_up_south_east())
        spec = {
            "mrr": msix[0] * 1e7, "mtt": msix[1] * 1e7, "mff": msix[2] * 1e7,
            "mrt": msix[3] * 1e7, "mrf": msix[4] * 1e7, "mtf": msix[5] * 1e7,
            "exponent": 1,
        }
        convention = 'mt'
    else:
        spec = {
            "strike":    ev.moment_tensor.strike1,
            "dip":       ev.moment_tensor.dip1,
            "rake":      ev.moment_tensor.rake1,
            "magnitude": ev.magnitude,
        }
        convention = 'aki'

    fill = depth_to_gray(ev.depth / 1000) if color_mode == 'depth_gray' else fixed_color

    fig.meca(
        spec=spec, convention=convention,
        longitude=ev.lon, latitude=ev.lat, depth=ev.depth / 1000,
        scale=f"{size:.2f}c",
        compressionfill=fill, extensionfill="white",
        pen="0.5p,gray30,solid",
    )

    if switch_timestamps:
        parts = ev.name.split('_')[1:]
        label = f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}:{parts[5]}"
        fig.text(text=label, x=ev.lon, y=ev.lat + 0.001,
                 font="4p,Helvetica,black", justify="CM")

# ═══════════════════════════════════════════════════════════════
#  MAGNITUDE LEGEND  — compact horizontal, top-left
# ═══════════════════════════════════════════════════════════════
ref_mags = [2.0, 3.0, 4.0]
dx_deg   = 0.0075

box_pad  = 0.0018
box_x0   = minlon + box_pad
box_h    = 0.016
box_w    = 0.003 + len(ref_mags) * dx_deg + box_pad
box_y0   = maxlat - box_h - box_pad

fig.plot(
    x=[box_x0, box_x0 + box_w, box_x0 + box_w, box_x0, box_x0],
    y=[box_y0, box_y0, box_y0 + box_h, box_y0 + box_h, box_y0],
    pen="0.4p,gray50", fill="white@20",
)

fig.text(text="Mag", x=box_x0 + box_w / 2, y=box_y0 + box_h * 0.87,
         font="4.5p,Helvetica-Bold,black", justify="CM")

x0_c    = box_x0 + 0.003
y_circ  = box_y0 + box_h * 0.52
y_label = box_y0 + box_h * 0.13

for i, rm in enumerate(ref_mags):
    xc = x0_c + i * dx_deg
    fig.plot(x=xc, y=y_circ, style=f"c{mag_to_size(rm):.2f}c",
             fill="gray50", pen="0.4p,black")
    fig.text(text=f"{int(rm)} Mw", x=xc, y=y_label,
             font="4p,Helvetica,black", justify="CM")

# ═══════════════════════════════════════════════════════════════
#  STATIONS
# ═══════════════════════════════════════════════════════════════
latsta, lonsta, namsta = [], [], []
with open(os.path.join(metadatadir, 'stations_flegrei_INGV_final.pf')) as f:
    for line in f:
        if line[0] == ' ':
            continue
        toks = line.split()
        latsta.append(float(toks[1]))
        lonsta.append(float(toks[2]))
        namsta.append(toks[0].split('.')[1])
latsta = np.array(latsta)
lonsta = np.array(lonsta)

fig.plot(x=lonsta, y=latsta, style="t0.3c", fill="#FFCC4E", pen="0.6p,black")
if switch_sta_names:
    fig.text(x=lonsta + 0.002, y=latsta + 0.001, text=namsta,
             justify='BL', font='5p,Helvetica,black')

# ═══════════════════════════════════════════════════════════════
#  DEPTH COLORBAR — inside map, bottom-centre
#  Strategy:
#    1. shift_origin to bottom-centre of map interior
#    2. semi-transparent white box (background)
#    3. basemap ONCE with full frame — ticks extend outward (SNwe)
#    4. gradient rectangles fill the interior (ticks stay visible outside)
#    5. shift_origin restore
# ═══════════════════════════════════════════════════════════════
if color_mode == 'depth_gray':
    cb_w   = 5.0    # colorbar width  (cm)
    cb_h   = 0.45   # colorbar strip height (cm)
    n_grad = 200    # gradient steps

    # Map width M6i = 6 in = 15.24 cm → centre colorbar
    map_w_cm = 6 * 2.54        # 15.24 cm
    x_shift  = (map_w_cm - cb_w) / 2   # left edge of colorbar from map origin

    # y_shift: distance from map bottom frame to bottom of colorbar strip
    # 0.5c up from the bottom puts it inside the map with room for ticks below
    y_shift = 0.5

    fig.shift_origin(xshift=f"{x_shift:.2f}c", yshift=f"{y_shift:.2f}c")

    # Semi-transparent background box (pad = 0.15c on all sides)
    pad = 0.15
    # box in Cartesian coords: x from -pad to cb_w+pad, y from -pad to cb_h+pad
    # (we use the colorbar's own Cartesian system, so draw after basemap sets it)

    # ONE basemap call: sets coordinates AND draws frame (ticks go outward)
    fig.basemap(
        region=[depth_min, depth_max, 0, 1],
        projection=f"X{cb_w}c/{cb_h}c",
        frame=["SNwe", "a1f0.5", "x+lDepth (km)"],
    )

    # Background box (drawn after basemap so it's in the right coord system,
    # then gradient is drawn on top)
    fig.plot(
        x=[depth_min - pad * (depth_max - depth_min) / cb_w,
           depth_max + pad * (depth_max - depth_min) / cb_w,
           depth_max + pad * (depth_max - depth_min) / cb_w,
           depth_min - pad * (depth_max - depth_min) / cb_w,
           depth_min - pad * (depth_max - depth_min) / cb_w],
        y=[-pad / cb_h, -pad / cb_h, 1 + pad / cb_h, 1 + pad / cb_h, -pad / cb_h],
        fill="white@40", pen="0.4p,gray50",
    )

    # Gradient rectangles (light → dark, shallow → deep)
    for i in range(n_grad):
        t0 = i / n_grad
        t1 = (i + 1) / n_grad
        z0 = depth_min + t0 * (depth_max - depth_min)
        z1 = depth_min + t1 * (depth_max - depth_min)
        g  = int(200 - t0 * 150)
        fig.plot(
            x=[z0, z1, z1, z0, z0],
            y=[0,  0,  1,  1,  0],
            fill=f"{g}/{g}/{g}",
            pen="0p",
        )

    # Restore origin
    fig.shift_origin(xshift=f"{-x_shift:.2f}c", yshift=f"{-y_shift:.2f}c")

# ═══════════════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════════════
suffix  = 'deviatoric' if switch_deviatoric else 'dc'
outpath = os.path.join(plotdir, f"{filename}_{suffix}_{map_name}.pdf")
fig.show()
fig.savefig(outpath)
print(f"Saved: {outpath}")
