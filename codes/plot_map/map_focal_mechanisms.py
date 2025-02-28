import pygmt
import numpy as np
import os
from pyrocko import util, model, io, trace, gmtpy
import pyrocko.moment_tensor as pmt

workdir='../../'
catdir =  os.path.join(workdir,'CAT')
metadatadir =  os.path.join(workdir,'META_DATA')

##########################################
############## SWITCH ##############
##########################################
# COORDINATES FOR GULF MAP OR POZZUOLI MAP

switch_coord_pozzuoli=False

if switch_coord_pozzuoli:
    # POZZUOLI COORD (SUPERNEAR)
    minlon=14.12
    maxlon=14.16
    minlat=40.82
    maxlat=40.84
    map_name='pozzuoli'
else:
    # GULF COORD (NEAR)
    minlon=14.07
    maxlon=14.175
    minlat=40.775
    maxlat=40.855
    map_name='gulf'

#   CREATE FIGURE
fig = pygmt.Figure()
pygmt.config(FORMAT_GEO_MAP="ddd.xxF")

# Define the region around the center coordinates (a smaller box for higher resolution)
region = [minlon, maxlon, minlat, maxlat]

# Define the projection
projection = "M6i"  # Mercator projection with a 6-inch width

fig.basemap(region=region,projection=projection, frame='a0.05', map_scale='x3c/-0.7c+w3')
# Load high-resolution topography data (1 arc-second resolution)
topo_data = pygmt.datasets.load_earth_relief(resolution="01s", region=region)

# Plot the topography with shading
fig.grdimage(grid=topo_data, region=region, projection=projection, shading="+a45+ne0.5", cmap="gray")
# Plot coastlines with high resolution
fig.coast(shorelines="1/0.5p,black", resolution="f", water="#EBEBEE")

#   PLOT FOCAL MECHANISM
filename='catalogue_flegrei_MT_final'             ###CHANGE###  'catalogue_flegrei_MT_final'
events_name=os.path.join(catdir,filename+'.pf')              
fm_events = model.load_events(events_name)

# TRUE if you want to plot deviatoric MT. FALSE for DC
##########################################
############## SWITCH ##############
##########################################
switch_deviatoric=True                                                                                                                               

# TRUE if you want timestamps
##########################################
############## SWITCH ##############
##########################################
switch_timestamps=False                                                                 


# loop on events in catalogue and plot FM
for ev in fm_events:
    if switch_deviatoric:

        #mm_grond=ev.moment_tensor.moment                        # == 10**( 3/2* (ev.magnitude + 10.7) -7 ) 
        #mm= 10**( ( (3/2) * ev.magnitude ) + 16.1 ) *10**-7     # GMT magnitude -> moment conversion (?)
        #print(f'ratio between mm grond and mm GMT: {mm_grond/mm}')

        msix = pmt.to6(ev.moment_tensor.m_up_south_east())
        moment_tensor_par = {
            "mrr": msix[0]* 10**7,         # Radial-Radial
            "mtt": msix[1]* 10**7,         # Tangential-Tangential
            "mff": msix[2]* 10**7,         # Perpendicular-Perpendicular
            "mrt": msix[3]* 10**7,         # Radial-Tangential
            "mrf": msix[4]* 10**7,         # Radial-Perpendicular
            "mtf": msix[5]* 10**7,         # Tangential-Perpendicular
            "exponent": 1                  # np.log10(mm) !!!WRONG!!!
            }

        # event date
        name=ev.name.split('_')[1:]
        name_ev= str(name[0] +'-'+ name[1] +'-'+ name[2] +'_'+ name[3] +':'+ name[4] +':'+ name[5])

        MT_white=False
        if MT_white:
            fig.meca(spec=moment_tensor_par,convention='mt', longitude =ev.lon, latitude=ev.lat, depth=ev.depth,
                    scale="1.2c", compressionfill="white",extensionfill="white", pen="1p,black",outline="1p,black")
        else:
            fig.meca(spec=moment_tensor_par,convention='mt', longitude =ev.lon, latitude=ev.lat, depth=ev.depth,
                    scale="0.8c", compressionfill="#BD2025",extensionfill="white", pen="0.5p,gray30,solid") 
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
                    scale="0.8c", compressionfill="#BD2025",extensionfill="white", pen="0.5p,gray30,solid") 
                    # blue : #0066cc        red :  #BD2025
    if switch_timestamps:  
        fig.text(
            text=name_ev,
            x=ev.lon,  
            y=ev.lat + 0.0006,  
            font="2p,Helvetica,black", 
            justify="CM"
            )

#   STATIONS
f=open(metadatadir + '/stations_flegrei_INGV_final.pf','r')
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
fig.plot(x=lonsta, y=latsta, style="t0.3", fill="#FFCC4E", pen="black") # yelow filling
#fig.text(x=lonsta+0.005, y=latsta+0.002, text=namsta, justify='BR',font='5p',fill="#FFCC4E")

fig.legend()
fig.show()
if switch_deviatoric:
    fig.savefig('../../PLOTS/MAPS/'+filename + '_deviatoric_' + map_name + '.pdf')
else:
    fig.savefig('../../PLOTS/MAPS/'+filename + '_dc_' + map_name + '.pdf')
