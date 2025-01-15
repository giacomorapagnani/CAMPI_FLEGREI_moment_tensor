import pygmt
import numpy as np
import os
from pyrocko import util, model, io, trace, gmtpy
import pyrocko.moment_tensor as pmt

workdir='../../'
catdir = os.path.join(workdir,'CAT')
metadatadir = os.path.join(workdir,'META_DATA')

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
    minlat=40.78
    maxlat=40.85
    map_name='gulf'

# Create a larger region for better interpolation
padding = 0.05  # Increased padding for better edge interpolation
region_extended = [
    minlon - padding,
    maxlon + padding,
    minlat - padding,
    maxlat + padding
]

# Configure PyGMT settings for high quality output
pygmt.config(
    FORMAT_GEO_MAP="ddd.xxF",
    PS_MEDIA="A3",
    FONT_ANNOT_PRIMARY="8p",
    FONT_LABEL="10p"
)

# Load the initial topography data
topo_data = pygmt.datasets.load_earth_relief(
    resolution="01s",
    region=region_extended
)

# Calculate ultra-high resolution spacing (approximately 5 meters)
desired_spacing = 0.00005

# Resample to ultra-high resolution
topo_resampled = pygmt.grdsample(
    grid=topo_data,
    spacing=[desired_spacing, desired_spacing],
    region=region_extended,
    interpolation="c"  # Cubic spline interpolation
)

# Create illumination for enhanced relief
topo_gradient = pygmt.grdgradient(
    grid=topo_resampled,
    azimuth=45,
    normalize="t0.5"
)

# CREATE FIGURE
fig = pygmt.Figure()

# Define the actual map region and projection
region = [minlon, maxlon, minlat, maxlat]
projection = "M20c"  # Increased size for better detail

# Set up the basemap
fig.basemap(
    region=region,
    projection=projection,
    frame=["af", "WSen"]
)

# Plot the enhanced topography
fig.grdimage(
    grid=topo_resampled,
    region=region,
    projection=projection,
    shading=topo_gradient,
    cmap="gray",
)

# Add refined coastlines
fig.coast(
    region=region,
    projection=projection,
    shorelines="0.1p,black",
    resolution="f",
    borders="1/0.1p,black",
    water="#EBEBEE"
)

# Add map scale
fig.basemap(map_scale="jBL+w2k+o0.5c/0.5c+f+u")

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
            pen="0.5p,black"
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
            pen="0.5p,black"
        )
    
    if switch_timestamps:  
        fig.text(
            text=name_ev,
            x=ev.lon,  
            y=ev.lat + 0.0006,  
            font="6p,Helvetica,black", 
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

# Plot stations with improved visibility
fig.plot(
    x=lonsta,
    y=latsta,
    style="t0.4c",
    fill="#FFCC4E",
    pen="0.5p,black",
    label='station'
)

fig.legend()

# Save with ultra-high DPI
if switch_deviatoric:
    fig.savefig(
        f'../../PLOTS/MAPS/{filename}_deviatoric_{map_name}_highres.pdf',
        dpi=200,
    )
else:
    fig.savefig(
        f'../../PLOTS/MAPS/{filename}_dc_{map_name}_highres.pdf',
        dpi=200,
    )

fig.show()