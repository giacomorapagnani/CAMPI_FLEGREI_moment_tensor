
#download catalogue from INGV
#create catalogue from CSV gossip

########################################################################
########################################################################
#############IMPORTANT: download data from GOSSIP,######################
############## before running, change ##################################
############# the column names in the .csv files ####################### 
########################################################################
########################################################################

# %% LIB
from obspy.clients.fdsn.client import Client
from obspy import UTCDateTime
from obspy.core.event import Catalog
from obspy.core.stream import Stream
from obspy.core.event import Event
from obspy.core.event import Origin
from obspy.core.event import Magnitude
from obspy import read_events
from obspy import read_inventory
from obspy.core.event import ResourceIdentifier
import cartopy.crs as ccrs

from pyrocko import util, model, io, trace, moment_tensor, gmtpy
from pyrocko import pz
from pyrocko import orthodrome as od
from pyrocko.io import quakeml
from pyrocko.io import stationxml as fdsn
from pyrocko.client import catalog
from pyrocko.automap import Map

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
import csv

# %% download/load calalogue INGV

workdir= '../'
catdir =  os.path.join(workdir,'CAT')

client=Client('INGV')

stime=UTCDateTime('2014-01-01T00:00:00')        # CHANGE set start time
etime=UTCDateTime('2025-03-16T15:00:00')        # CHANGE set end time

######################################################################################
######################################################################################
switch_get_events_and_save=True                ############################### SWITCH
######################################################################################
######################################################################################

if switch_get_events_and_save:
    print('downloading events from INGV database')
    cat_INGV=client.get_events(starttime=stime,endtime=etime,
                        minlatitude=40.75,maxlatitude=40.90,minlongitude=14.00,
                        maxlongitude=14.20)


    cat_name=os.path.join(catdir,'INGV/catalogue_flegrei_INGV.xml')
    cat_INGV.write(cat_name,format='QUAKEML')

    cat_mag_INGV = cat_INGV.filter("magnitude >= 2.5")
    
    #cat_mag_INGV.plot(projection='local',resolution='i') #plot

    cat_mag_name=os.path.join(catdir,'INGV/catalogue_flegrei_INGV_mag_2_5.xml')
    cat_mag_INGV.write(cat_mag_name,format='QUAKEML')
    print('creating catalogue INGV in .xml')
    print('number of events selected:', len(cat_mag_INGV), 'out of:',len(cat_INGV))
else:
    cat_name=os.path.join(catdir,'INGV/catalogue_flegrei_INGV.xml')
    cat_INGV=read_events(cat_name)

    cat_mag_name=os.path.join(catdir,'INGV/catalogue_flegrei_INGV_mag_2_5.xml')
    cat_mag_INGV=read_events(cat_mag_name)
    #cat_mag_INGV.plot(projection='local',resolution='i') #plot
    print('loading catalogue INGV in .xml')
    print('number of events selected:', len(cat_mag_INGV), 'out of:',len(cat_INGV))

# create/load pf catalogue
catname_pf = os.path.join(catdir, 'INGV/catalogue_flegrei_INGV.pf')
catname_mag_pf = os.path.join(catdir, 'INGV/catalogue_flegrei_INGV_mag_2_5.pf')

def catalogue_INGV_to_PF(cat,cat_name):
    events = []
    for ev in cat:
        name= str(ev.resource_id).split('=')[1]

        timetmp= str(ev.origins[0].time)
        timestr = timetmp[0:10] + ' ' + timetmp[11:23]                          # format: '2010-01-01 00:00:00.000'
        time = util.str_to_time(timestr)

        lat=    float( ev.origins[0].latitude )
        lon =   float( ev.origins[0].longitude )
        depth = float( ev.origins[0].depth )
        magnitude = float( ev.magnitudes[0].mag )
        events.append(model.Event(name=name, time=time,
                                lat=lat, lon=lon,
                                depth=depth, magnitude=magnitude))
    events.sort(key=lambda x: x.time, reverse=False)
    model.dump_events(events, cat_name)
    return events

######################################################################################
######################################################################################
switch_convert_xml_to_pf=True                  ############################### SWITCH
######################################################################################
######################################################################################

if switch_convert_xml_to_pf:
    print('creating catalogues INGV in .pf')
    cat_pf_INGV=    catalogue_INGV_to_PF(cat_INGV,catname_pf)
    cat_mag_pf_INGV=catalogue_INGV_to_PF(cat_mag_INGV,catname_mag_pf)
else:
    print('loading catalogues INGV in .pf')
    cat_pf_INGV= model.load_events(catname_pf)
    cat_mag_pf_INGV= model.load_events(catname_mag_pf)

# %% Create/load Gossip catalogue
def create_obspy_catalogue(catalogue):
    cat_obs=Catalog()
    for ind,id_number in enumerate(catalogue['#EventID']):
        
        event=Event()
        
        resourceid=ResourceIdentifier(id=str(id_number)) #, referred_object=event) #gives warning


        #comment= Comment()
        #comment.creation_info=cat_all['Level'].iloc[ind]
        
        origin=Origin()
        origin.time=catalogue['Time'].iloc[ind]

        magnitude=Magnitude()

        try:
            origin.latitude=catalogue['Latitude'].iloc[ind]
        except:
            continue                #exclude events not complete in catalogue
        
        try:
            origin.longitude=catalogue['Longitude'].iloc[ind]
        except:
            continue
        
        try:
            origin.depth=catalogue['Depth/km'].iloc[ind] *1000
        except:
            continue
        
        try:
            magnitude.mag=catalogue['Magnitude'].iloc[ind]
        except:
            continue

        try:
            magnitude.mag_errors=catalogue['MagErr'].iloc[ind]
        except:
            None

        try:
            magnitude.magnitude_type=catalogue['MagType'].iloc[ind]
        except:
            None

        event.resource_id=resourceid
        #event.comments.append(comment)
        event.origins.append(origin)
        event.magnitudes.append(magnitude)
        cat_obs.events.append(event)

    return cat_obs

def catalogue_GOSSIP_to_PF(catalogue,catalogue_path):
    events = []

    for ev in catalogue:
        name= str(ev.resource_id)#.split('/')[1] #not needed anymore

        timetmp= str(ev.origins[0].time)
        timestr = timetmp[0:10] + ' ' + timetmp[11:23]                        # format: '2010-01-01 00:00:00.000'
        time = util.str_to_time(timestr)

        magnitude = ev.magnitudes[0].mag 

        lat=ev.origins[0].latitude
        lon =   ev.origins[0].longitude
        depth = ev.origins[0].depth

        if lat!=None and lon!=None and depth!=None and magnitude!=None :
            
            events.append(model.Event(name=name, time=time,
                                lat=lat, lon=lon,
                                depth=depth, magnitude=magnitude))
        
    events.sort(key=lambda x: x.time, reverse=False)
    model.dump_events(events, catalogue_path)

    return events

workdir_GOSSIP='../CAT/GOSSIP_events_cvs/csv/'
save_dir_GOSSIP='../CAT/GOSSIP_events_cvs/'

GOSSIP_name_pf = os.path.join(catdir, 'GOSSIP/catalogue_flegrei_GOSSIP.pf')
GOSSIP_name_pf_mag = os.path.join(catdir, 'GOSSIP/catalogue_flegrei_GOSSIP_mag_2_5.pf')

######################################################################################
######################################################################################
switch_merge_csv_and_convert_to_PF_GOSSIP=  True              ##################SWITCH
######################################################################################
######################################################################################

if switch_merge_csv_and_convert_to_PF_GOSSIP:
    print('merge cvs catalogues GOSSIP and create a .pf')
    directory = os.fsencode(workdir_GOSSIP)
    cat_all=pd.DataFrame()

    for file in os.listdir(directory):
        filename = os.fsdecode(file)

        #if 'events' in filename:
        if filename.endswith(".csv"): 
            cat=pd.read_csv(workdir_GOSSIP + filename)
            print(filename)
            cat=cat.drop(labels=['Area','Type'],axis=1)
            cat['Time'] = cat['Time'].apply(UTCDateTime)
            cat_all=pd.concat( [cat_all,cat] ,ignore_index=True)
        else:
            continue

    for location,id_event in enumerate(cat_all['#EventID']):
        if cat_all['Latitude'].isna().loc[location] and cat_all['Magnitude'].isna().loc[location]:
            cat_all=cat_all.drop(index=location)

    #all events
    cat_all.to_csv( save_dir_GOSSIP + 'events_all.csv' )

    #events >2.5 M
    cat_mag_csv=cat_all[ cat_all['Magnitude'] >= 2.5 ]
    cat_mag_csv.to_csv(save_dir_GOSSIP + 'events_all_mag_2_5.csv')

    #create obspy catalogue for all events
    cat_all_GOSSIP=create_obspy_catalogue(cat_all)

    cat_all_GOSSIP.write(save_dir_GOSSIP + 'catalogue_flegrei_GOSSIP.xml',format='QUAKEML')
    cat_all_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP.xml')
    cat_all_GOSSIP.write(cat_all_name,format='QUAKEML')
    
    #create obspy catalogue for events >2.5 M
    cat_mag_GOSSIP=create_obspy_catalogue(cat_mag_csv)
    cat_mag_GOSSIP.write(save_dir_GOSSIP + 'catalogue_flegrei_GOSSIP_mag_2_5.xml',format='QUAKEML')
    cat_mag_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP_mag_2_5.xml')
    cat_mag_GOSSIP.write(cat_mag_name,format='QUAKEML')

    print('number of events selected:', len(cat_mag_GOSSIP), 'out of:',len(cat_all_GOSSIP))

    #create pf catalogue for all events
    cat_all_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP.pf')
    cat_all_GOSSIP_pf=catalogue_GOSSIP_to_PF(cat_all_GOSSIP,cat_all_name)

    #create pf catalogue for events >2.5 M
    cat_mag_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP_mag_2_5.pf')
    cat_mag_GOSSIP_pf=catalogue_GOSSIP_to_PF(cat_mag_GOSSIP,cat_mag_name)
else:
    print('loading catalogue GOSSIP in .xml and .pf')
    #load all events
    cat_all_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP.xml')
    cat_all_GOSSIP=read_events(cat_all_name)

    cat_all_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP.pf')
    cat_all_GOSSIP_pf=model.load_events(cat_all_name)

    #load events >2.5 M
    cat_mag_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP_mag_2_5.xml')
    cat_mag_GOSSIP=read_events(cat_mag_name)

    cat_mag_name=os.path.join(catdir,'GOSSIP/catalogue_flegrei_GOSSIP_mag_2_5.pf')
    cat_mag_GOSSIP_pf=model.load_events(cat_mag_name)
    print('number of events selected:', len(cat_mag_GOSSIP), 'out of:',len(cat_all_GOSSIP))
# %% compare the catalogues

#cat_pf_INGV        (complete)              cat_mag_pf_INGV     (M>2.5)
#cat_all_GOSSIP_pf  (complete)              cat_mag_GOSSIP_pf   (M>2.5)

######################################################################################
######################################################################################
switch_compare_and_merge_INGV_and_GOSSIP_catalogue= True              ##################SWITCH
######################################################################################
######################################################################################
if switch_compare_and_merge_INGV_and_GOSSIP_catalogue:
    print('creating final .pf catalogue comparing INGV and GOSSIP')
    #1 create a new catalogue with all the events from GOSSIP
    events = []                                                         #name of final catalogue :')
    for ev_G in cat_mag_GOSSIP_pf: # catalogue GOSSIP with M>2.5
        tag = ['GOSSIP_id:'+ str(ev_G.name) + ', mag:' + str(ev_G.magnitude)]
        strtime = util.time_to_str(ev_G.time)
        event_name = 'flegrei_' + strtime[0:4] +'_'+ strtime[5:7]+'_'+strtime[8:10]+'_'+strtime[11:13]+'_'+strtime[14:16]+'_'+strtime[17:19]
        events.append(model.Event(name=event_name, time=ev_G.time,
                                lat=ev_G.lat, lon=ev_G.lon,
                                depth=ev_G.depth,tags=tag))

    events.sort(key=lambda x: x.time, reverse=False)
    ev_to_remove=[]

    #2 add the tags on the common events with INGV complete

    for ind,ev_G in enumerate(events):
        time_min= ev_G.time -5
        time_max= ev_G.time +5
        count=0
        for ev_I in cat_pf_INGV:        #catalogue INGV complete
            if time_min<ev_I.time<time_max:
                ev_G.tags.append('INGV_id:'+ str(ev_I.name) + ', mag:' + str(ev_I.magnitude))
                count+=1
        if count>1:
            ev_to_remove.append(ind)

    #3 remove events close in time
    for ind in reversed(ev_to_remove):
        print('removing event:', util.time_to_str(events[ind].time) ,'too close in time')
        del events[ind]

    events_to_append=[]

    #4 add to catalogue events from INGV of mag > 2.5 not present in GOSSIP > 2.5 catalogue, remove events close in time
    for ev_I in cat_mag_pf_INGV:                    # catalogue INGV with M>2.5
        time_min= ev_I.time -5
        time_max= ev_I.time +5
        count=0
        for ev in events:
            if time_min<ev.time<time_max:
                count+=1
        if count==0:    # new event to add
            count2=0
            for ind,ev_G in enumerate(cat_all_GOSSIP_pf):          #catalogue GOSSIP complete
                if time_min<ev_G.time<time_max:
                    count2+=1
                    ev_num=ind
            if count2==1:  # 1 to 1 correspondence to GOSSIP catalogue  
                tag = ['GOSSIP_id:'+ str(cat_all_GOSSIP_pf[ev_num].name) + ', mag:' + str(cat_all_GOSSIP_pf[ev_num].magnitude) + 
                    ', INGV_id:'+ str(ev_I.name) + ', mag:' + str(ev_I.magnitude)]
                strtime = util.time_to_str(cat_all_GOSSIP_pf[ev_num].time)
                event_name = 'flegrei_' + strtime[0:4] +'_'+ strtime[5:7]+'_'+strtime[8:10]+'_'+strtime[11:13]+'_'+strtime[14:16]+'_'+strtime[17:19]
                events_to_append.append(model.Event(name=event_name, time=cat_all_GOSSIP_pf[ev_num].time,
                                        lat=cat_all_GOSSIP_pf[ev_num].lat, lon=cat_all_GOSSIP_pf[ev_num].lon,
                                        depth=cat_all_GOSSIP_pf[ev_num].depth,tags=tag))
            if count2==0: # event just present in INGV catalogue
                tag = ['INGV_id:'+ str(ev_I.name) + ', mag:' + str(ev_I.magnitude)]
                strtime = util.time_to_str(ev_I.time)
                event_name = 'flegrei_' + strtime[0:4] +'_'+ strtime[5:7]+'_'+strtime[8:10]+'_'+strtime[11:13]+'_'+strtime[14:16]+'_'+strtime[17:19]
                events_to_append.append(model.Event(name=event_name, time=ev_I.time,
                                        lat=ev_I.lat, lon=ev_I.lon,
                                        depth=ev_I.depth,tags=tag))
            if count2>1:
                print(count2,' events too close in time:', util.time_to_str(ev_I.time) )

    events_to_append.sort(key=lambda x: x.time, reverse=False)

    for ev in events_to_append:
        events.append(ev)

    events.sort(key=lambda x: x.time, reverse=False)

    catname = os.path.join(catdir, 'catalogue_flegrei_mag_2_5.pf')
    model.dump_events(events, catname)
    print('Number of events in final catalogue:', len(events))
else:
    print('loading final catalogue in .pf')
    catname = os.path.join(catdir, 'catalogue_flegrei_mag_2_5.pf')
    events=model.load_events(catname)
 # %% manually eliminate events
#no good signals, not enough stations, too close in time

# %% CHECK DATA NAME'S CONSISTENCIES:
# DATA
# BLACKLIST
# MARKERS