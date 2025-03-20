# libs
import os

from pyrocko import gf
from pyrocko.gf import LocalEngine, Target, DCSource, ws,MTSource
from pyrocko import trace,model
from pyrocko.gui.marker import PhaseMarker

import numpy as np
import matplotlib.pyplot as plt

# dirs
catdir='../CAT'
metadatadir='../META_DATA'

stations_name=os.path.join(metadatadir,'stations_flegrei_INGV_final.pf')
stations=model.load_stations(stations_name)

catname_VLP=os.path.join(catdir,'catalogue_flegrei_MT_final_VLP_reloc.pf')
events_VLP = model.load_events(catname_VLP)

catname_VT=os.path.join(catdir,'catalogue_flegrei_MT_final.pf')
events_VT = model.load_events(catname_VT)

# Select station
s_name='CPOZ'                           #CHANGE
st=False
for s in stations:
    if s.station==s_name:
        st=s
if not st:
    print(f'Error: station {s_name} not found')

# Select event
e_name='flegrei_2024_04_27_03_44_56'    #CHANGE
#e_name='flegrei_2025_02_16_14_20_02'    #CHANGE

ev_VT=False
for e in events_VT:
    if e.name==e_name:
        ev_VT=e
if not ev_VT:
    print(f'Error: event {e_name} not found in {catname_VT}')

ev_VLP=False
for e in events_VLP:
    if e.name==e_name:
        ev_VLP=e
if not ev_VLP:
    print(f'Error: event {e_name} not found in {catname_VLP}')

# Synth
store_id = 'campiflegrei_near'

engine = LocalEngine(store_superdirs=['../GF_STORES'])

channel_codes = 'ENZ'
targets_VT = [
    Target(
        lat=st.lat,
        lon=st.lon,
        store_id=store_id,
        codes=('', st.station, 'VT', channel_code))
    for channel_code in channel_codes]

targets_VLP = [
    Target(
        lat=st.lat,
        lon=st.lon,
        store_id=store_id,
        codes=('', st.station, 'VLP', channel_code))
    for channel_code in channel_codes]

# MT source representation.

source_mt_VT = MTSource.from_pyrocko_event(ev_VT)

source_mt_VLP = MTSource.from_pyrocko_event(ev_VLP)
source_mt_VLP.stf=gf.ResonatorSTF(30., frequency=0.114)

# return a pyrocko.gf.Reponse object.
response_VT = engine.process(source_mt_VT, targets_VT)
response_VLP = engine.process(source_mt_VLP, targets_VLP)

# list of the requested traces:
synthetic_traces_VT = response_VT.pyrocko_traces()
synthetic_traces_VLP = response_VLP.pyrocko_traces()

# chop heads and tails
trs_VT= [ x.chop(x.tmin+1,x.tmax-1) for x in synthetic_traces_VT ]
trs_VLP= [ x.chop(x.tmin+1,x.tmax-1) for x in synthetic_traces_VLP ]

tlen = 120.
newtrs_VT = []
for tr in trs_VT:
    newtr = tr.copy()
    ydata = newtr.get_ydata()
    first, last = ydata[0], ydata[-1]
    npts = int(tlen/newtr.deltat)
    ydata = np.concatenate( (np.ones(npts) * first, ydata, np.ones(npts) * last) )
    newtr.ydata = ydata
    newtr.shift(-tlen)
    newtr.tmax+= 2* tlen
    newtrs_VT.append(newtr)

tlen = 120.
newtrs_VLP = []
for tr in trs_VLP:
    newtr = tr.copy()
    ydata = newtr.get_ydata()
    first, last = ydata[0], ydata[-1]
    npts = int(tlen/newtr.deltat)
    ydata = np.concatenate( (np.ones(npts) * first, ydata, np.ones(npts) * last) )
    newtr.ydata = ydata
    newtr.shift(-tlen)
    newtr.tmax+= 2* tlen
    newtrs_VLP.append(newtr)

# sum VLP and VT traces
trs_sum = []
channels=['E','N','Z']
for n,ch in enumerate(channels):
    dt=newtrs_VLP[n].deltat
    tmin = newtrs_VLP[n].tmin
    tshift= int( (newtrs_VT[n].tmin - newtrs_VLP[n].tmin) / dt )
    len_tr_VT= len (newtrs_VT[n].get_ydata())
    tr1=newtrs_VLP[n].get_ydata()
    tr2=newtrs_VT[n].get_ydata()
    trsum=tr1.copy()
    trsum[tshift:tshift+len_tr_VT] += tr2
    trs_sum.append(trace.Trace(
                station=s_name, channel=ch,location='VLP + VT', deltat=dt, tmin=tmin, ydata=trsum))

trs=[]
#trs.extend(trs_VT)
#trs.extend(trs_VLP)

trs.extend(newtrs_VT)
trs.extend(newtrs_VLP)
trs.extend(trs_sum)

# matplotlib figure
fig, axs = plt.subplots(9, 2, figsize=(10,20))
axs = axs.ravel()
i=0

freq_ranges= [ [0.5,2],[0.075,0.125] ]
for tr in trs:
    
    for fq in freq_ranges:
        tmp_trace= tr.copy() 
        tmp_trace.lowpass(4,fq[1])
        tmp_trace.highpass(4,fq[0])
        o_t = int( round( ev_VT.time ) ) 
        if fq == [0.5,2] :
            chop1,chop2= 10 , 20
        else:
            chop1,chop2= 60 , 120
        tmp_trace.chop(o_t-chop1, o_t + chop2)
        tax=np.arange(o_t-chop1, o_t + chop2, tr.deltat)

        axs[i].plot( tax, tmp_trace.get_ydata(),color='k', label=f'{tmp_trace.location}, {tmp_trace.channel}')    
        axs[i].grid(True)
        #axs[i].set_ylabel('Counts')
        axs[i].legend(loc=1)

        i+=1
#plt.show()
fig.savefig('../PLOTS/synth_test.pdf')

'''
# In addition to that it is also possible to extract interpolated travel times
# of phases which have been defined in the store's config file.
store = engine.get_store(store_id)

markers = []
for t in targets:
    dist = t.distance_to(source_mt)
    depth = source_mt.depth
    arrival_time = store.t('begin', (depth, dist))
    m = PhaseMarker(tmin=arrival_time,
                    tmax=arrival_time,
                    phasename='P',
                    nslc_ids=(t.codes,))
    markers.append(m)
'''
# snuffler
#trace.snuffle(trs)      #, markers=markers)