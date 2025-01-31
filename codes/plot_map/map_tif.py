import rasterio
import numpy as np
import pygmt

# Load the TIF file
with rasterio.open('/Users/giaco/Downloads/w45090_s10_INGV/w45090_s10.tif') as src:
    # Read the raster data
    raster_data = src.read(1)  # Assumes first band
    
    # Get geotransform and bounds
    transform = src.transform
    bounds = src.bounds

# Create temporary grid file
grid_filename = 'temp_grid.nc'

# Prepare coordinate meshgrid
x = np.linspace(bounds.left, bounds.right, raster_data.shape[1])
y = np.linspace(bounds.bottom, bounds.top, raster_data.shape[0])
xx, yy = np.meshgrid(x, y)

# Create grid using GMT
pygmt.xyz2grd(
    data=np.column_stack([xx.ravel(), yy.ravel(), raster_data.ravel()]),
    outgrid=grid_filename,
    region=[bounds.left, bounds.right, bounds.bottom, bounds.top],
    spacing=[abs(transform.a), abs(transform.e)]
)

# Create a figure
fig = pygmt.Figure()

# Use a custom projection that can handle large coordinate ranges
fig.basemap(
    region=[bounds.left, bounds.right, bounds.bottom, bounds.top],
    projection='X15c',  # Simple linear projection
    frame=['af', 'WSen']  # Add grid lines and annotations
)

# Plot the grid
fig.grdimage(
    grid=grid_filename,
    cmap='relief'
)

# Add a colorbar
fig.colorbar(frame='+l"Elevation"')

# Save the figure
fig.savefig('output_map.png')