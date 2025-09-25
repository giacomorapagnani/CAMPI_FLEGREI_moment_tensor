# !!! not working!!!

# libs
import os
import sys
from pyrocko import gf,trace,model,util,io
from pyrocko.gf import LocalEngine, Target, DCSource, ws,MTSource
from pyrocko.gui.marker import PhaseMarker

import numpy as np
import matplotlib.pyplot as plt
import datetime

# dirs
catdir='../CAT'
metadatadir='../META_DATA'

stations_name=os.path.join(metadatadir,'stations_flegrei_INGV_final.pf')
stations=model.load_stations(stations_name)

catname_VT=os.path.join(catdir,'catalogue_flegrei_MT_final.pf')
events_VT = model.load_events(catname_VT)

# Select station
s_name='CFMN'                                                   #CHANGE
st=False
for s in stations:
    if s.station==s_name:
        st=s
if not st:
    sys.exit(f'Error: station {s_name} not found')
    

# Select event
e_name='flegrei_2024_04_27_03_44_56'            #CHANGE reference: flegrei_2024_04_27_03_44_56
                                                #flegrei_2025_02_16_14_30_02
                                                #flegrei_2024_07_26_11_46_21
                                                #flegrei_2024_05_22_06_28_00

ev_VT=False
for e in events_VT:
    if e.name==e_name:
        ev_VT=e
if not ev_VT:
    sys.exit(f'Error: event {e_name} not found in {catname_VT}')

# Synth
store_id = 'campiflegrei_near'

engine = LocalEngine(store_superdirs=['../GF_STORES'])

channel_codes = 'ENZ'
targets_VT = [
    Target(
        lat=st.lat,
        lon=st.lon,
        store_id=store_id,
        codes=('', st.station, 'synth', channel_code))
    for channel_code in channel_codes]

# MT source representation.

source_mt_VT = MTSource.from_pyrocko_event(ev_VT)

# return a pyrocko.gf.Reponse object.
response_VT = engine.process(source_mt_VT, targets_VT)

# list of the requested traces:
synthetic_traces_VT = response_VT.pyrocko_traces()

# chop heads and tails
trs_VT= [ x.chop(x.tmin+1,x.tmax-1) for x in synthetic_traces_VT ]
# add longer heads and tails
tlen = 180. # lentgh of buffer
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

# save synth traces (watch out for the 'location' parameter: max 2 letters)
#io.save(trs, '../PLOTS/SYNTH/synth_traces.mseed')

# load observed traces
datadir='../DATA_VLP_RESPONSE'
dir_name=os.path.join(datadir,e_name)
file_name=os.path.join(dir_name,e_name+'.mseed')
obs_trs_all = io.load(file_name)
obs_trs = [ tr for tr in obs_trs_all if tr.station == s_name]
for tr in obs_trs:
    tr.location='recorded'

# Create trace list with all traces
trs=[]
#trs.extend(trs_VT)     # non chopped
#trs.extend(trs_VLP)    # non chopped
trs.extend(newtrs_VT)   # chopped
trs.extend(obs_trs)     # obs

# snuffler
#trace.snuffle(trs)

# Figures 
colors=['#BD2025','#64DC89','#FFCC4E','#FF7400']    # red, yellow, orange, green
freq_ranges= [ [0.5,2] ]
# y limits
ylims= [ [4.5e-4 , 4.5e-4] , [0.6e-4 , 1.1e-4] ]          # reference: flegrei_2024_04_27_03_44_56
#ylims= [ [35e-4 , 20e-4] , [3e-4 , 10e-4] ]              # flegrei_2025_03_13_00_25_02 (large)
#ylims= [ [0.4e-4 , 0.4e-4] , [0.1e-4 , 0.3e-4] ]          # small


trs_mseed=[]
for l,fq in enumerate(freq_ranges):
    fig, axs =   plt.subplots(3, 1, figsize=(12,8), sharex=True)
    axs = axs.ravel()
    i=0
    for n,tr in enumerate(trs):
        tmp_trace= tr.copy() 
        tmp_trace.lowpass(4,fq[1])
        tmp_trace.highpass(4,fq[0])

        chop1,chop2= 5 , 15

        # chop 
        #o_t = int( round( ev_VT.time - tr.tmin ) )
        o_t = ev_VT.time
        tmp_trace.chop(o_t-chop1, o_t + chop2)
        # shift to 0, actually not to 00:00:00 but to 23:00:00 (DNW)
        new_tmin= 23*60*60.         #23:00:00
        new_tmax = new_tmin + (tmp_trace.tmax - tmp_trace.tmin) 
        tmp_trace.tmin= new_tmin
        tmp_trace.tmax= new_tmax

        # Check if arrays are of the same length
        tax=np.arange(new_tmin,new_tmax, tmp_trace.deltat)
        yax=tmp_trace.get_ydata()
        len_t, len_y = len(tax) , len(yax)
        if len_t < len_y:
            eq_dates = [datetime.datetime.fromtimestamp(t) for t in tax]
            yax= yax[0:len_t] # cut last element
            print(f'Warning: {tmp_trace.location} time ax length smaller than displacement\n {len_t} =/= {len_y}')
        elif len_t > len_y:
            eq_dates = [datetime.datetime.fromtimestamp(t) for t in tax[0:len_y]]
            print(f'Warning: {tmp_trace.location} time ax length larger than displacement\n {len_t} =/= {len_y}')
        else:
            eq_dates = [datetime.datetime.fromtimestamp(t) for t in tax]

        # Plot
        axs[i%3].plot( eq_dates, yax,color=colors[n//3], linewidth=1, 
                    label=f'{tmp_trace.location}')
        if i<3:
            axs[i%3].plot( eq_dates, -yax,color=colors[2], linewidth=1, 
                    label=f'{tmp_trace.location} flipped')

        # add flavor    
        axs[i%3].grid(True)
        if i < 9 :
            axs[i%3].set_ylim(- ylims[l][0], + ylims[l][0])
        elif i >= 9:
            axs[i%3].set_ylim(- ylims[l][1], + ylims[l][1])
        if i==0 or i==3 or i==6 or i==9:
            axs[i%3].set_ylabel('Displacement [m]')
        if i<3:
            axs[i%3].set_title(f'{tmp_trace.channel} channel',fontsize=15)
        if i>8:
            axs[i%3].set_xlabel('Time')
        axs[i%3].legend(loc=1)

        trs_mseed.append(tmp_trace)

        i+=1
    plt.title(f'Event: {e_name[8:]}, Station: {s_name}')
    fig.tight_layout()
    #fig.savefig(f'../PLOTS/SYNTH/{e_name}_{s_name}_sum_traces_{fq[0]}_{fq[1]}_Hz.pdf')
plt.show()