import numpy as np
from obspy.core import read
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

# Read raw data
workdir='/Users/giaco/UNI/PhD_CODE/GIT/CAMPI_FLEGREI_moment_tensor/DATA_VLP/'
event_name='flegrei_2024_04_27_03_44_56'
st = read(workdir + event_name + '/' + event_name + '.mseed')

station_name='CPOZ'
channel_name='HHZ'
st_raw=st.select(station=station_name,channel=channel_name)


# Copy and filtering
st_filt = st_raw.copy()
st_filt.detrend("demean")
st_filt.taper(max_percentage=0.05)
fmin=4.
fmax=15.
st_filt.filter("bandpass", freqmin=fmin, freqmax=fmax, corners=4 ,zerophase=True )

# time axis
npts=np.size(st_filt[0].data)
dt=st_filt[0].stats.delta
t=np.arange(npts)*dt

# Plot
plt.title(f'{event_name}, station: {station_name}, channel: {channel_name}, filtering: {fmin}-{fmax} Hz')
plt.plot(t,st_raw[0].data/np.max(np.abs(st_raw[0].data)),label='raw')
plt.plot(t,st_filt[0].data/np.max(np.abs(st_filt[0].data)),label='filtered')
plt.legend()
plt.show()