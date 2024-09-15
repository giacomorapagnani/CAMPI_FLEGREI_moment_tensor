###  CREATE FIGURE OF RMS SIGNAL VS NOISE FOR REGIONAL STATIONS OF FLEGREI EVENTS

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

plotdir =  os.path.join(workdir,'PLOTS')
plotdir =  os.path.join(plotdir,'RMS_SIGNAL_NOISE')

catdir =  os.path.join(workdir,'CAT')
meta_datadir=os.path.join(workdir,'META_DATA')
datadir=os.path.join(workdir,'DATA_response')                                         #CHANGE

#select stations (pyrocko)
station_name = os.path.join(meta_datadir, 'stations_flegrei_INGV.pf')

st = model.load_stations(station_name)
#print('Number of stations', len(st))

#select catalogue (pyrocko)
catname = os.path.join(catdir, 'catalogue_flegrei_mag_2_5.pf')

events = model.load_events(catname)
#print('Number of events:', len(events))

###################################
# RMS rumore da OT -10 a  OT

for file in os.listdir(datadir):
    #select event
    name = os.fsdecode(file)

    if name.startswith(events[0].name.split('_')[0]): 

        ev_dir=os.path.join(datadir,name)
        ev_name=os.path.join(ev_dir,name + '.mseed')

        for ev in events:
            if ev.name==name:
                print('Selected event:',name)
                #print('lat:',ev.lat,' lon:',ev.lon)
                event=ev
                mag_value=ev.tags[1]

        #select wavelet (obspy)  
        w=read(ev_name)
        #print('number of traces in event:',len(w))

        list_of_stations= ['MODR','PIGN','PAOL','OVO','SORR','IOCA']
        st_coord=[]
        for trace in w:
            for s in st:
                if trace.stats.station==s.station:
                    if trace.stats.station in list_of_stations:
                        n_el_noise= int( round( len(trace.data)/140*40 ) )                     # take time interval [0,40]s of the entire leght (140s) to compute noise's rms
                        n_el_eq1= int( round( len(trace.data)/140*45 ) )                        # take time interval [45,105]s of the entire leght (140s) to compute eq's rms
                        n_el_eq2= int( round( len(trace.data)/140*105 ) )

                        rms_noise= num.sqrt( num.mean(trace.data[:n_el_noise]**2) )
                        rms_eq= num.sqrt( num.mean(trace.data[n_el_eq1:n_el_eq2]**2) )
                        st_coord.append( [trace.stats.station, trace.stats.channel , s.lat, s.lon , rms_eq , rms_noise ] ) #station, channel, lat, long, rms_eq, rms_noise
            
        #print('number of traces:',len(st_coord))

        #calculate distance
        coords_event = (event.lat, event.lon)

        dist_vs_amp=[]

        for row in st_coord:
            coords_station = (row[2], row[3])
            dist= geopy.distance.distance(coords_event, coords_station).km
            rms_log= 20 * num.log10( row[4]/row[5] )
            #print('rms eq : ',row[4],'         rms noise : ',row[5],'          rms log : ',rms_log)
            dist_vs_amp.append( [ row[0], row[1],dist,rms_log ] ) # station, channel, dist, log(rms_eq/rms_noise)

        # separate 3 channels
        channel1=[]
        channel2=[]
        channel3=[]
        distance1=[]
        distance2=[]
        distance3=[]
        hhe=[]
        hhn=[]
        hhz=[]

        for row in dist_vs_amp:
            channel=row[1]
            if channel=='HHE':
                hhe.append(row[3])
                distance1.append(row[2])
                channel1.append(row[0])
                
            elif channel=='HHN':
                hhn.append(row[3])
                distance2.append(row[2])
                channel2.append(row[0])
                
            elif channel=='HHZ':
                hhz.append(row[3])
                distance3.append(row[2])
                channel3.append(row[0])
        
        #SAVE FIGURE SWITCH
        save_fig=True

        # Creazione della figura e dei subplot
        fig, axs = plt.subplots(1, 1, figsize=(17, 11), sharex=False)

        # Plot per il primo subplot
        plt.title(name + ', '+ mag_value)
        axs.scatter(num.array(distance1),
                        num.array(hhe),
                        label='HHE', s=40, color='green')
        
        axs.scatter(num.array(distance2),
                        num.array(hhn),
                        label='HHN', s=40, color='orange')
        
        axs.scatter(num.array(distance3),
                        num.array(hhz),
                        label='HHZ', s=40, color='blue')
        
        axs.set_xlim(xmin=10.,xmax=50.) #max distance of x axis in Km
        axs.set_ylim(ymin=-11.,ymax=27.) #max distance of x axis in Km

        axs.set_ylabel('Amplitude')
        axs.grid(True)
        axs.set_xlabel('Distance [km]')
        axs.legend()

        for i, txt in enumerate(channel1):
            axs.annotate(txt, (distance1[i]+distance1[i]/100, hhe[i]),color='tab:green',size=10)  # '+distance1[i]/50' to shift the name to the right
                                                                                                    
        for i, txt in enumerate(channel2):
            axs.annotate(txt, (distance2[i]+distance2[i]/80, hhn[i]),color='tab:orange',size=10)

        for i, txt in enumerate(channel3):
            axs.annotate(txt, (distance3[i]+distance3[i]/60, hhz[i]),color='tab:blue',size=10)

        if save_fig:

            figname = os.path.join(plotdir, 'ALL_rms_vs_distance.pdf')
            if os.path.isfile(figname):
                os.remove(figname)

            plt.savefig(figname)

            print('Figure',figname.split('/')[-1],'saved!')

        #plt.show()
        plt.close()   