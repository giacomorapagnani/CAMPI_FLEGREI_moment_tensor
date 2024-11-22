import pygmt
import numpy as np
import os
import pandas as pd
from pyrocko import util, model, io, trace, gmtpy
import pyrocko.moment_tensor as pmt

workdir='../../'
catdir =  os.path.join(workdir,'CAT')
metadatadir =  os.path.join(workdir,'META_DATA')

#   COORDINATES FOR NEAR MAP OR SUPER NEAR MAP
#NEAR
#minlon=14.05
#maxlon=14.23
#minlat=40.75
#maxlat=40.90

#SUPERNEAR
minlon=14.07
maxlon=14.17
minlat=40.77
maxlat=40.85

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
filename='catalogue_flegrei_MT_final'             ###CHANGE###
events_name=os.path.join(catdir,filename+'.pf')              
fm_events = model.load_events(events_name)

# TRUE if you want to plot deviatoric MT. FALSE for DC
##########################################
############## SWITCH ##############
##########################################
switch_deviatoric=True                                                                 

# loop on events in catalogue and plot FM
for ev in fm_events:
    if switch_deviatoric:
        mm=ev.moment_tensor.moment
        #print(ev.moment_tensor)
        msix = pmt.to6(ev.moment_tensor.m_up_south_east())
        moment_tensor_par = {
            "mrr": msix[0],         # Radial-Radial
            "mtt": msix[1],         # Tangential-Tangential
            "mff": msix[2],         # Perpendicular-Perpendicular
            "mrt": msix[3],         # Radial-Tangential
            "mrf": msix[4],         # Radial-Perpendicular
            "mtf": msix[5],         # Tangential-Perpendicular
            "exponent": np.log10(mm)          # !!!WRONG!!!
            }

        # event date
        name=ev.name.split('_')[1:]
        name_ev= str(name[0] +'-'+ name[1] +'-'+ name[2] +'_'+ name[3] +':'+ name[4] +':'+ name[5])

        fig.meca(spec=moment_tensor_par,convention='mt', longitude =ev.lon, latitude=ev.lat, depth=ev.depth,
                    scale="0.8c", compressionfill="#BD2025",extensionfill="white", pen="0.5p,gray30,solid", event_name=name_ev ) 
    else:
        moment_tensor_par = {
            "strike": ev.moment_tensor.strike1,
            "dip": ev.moment_tensor.dip1,
            "rake": ev.moment_tensor.rake1,
            "magnitude": ev.magnitude 
            }
        #add event date
        name=ev.name.split('_')[1:]
        name_ev= str(name[0] +'-'+ name[1] +'-'+ name[2] +'_'+ name[3] +':'+ name[4] +':'+ name[5])

        fig.meca(spec=moment_tensor_par, longitude =ev.lon, latitude=ev.lat, depth=ev.depth,
                    scale="0.8c", compressionfill="#BD2025",extensionfill="white", pen="0.5p,gray30,solid")#, event_name=name_ev ) 

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
if switch_deviatoric:
    fig.savefig('../../PLOTS/MAPS/'+filename + '_deviatoric.pdf')
else:
    fig.savefig('../../PLOTS/MAPS/'+filename + '_dc.pdf')
