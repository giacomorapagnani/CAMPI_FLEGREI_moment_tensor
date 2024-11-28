from obspy import read
from obspy import read_events
from obspy import read_inventory
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import pickle
from pyrocko import util, model, io, trace, moment_tensor, gmtpy
import numpy as np
from matplotlib import pyplot as plt

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

def filter_and_normalize(trace, corner_frequency): # to do: band pass
    tr= trace.copy()
    tr.highpass(4,corner_frequency)
    data_tr=tr.get_ydata().astype(float)
    data_tr /= np.max( np.abs(data_tr) )
    tr.set_ydata(data_tr)
    return tr

cmis_z=[]
cque_z=[]
corner_freq=0.01

for ev in cat:

    for file in os.listdir(datadir):
        #select event
        name = os.fsdecode(file)

        if name.startswith('flegrei') and name == ev.name: 
            ev_dir=os.path.join(datadir,name)
            ev_name=os.path.join(ev_dir,name + '.mseed')

            traces=io.load(ev_name)
            #print('loading event:',ev_name.split('/')[2])

            for tr in traces:
                if tr.station=='CMIS' and tr.channel=='HHZ' :
                        cmis_z.append( filter_and_normalize(tr,corner_freq) )
                if tr.station=='CQUE' and tr.channel=='HHZ':
                        cque_z.append( filter_and_normalize(tr,corner_freq) )
        else:
            continue

mat=np.zeros((len(cque_z),len(cque_z)))

for i,tr_row in enumerate(cque_z):
    print(f'loading: {round(i/len(cque_z)*100)} % completed')
    for j, tr_col in enumerate(cque_z):
        c=trace.correlate(tr_row,tr_col,mode='same',normalization='normal')
        t, coef = c.max()
        #print(coef)
        mat[i,j]=coef

plt.figure('correlation matrix')
plt.imshow(mat)
plt.colorbar()


plt.show()