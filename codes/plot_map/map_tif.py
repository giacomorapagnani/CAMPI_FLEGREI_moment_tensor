import pygmt
import rioxarray  # Per leggere il file .tif
import geopandas as gpd
from rasterio.warp import transform
import os
import numpy as np

workdir='../../'
catdir =  os.path.join(workdir,'CAT')
metadatadir =  os.path.join(workdir,'META_DATA')

# Parametri della mappa
region = [14.07, 14.175, 40.775, 40.855]

# Caricare il file .tif
topo = rioxarray.open_rasterio('/Users/giaco/Downloads/w45090_s10_INGV/w45090_s10.tif')

# Verificare il sistema di riferimento
crs = topo.rio.crs
print("Sistema di riferimento del file:", crs)

# Se necessario, convertire le coordinate
if crs.to_epsg() != 4326:
    print("trasforma sistema di riferimento")
    x, y = topo.x.values, topo.y.values
    lon, lat = transform(crs, "EPSG:4326", x, y)
    topo = topo.assign_coords({"x": lon, "y": lat})


# Creare la figura con PyGMT
fig = pygmt.Figure()
fig.basemap(region=region, projection="M6i", frame='a0.05', map_scale='x2c/0.5c+w10')
fig.grdimage(topo, cmap="gray", shading=True)

# Aggiungere i terremoti
f=open(catdir + '/catalogue_flegrei_mag_2_5.txt','r')
latevf=[]
lonevf=[]
magevf=[]
for line in f:
    toks=line.split()
    latevf.append(eval(toks[2]))
    lonevf.append(eval(toks[3]))
    #namsta.append(toks[0])
latevf=np.array(latevf)
lonevf=np.array(lonevf)

minlon=14.07
maxlon=14.175
minlat=40.775
maxlat=40.855

evf=[] # mag>2.5
for elat,elon in zip(latevf,lonevf):
    if (elon>minlon and elon<maxlon) and (elat>minlat and elat<maxlat):
        evf.append([elon,elat])
evf=np.array(evf)

fig.plot(x=evf[:,0], y=evf[:,1], style="c0.2c", fill="#0066cc", pen="black", label='event selected') # blue filling


# Mostrare la mappa
fig.show()