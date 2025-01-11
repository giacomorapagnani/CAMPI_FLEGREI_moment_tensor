import pygmt
import numpy as np
import os

workdir='../../'
catdir =  os.path.join(workdir,'CAT')
metadatadir =  os.path.join(workdir,'META_DATA')

#    ALL EVENTS IN CATALOGUE GOSSIP
f=open(catdir + '/GOSSIP/catalogue_flegrei_GOSSIP.txt','r')
#f=open(catdir + '/INGV/catalogue_flegrei_INGV.txt','r')
latev=[]
lonev=[]
magev=[]
for line in f:
    toks=line.split()
    latev.append(eval(toks[2]))
    lonev.append(eval(toks[3]))
    #namsta.append(toks[0])
latev=np.array(latev)
lonev=np.array(lonev)

#   EVENTS IN FINAL CATALOGUE (MAG>2.5)
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

#    EVENTS EXCLUDED
f=open(catdir + '/catalogue_flegrei_mag_2_5_excluded.txt','r')
latev_ex=[]
lonev_ex=[]
magev_ex=[]
for line in f:
    toks=line.split()
    latev_ex.append(eval(toks[2]))
    lonev_ex.append(eval(toks[3]))
    #namsta.append(toks[0])
latev_ex=np.array(latev_ex)
lonev_ex=np.array(lonev_ex)

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

# create arrays with events
ev=[]   # GOSSIP
for elat,elon in zip(latev,lonev):
    if (elon>minlon and elon<maxlon) and (elat>minlat and elat<maxlat):
        ev.append([elon,elat])
ev=np.array(ev)

evf=[] # mag>2.5
for elat,elon in zip(latevf,lonevf):
    if (elon>minlon and elon<maxlon) and (elat>minlat and elat<maxlat):
        evf.append([elon,elat])
evf=np.array(evf)

evex=[] # ev excluded
for elat,elon in zip(latev_ex,lonev_ex):
    if (elon>minlon and elon<maxlon) and (elat>minlat and elat<maxlat):
        evex.append([elon,elat])
evex=np.array(evex)

# Plot the seismic events               
fig.plot(x=ev[:,0], y=ev[:,1], style="c0.1c", fill="#BD2025", pen="black", label='event in catalogue') # red filling
fig.plot(x=evex[:,0], y=evex[:,1], style="c0.15c", fill="gray", pen="black", label='event excluded') # gray filling
fig.plot(x=evf[:,0], y=evf[:,1], style="c0.2c", fill="#0066cc", pen="black", label='event selected') # blue filling

#   STATIONS NETWORK
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
fig.text(x=lonsta+0.01, y=latsta+0.002, text=namsta, justify='BR',font='8p',fill="#FFCC4E")

fig.legend()

fig.show()