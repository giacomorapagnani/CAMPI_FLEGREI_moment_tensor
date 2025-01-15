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
    maxlon=14.17
    minlat=40.77
    maxlat=40.85
    map_name='gulf'

#   CREATE FIGURE
fig = pygmt.Figure()
pygmt.config(FORMAT_GEO_MAP="ddd.xxF")

# Define the region around the center coordinates
region = [minlon, maxlon, minlat, maxlat]

# Define the projection with increased width for better detail
projection = "M8i"  # Increased from 6i to 8i for larger figure

# Calculate grid spacing for higher resolution (approximately 30m)
spacing = "0.0003"  # About 30 meters at this latitude

# Create high-resolution grid
topo_data = pygmt.datasets.load_earth_relief(
    resolution="01s", 
    region=region,
    spacing=spacing
)

# Enhance the grid using continuous curvature splines in tension
topo_high_res = pygmt.surface(
    data=None,
    region=region,
    spacing=spacing,
    grid=topo_data,
    tension="0.25"  # Adjust tension parameter for smoother interpolation
)

fig.basemap(region=region, projection=projection, frame='a0.05', map_scale='x2c/0.5c+w10')

# Plot the enhanced topography with improved shading
fig.grdimage(
    grid=topo_high_res,
    region=region,
    projection=projection,
    shading="+a45+ne0.7",  # Enhanced shading parameters
    cmap="relief",  # Using relief colormap for better topographic visualization
    transparency=20  # Slight transparency for better feature visibility
)

# Plot coastlines with highest resolution
fig.coast(
    shorelines="0.5/0.5p,black",
    resolution="f",
    water="#EBEBEE",
    borders="1/0.5p,black"
)

#   PLOT FOCAL MECHANISM
filename='catalogue_flegrei_MT_final'             
events_name=os.path.join(catdir,filename+'.pf')              
fm_events = model.load_events(events_name)

switch_deviatoric=False                                                                                                                               
switch_timestamps=False                                                                 

# Loop on events in catalogue and plot FM
for ev in fm_events:
    if switch_deviatoric:
        msix = pmt.to6(ev.moment_tensor.m_up_south_east())
        moment_tensor_par = {
            "mrr": msix[0]* 10**7,
            "mtt": msix[1]* 10**7,
            "mff": msix[2]* 10**7,
            "mrt": msix[3]* 10**7,
            "mrf": msix[4]* 10**7,
            "mtf": msix[5]* 10**7,
            "exponent": 1
            }

        name=ev.name.split('_')[1:]
        name_ev= str(name[0] +'-'+ name[1] +'-'+ name[2] +'_'+ name[3] +':'+ name[4] +':'+ name[5])

        fig.meca(
            spec=moment_tensor_par,
            convention='mt',
            longitude=ev.lon,
            latitude=ev.lat,
            depth=ev.depth,
            scale="0.8c",
            compressionfill="#BD2025",
            extensionfill="white",
            pen="0.5p,gray30,solid"
        )
    else:
        moment_tensor_par = {
            "strike": ev.moment_tensor.strike1,
            "dip": ev.moment_tensor.dip1,
            "rake": ev.moment_tensor.rake1,
            "magnitude": ev.magnitude 
            }
        name=ev.name.split('_')[1:]
        name_ev= str(name[0] +'-'+ name[1] +'-'+ name[2] +'_'+ name[3] +':'+ name[4] +':'+ name[5])

        fig.meca(
            spec=moment_tensor_par,
            longitude=ev.lon,
            latitude=ev.lat,
            depth=ev.depth,
            scale="0.8c",
            compressionfill="#BD2025",
            extensionfill="white",
            pen="0.5p,gray30,solid"
        )
    
    if switch_timestamps:  
        fig.text(
            text=name_ev,
            x=ev.lon,  
            y=ev.lat + 0.0006,  
            font="2p,Helvetica,black", 
            justify="CM"
        )

# Plot stations
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

fig.plot(x=lonsta, y=latsta, style="t0.3", fill="#FFCC4E", pen="black", label='station')

fig.legend()
fig.show()
if switch_deviatoric:
    fig.savefig('../../PLOTS/MAPS/'+filename + '_deviatoric_' + map_name + '_highres.pdf', dpi=300)
else:
    fig.savefig('../../PLOTS/MAPS/'+filename + '_dc_' + map_name + '_highres.pdf', dpi=300)