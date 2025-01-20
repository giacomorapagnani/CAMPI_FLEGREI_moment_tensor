import pygmt
import numpy as np
import pandas as pd

# Read the XYZ data
data = pd.read_csv('/Users/giaco/Downloads/MappaFlegrei.dat', sep='\s+', header=None, names=['x', 'y', 'z'])

# Create the grid from XYZ data
# Adjust the spacing (inc) and region according to your data
region = [
    data['x'].min(),  # West
    data['x'].max(),  # East
    data['y'].min(),  # South
    data['y'].max(),  # North
]

# Create a grid using surface interpolation
grid = pygmt.surface(
    data=data,
    region=region,
    spacing='0.001d',  # Adjust this value based on your data resolution
    verbose='q'
)

# Create the figure and plot
fig = pygmt.Figure()

# Plot the grid
fig.grdimage(
    grid=grid,
    region=region,
    projection='M15c',  # Mercator projection, 15cm width
    shading='+a45+ne0.5',
    cmap='gray'
)

# Add colorbar
fig.colorbar(frame=["a100", "x+lElevation", "y+lm"])

# Add coast for reference (if needed)
fig.coast(shorelines=True, borders=["1/0.5p,black"])

# Show the plot
fig.show()