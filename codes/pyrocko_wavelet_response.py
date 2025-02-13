### REMOVE INSTRUMENTAL RESPONSE FROM DOWNLOADED WAVEFORMS WITH STATION.XML
### AND SAVE NEW-WAVEFORMS IN NEW DIRECTORY 

import matplotlib.pyplot as plt
import numpy as num

from pyrocko import util, model, io, trace, moment_tensor, gmtpy
from pyrocko import pz
from pyrocko import orthodrome as od
from pyrocko.io import quakeml
from pyrocko.io import stationxml as fdsn
from pyrocko.client import catalog
from pyrocko.automap import Map

from obspy.clients.fdsn.client import Client
from obspy import UTCDateTime
from obspy.core.event import Catalog
from obspy.core.stream import Stream
from obspy.core.event import Event
from obspy.core.event import Origin
from obspy.core.event import Magnitude
from obspy import read
from obspy import read_events
from obspy import read_inventory
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import pickle

import geopy.distance

workdir='../'

datadir=os.path.join(workdir,'DATA_VLP')                                         #CHANGE
newdatadir=os.path.join(workdir,'DATA_VLP_response')                             #CHANGE

###################################
meta_datadir=os.path.join(workdir,'META_DATA')

stations_name=os.path.join(meta_datadir, 'stations_flegrei_INGV_final.xml')
stations=read_inventory(stations_name)                             

#print(stations)

for file in os.listdir(datadir):
    #select event
    name = os.fsdecode(file)

    if name.startswith('.'): 
        continue
    else:
        ev_dir=os.path.join(datadir,name)
        ev_name=os.path.join(ev_dir,name + '.mseed')

        #select wavelet (obspy)  
        w=read(ev_name)
        print('loading event:',ev_name.split('/')[2])

        #wave.merge(fill_value=0)
        # trim over the [t1, t2] interval
        #wave.trim(starttime=event_start, endtime=event_end, pad=True, fill_value=0)

        # remove trend
        w.detrend("demean")
        
        #remove instrumental response
        #pre_filt = [0.1, 0.2, 20,30]       # for small eq
        pre_filt = [0.01, 0.03, 10,15]       # for big eq


        #remove instrumental response
        w.remove_response(inventory=stations, output='DISP', pre_filt=pre_filt)

        waveletdir=os.path.join(newdatadir,name)
        wavelet_name= os.path.join(waveletdir,name)  
        if os.path.isdir(waveletdir):
            os.remove(wavelet_name + '.mseed')
            os.rmdir(waveletdir)

        os.mkdir(waveletdir)  
        w.write(wavelet_name +'.mseed',format='MSEED')
        print('response removed and saved!')
