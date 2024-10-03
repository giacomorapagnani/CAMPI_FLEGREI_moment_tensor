import pygmt
import numpy as np
import os
import pandas as pd

workdir='../../'
catdir =  os.path.join(workdir,'CAT')
metadatadir =  os.path.join(workdir,'META_DATA')

#   COORDINATES FOR NEAR MAP OD FAR MAP
#NEAR
minlon=14.05
maxlon=14.23
minlat=40.75
maxlat=40.90

#FAR
#minlon=13.6
#maxlon=14.7
#minlat=40.5
#maxlat=41.3

#   CREATE FIGURE
fig = pygmt.Figure()
pygmt.config(FORMAT_GEO_MAP="ddd.xxF")

# Define the region around the center coordinates (a smaller box for higher resolution)
region = [minlon, maxlon, minlat, maxlat]

# Define the projection
projection = "M6i"  # Mercator projection with a 6-inch width

fig.basemap(region=region,projection=projection, frame='a0.05', map_scale='x2c/0.5c+w10')
# Load high-resolution topography data (1 arc-second resolution)
topo_data = pygmt.datasets.load_earth_relief(resolution="01s", region=region)

# Plot the topography with shading
fig.grdimage(grid=topo_data, region=region, projection=projection, shading="+a45+ne0.5", cmap="gray")
# Plot coastlines with high resolution
fig.coast(shorelines="1/0.5p,black", resolution="f", water="#EBEBEE")

#   PLOT FOCAL MECHANISM
fm_events = pd.read_csv("focal_mechanism_catalogue_flegrei_mag_2_5.csv")

# Itera sugli eventi e traccia i meccanismi focali
for _, row in fm_events.iterrows():
    fig.meca(spec=[row['longitude'], row['latitude'], row['strike'], row['dip'], row['rake'], row['magnitude']],depth=row['depth'],
             scale="1c", compressionfill="#BD2025",extensionfill="white", pen="0.5p,gray30,solid") 

#   STATIONS
f=open(metadatadir + '/stations_flegrei_INGV.pf','r')
latsta=[]
lonsta=[]
namsta=[]
for line in f:
    toks=line.split()
    latsta.append(eval(toks[1]))
    lonsta.append(eval(toks[2]))
    namsta.append(toks[0].split('.')[1])
latsta=np.array(latsta)
lonsta=np.array(lonsta)

# Plot stations
fig.plot(x=lonsta, y=latsta, style="t0.3", fill="#FFCC4E", pen="black", label='station') # yelow filling
#fig.text(x=lonsta+0.005, y=latsta+0.002, text=namsta, justify='BR',font='5p',fill="#FFCC4E")

fig.legend()
fig.show()