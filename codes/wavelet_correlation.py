from obspy import read
from obspy import read_events
from obspy import read_inventory
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import pickle
from pyrocko import util, model, io, trace, moment_tensor, gmtpy


import geopy.distance

workdir='../'
datadir=os.path.join(workdir,'DATA')
catdir=os.path.join(workdir,'CAT')
meta_datadir=os.path.join(workdir,'META_DATA')

stations_name=os.path.join(meta_datadir, 'stations_flegrei_INGV.xml')       #CHANGE
stations=read_inventory(stations_name)                             
#print(stations)

cat_name=os.path.join(catdir,'catalogue_flegrei_mag_2_5.pf')               #CHANGE
cat=model.load_events(cat_name)

sel_tr_HHE=[]
sel_tr_HHN=[]
sel_tr_HHZ=[]
sel_tr=[]

for ev in cat:

    for file in os.listdir(datadir):
        #select event
        name = os.fsdecode(file)

        if name.startswith('flegrei') and name == ev.name: 
            ev_dir=os.path.join(datadir,name)
            ev_name=os.path.join(ev_dir,name + '.mseed')

            #select wavelet (obspy)  
            w=read(ev_name)
            print('loading event:',ev_name.split('/')[2])

            for tr in w:
                if tr.stats.station=='CMIS':
                    if tr.stats.channel=='HHE':
                        sel_tr_HHE.append(tr)
                    if tr.stats.channel=='HHN':
                        sel_tr_HHN.append(tr)
                    if tr.stats.channel=='HHZ':
                        sel_tr_HHZ.append(tr)
                    sel_tr.append(tr)
        else:
            continue