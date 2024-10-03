import pygmt
import numpy as np

f=open('/Users/giaco/Downloads/catalogo_giacomo_py_gmt/cat_final.txt','r')
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
minlon=13.3#13.6
maxlon=15.5#14.6
minlat=40.#40.5
maxlat=42.1 #41.5

# Create a new figure
fig = pygmt.Figure()
pygmt.config(FORMAT_GEO_MAP="ddd.xF")

# Define the region around the center coordinates (a smaller box for higher resolution)
region = [minlon, maxlon, minlat, maxlat]

# Define the projection
projection = "M6i"  # Mercator projection with a 6-inch width

fig.basemap(region=region,projection=projection, frame='a0.2', map_scale='x2c/0.5c+w10')
# Load high-resolution topography data (1 arc-second resolution)
topo_data = pygmt.datasets.load_earth_relief(resolution="01s", region=region)

# Plot the topography with shading
fig.grdimage(grid=topo_data, region=region, projection=projection, shading="+a45+ne0.5", cmap="gray")
# Plot coastlines with high resolution
fig.coast(shorelines="1/0.5p,black", resolution="f", water="#EBEBEE")



# Generate random seismic events


#ev=[]
#for elat,elon in zip(latev,lonev):
#    if (elon>minlon and elon<maxlon) and (elat>minlat and elat<maxlat):
#        ev.append([elon,elat])
#ev=np.array(ev)
## Plot the seismic events
#fig.plot(x=ev[:,0], y=ev[:,1], style="c0.1c", fill="#BD2025", pen="black")

f=open('/Users/giaco/Downloads/catalogo_giacomo_py_gmt/stations_flegrei_INGV_simone_plot.pf','r')
latsta=[]
lonsta=[]
namsta=[]
for line in f:
    toks=line.split()
    latsta.append(eval(toks[1]))
    lonsta.append(eval(toks[2]))
    #namsta.append(toks[0])
latsta=np.array(latsta)
lonsta=np.array(lonsta)
fig.plot(x=lonsta, y=latsta, style="t0.5", fill="#FFCC4E", pen="black", label='stazioni')
#fig.text(x=station.lon+0.050, y=station.lat+0.008, text=station.sta, justify='BR',font='9p')

#fig.legend(position="JTR+jTR+o0.1c", box= '+gwhite+p1p', S=0.7)


# Show the plot
fig.show()




#dgrid = pygmt.grdgradient(grid=grid, radiance=[270, 20])

#plot grid
#pygmt.makecpt(transparency=60,cmap="gray", series=[-1.7, 0.2, 0.02])
#fig.grdimage(
#    projection="M12c",
#    cmap=True,
#    grid=dgrid,
#)


#plot stations
#fig.plot(x=station.lon, y=station.lat, style="t0.5", color="darkred", pen="black", label='stazioni')
#fig.text(x=station.lon+0.050, y=station.lat+0.008, text=station.sta, justify='BR',font='9p')

#fig.legend(position="JTR+jTR+o0.1c", box= '+gwhite+p1p', S=0.7)
