### Download waveforms with obspy from station.xml and catalogue.pf
# %% lib
from pyrocko import util, model, io, trace, moment_tensor, gmtpy
from pyrocko import pz
from pyrocko import orthodrome as od
from pyrocko.io import quakeml
from pyrocko.io import stationxml as fdsn
from pyrocko.client import catalog
from pyrocko.automap import Map
import pyrocko.moment_tensor as pmt
from seiscloud import plot as scp
from seiscloud import cluster as scc
import numpy as num
import os, sys, re, math, shutil
import matplotlib.pyplot as plt
from matplotlib import collections  as mc
from matplotlib import dates
import datetime
import urllib.request
from pyrocko.plot.gmtpy import GMT
from zoneinfo import ZoneInfo

#obspy
from obspy import read_inventory
from obspy.core.stream import Stream
from obspy.clients.fdsn.client import Client
from obspy import UTCDateTime
import pytz

# %% code

workdir='../'
catdir =  os.path.join(workdir,'CAT')
meta_datadir=os.path.join(workdir,'META_DATA')
datadir=os.path.join(workdir,'DATA')                #CHANGE

catname = os.path.join(catdir, 'catalogue_flegrei_mag_2_5.pf')           #CHANGE

cat = model.load_events(catname)
print('Number of events:', len(cat))

client=Client('INGV')
stations_name=os.path.join(meta_datadir, 'stations_flegrei_INGV.xml')           #CHANGE
stations=read_inventory(stations_name)                                 #read

print(stations)

################################################################################
########## DO NOT USE !!!datetime.datetime.fromtimestamp(ev.time)!!! ##########
################################################################################

################################################################################
#################### USE INSTEAD util.time_to_str(ev.time) ####################
################################################################################

# download waveforms strarting from this data:
date_start_download='2024-11-01 00:00:00.000'                               #CHANGE
sec_start_download=util.str_to_time(date_start_download)

count=1
for ev in cat:
    if ev.time>=sec_start_download:
        evID=ev.name

        #transform UTC time
        t = util.time_to_str(ev.time)

        print('\nevent number:',count)
        print('origin UTC time event:',t)

        event_start = UTCDateTime(t) - 40                               #CHANGE: -40 normal
        #print('event starts at:',event_start)

        event_end=UTCDateTime(t) + 140                                    #CHANGE: +140 normal
        #print('event ends at:',event_end)


        wave=Stream()
        for network in stations:
            for  station in network.stations:
                try:
                    wave += client.get_waveforms(starttime=event_start,endtime=event_end,
                                        network=network.code,station=station.code,location='*', channel='HH?',
                                        attach_response=True)
                except:
                    #print(station.code , 'station not recording')
                    continue

        print('traces found:',len(wave.traces))    

        waveletdir=os.path.join(datadir,evID)
        wavelet_name= os.path.join(waveletdir,evID) 

        if os.path.isdir(waveletdir):
            os.remove(wavelet_name + '.mseed')
            os.rmdir(waveletdir)

        os.mkdir(waveletdir)


        wave.write(wavelet_name +'.mseed',format='MSEED')
        print('wavelet dowloaded and saved!')
        count+=1