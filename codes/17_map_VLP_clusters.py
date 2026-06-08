import pygmt
import numpy as np
import os
from pyrocko import model

workdir = '../'
catdir = os.path.join(workdir, 'CAT')
metadatadir = os.path.join(workdir, 'META_DATA')
plotdir = os.path.join(workdir, 'PLOTS', 'MAPS')
os.makedirs(plotdir, exist_ok=True)

# ─────────────────────────────────────────
#  SWITCHES
# ─────────────────────────────────────────
switch_show_names = True       # label each event with its date string
switch_coord_pozzuoli = False   # True → tight Pozzuoli view, False → Gulf view
# ─────────────────────────────────────────

if switch_coord_pozzuoli:
    minlon, maxlon = 14.07, 14.175
    minlat, maxlat = 40.79, 40.845
    map_name = 'pozzuoli'
else:
    minlon, maxlon = 14.06, 14.185
    minlat, maxlat = 40.775, 40.855
    map_name = 'gulf'

# ─── load catalogue ───────────────────────
events = model.load_events(os.path.join(catdir, 'catalogue_VLP_clusters.yaml'))

# collect unique clusters and their colours (from YAML extras)
cluster_color = {}
for ev in events:
    cn = ev.extras['cluster_number']
    if cn not in cluster_color:
        cluster_color[cn] = ev.extras['color']

# magnitude → symbol size in cm
def mag_to_size(mag, scale=0.25):
    return max(scale * (mag - 1.5), 0.15)

def event_label(ev):
    parts = ev.name.split('_')[1:]      # drop 'flegrei' prefix
    return f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:{parts[4]}:{parts[5]}"

# ─── build figure ─────────────────────────
fig = pygmt.Figure()
pygmt.config(
    FORMAT_GEO_MAP="ddd.xxF",
    FONT_ANNOT_PRIMARY="9p,Helvetica,black",
    MAP_FRAME_PEN="0p,white@100",
)

region = [minlon, maxlon, minlat, maxlat]
projection = "M6i"

fig.basemap(region=region, projection=projection, frame='a0.05',
            map_scale='x4.8c/-0.7c+w3')

topo = pygmt.datasets.load_earth_relief(resolution="01s", region=region)
fig.grdimage(grid=topo, region=region, projection=projection,
             shading="+a45+ne0.5", cmap="gray")
fig.coast(shorelines="1/0.5p,black", resolution="f", water="#EBEBEE")

# ─── plot events by cluster ───────────────
for cluster_id in sorted(cluster_color.keys()):
    color = cluster_color[cluster_id]
    label = f"Cluster {cluster_id}" if cluster_id >= 0 else "Unclassified"

    evs = [ev for ev in events if ev.extras['cluster_number'] == cluster_id]

    for ev in evs:
        mag = float([t for t in ev.tags if t.startswith('mag:')][0].split(':')[1])
        size = mag_to_size(mag)

        fig.plot(
            x=ev.lon, y=ev.lat,
            style=f"c{size}c",
            fill=color,
            pen="0.6p,black",
            label=f"{label}+S0.35c" if ev is evs[0] else None,
        )

        if switch_show_names:
            fig.text(
                text=event_label(ev),
                x=ev.lon, y=ev.lat + 0.0008,
                font="4p,Helvetica,black",
                justify="CM",
            )

# ─── stations ─────────────────────────────
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

fig.plot(x=lonsta, y=latsta, style="t0.3c", fill="#FFCC4E", pen="0.6p,black",
         label="Stations+S0.35c")

# ─── legend ───────────────────────────────
fig.legend(position="JTR+jTR+o0.1c", box="+gwhite+p0.5p,gray30")

fig.show()
fig.savefig(os.path.join(plotdir, f'catalogue_VLP_clusters_{map_name}.pdf'))
print(f"Saved: {os.path.join(plotdir, 'catalogue_VLP_clusters_' + map_name + '.pdf')}")
