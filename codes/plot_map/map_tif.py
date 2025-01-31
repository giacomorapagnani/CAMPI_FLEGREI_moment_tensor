import pygmt
import rioxarray  # Per leggere il file .tif
import geopandas as gpd
from rasterio.warp import transform

# Parametri della mappa
region = [14.07, 14.175, 40.775, 40.855]

# Caricare il file .tif
topo = rioxarray.open_rasterio('/Users/giaco/Downloads/w45090_s10_INGV/w45090_s10.tif')

# Verificare il sistema di riferimento
crs = topo.rio.crs
print("Sistema di riferimento del file:", crs)

# Se necessario, convertire le coordinate
if crs.to_epsg() != 4326:
    x, y = topo.x.values, topo.y.values
    lon, lat = transform(crs, "EPSG:4326", x, y)
    topo = topo.assign_coords({"x": lon, "y": lat})


# Creare la figura con PyGMT
fig = pygmt.Figure()
fig.basemap(region=region, projection="M10c", frame=["af", "WSne"])
fig.grdimage(topo, cmap="gray", shading=True)

# Aggiungere i terremoti
earthquakes = [
    (40.828671, 14.148), (40.83017, 14.1493), (40.826672, 14.143),
    (40.829498, 14.148), (40.82917, 14.15), (40.831329, 14.145),
    (40.8283, 14.1352), (40.8293, 14.1507), (40.828201, 14.142),
    (40.827301, 14.140), (40.809799, 14.117), (40.827202, 14.133),
    (40.8032, 14.1108)
]

# Convertire la lista in un array per PyGMT
lon, lat = zip(*earthquakes)
fig.plot(x=lat, y=lon, style="c0.2c", fill="#0066cc", pen="black")

# Mostrare la mappa
fig.show()
