import pygmt
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# Read the XYZ data
#data = pd.read_csv('/Users/giaco/Downloads/CF-xyz_new.dat', sep='\s+', header=None, names=['lat', 'lon', 'z'])
data = pd.read_csv('/Users/giaco/Downloads/CF_LatLon.txt', sep=',', header=None, names=['lat', 'lon', 'z'])

# Create the grid from XYZ data
# Adjust the spacing (inc) and region according to your data
region = [
    data['lat'].min(),  # West
    data['lat'].max(),  # East
    data['lon'].min(),  # South
    data['lon'].max(),  # North
]

# Create a grid using surface interpolation
grid = pygmt.surface(
    data=data,
    region=region,
    spacing='0.1s',  # Adjust this value based on your data resolution
)

# Create the figure and plot 
fig = pygmt.Figure()

# Plot the grid
fig.grdimage(
    grid=grid,
    region=region,
    projection='M14.1426817/40.862011445/10c',  # Mercator projection, 15cm width
    shading='+a45+ne0.5',
    cmap='gray'
)

# Add colorbar
#fig.colorbar(frame=["a100", "x+lElevation", "y+lm"])

# Add coast for reference (if needed)
#fig.coast(shorelines=True, borders=["1/0.5p,black"])

# Show the plot
fig.show()
fig.savefig('../../PLOTS/map_custom.pdf')