### Check if station.xml has incorrect zeros, poles and correction factors
### remove un-wanted stations (for big event inversions)
### correct the wrong values

import numpy as np
import matplotlib.pyplot as plt
import os
import pandas as pd
from obspy import UTCDateTime
from obspy.clients.fdsn.client import Client
from obspy.core.event import Catalog
from obspy.core.event import Event
from obspy.core.stream import Stream
from obspy.core.event import Origin
from obspy.core.event import Magnitude
from obspy.core.event.base import Comment
from obspy.core.event import ResourceIdentifier
from obspy import read_events
from obspy import read_inventory
import pickle
from pyrocko import util

#read flegrei stations
workdir= '../'
catdir =  os.path.join(workdir,'CAT')
meta_data_dir= os.path.join(workdir,'META_DATA')
filename='stations_flegrei_INGV_1980'                             #CHANGE
stations_xml_name=os.path.join(meta_data_dir, filename + '.xml')          


#%%% list of stations with GURALP CMG-40T-60S sensor
###################################################
check_stations=True ########################SWITCH
###################################################

if check_stations:

    inv_f=read_inventory(stations_xml_name)
    #print(inv_f)

    st_list=[]

    for network in inv_f:
        for station in network:
            for channel in station.channels:
                if channel.sensor.description == 'GURALP CMG-40T-60S':
                        data_logger=channel.data_logger.description                 #analog digital convertor
                        trans_funct_type=channel.response.response_stages[0]._pz_transfer_function_type     #transfer function type
                        t1=util.time_to_str(channel.start_date)                   #start of recording time
                        try:
                            t2=util.time_to_str(channel.end_date)                     #end of recording time
                        except:
                            t2='None'
                        norm_factor=channel.response.response_stages[0].normalization_factor     #normalization factor: A0
                        g0=channel.response.response_stages[0].stage_gain                        #G0
                        try:
                            find_correct_stage=channel.response.response_stages[1].cf_transfer_function_type
                            if find_correct_stage == 'DIGITAL':
                                stage_gain=channel.response.response_stages[1].stage_gain       #stage gain
                            else:
                                stage_gain='!STAGE GAIN ERROR!'
                        except:
                            find_correct_stage=channel.response.response_stages[2].cf_transfer_function_type
                            if channel.response.response_stages[2].cf_transfer_function_type == 'DIGITAL':
                                stage_gain=channel.response.response_stages[2].stage_gain       #stage gain
                            else:
                                stage_gain='!STAGE GAIN ERROR!'
                        zeros=channel.response.response_stages[0].zeros                         #zeros
                        poles=channel.response.response_stages[0].poles                         #poles
                        sensitivity=channel.response.instrument_sensitivity.value               #sensitivity
                        st_list.append([[network.code +'_'+ station.code +'_'+ channel.code],[data_logger],[trans_funct_type],[t1],[t2],[sensitivity],[norm_factor],[g0],[stage_gain],[zeros],[poles]])

    #st_list values:
    #                    [0]network_station_channel [1]data_logger [2]transfer_function_type
    #                    [3]start_time  [4]end_time  
    #                    [5]SENSITIVITY  [6]NORM_FACTOR  [7]G0  [8]STAGE_GAIN  [9]ZEROS  [10]POLES

    '''
    for ch in st_list:
        print(ch[0],ch[1],ch[3],ch[4])
    '''
    '''
    for ch in st_list:
        if ch[1]!=['INGV GILDA']:
            print(ch[0],ch[1],ch[3],ch[4])
            print('sens:',ch[5],'norm factor:',ch[6],'G0:',ch[7],'stage gain:',ch[8])
            print('zeros:',ch[9],'poles:',ch[10],'\n')
    '''

    inv_f.plot(projection='local',resolution='h')

    save_list=True
    if save_list:
        file_dir=os.path.join(meta_data_dir,'extra')
        file_st_list=os.path.join(file_dir, filename + '_w_GURALP_40T_60S.txt')

        with open(file_st_list, 'w') as output:
            for row in st_list:
                output.write(str(row) + '\n')

#%%% remove stations in xml file
####################################################
remove_stations=False ########################SWITCH
####################################################

#STATIONS REMOVED IN 'stations_flegrei_INGV_final.xml'
# CAFL CAWE CCAP NAPI

if remove_stations:
    inv_f=read_inventory(stations_xml_name)
    inv_new=inv_f.copy()

    inv_new=inv_new.remove(network='ZM')
    inv_new=inv_new.remove(station='VPOB')
    inv_new=inv_new.remove(station='VVDG')
    inv_new=inv_new.remove(station='VARP')
    inv_new=inv_new.remove(station='VBKN')
    inv_new=inv_new.remove(station='VBKS')
    inv_new=inv_new.remove(station='VBKW')
    inv_new=inv_new.remove(station='VCNE')
    inv_new=inv_new.remove(station='VBKE') # good vesuvio's station
    inv_new=inv_new.remove(station='VCRE')
    inv_new=inv_new.remove(station='VPOB')
    inv_new=inv_new.remove(station='VTIR')
    inv_new=inv_new.remove(station='VTRZ')
    inv_new=inv_new.remove(station='VVDG')
    inv_new=inv_new.remove(station='CRTO')
    inv_new=inv_new.remove(station='PTMR')
    inv_new=inv_new.remove(station='ICVJ')
    inv_new=inv_new.remove(station='IMTC')
    inv_new=inv_new.remove(station='IFOR') # good ischia's station
    inv_new=inv_new.remove(station='IBCM')
    inv_new=inv_new.remove(station='IVLC')
    inv_new=inv_new.remove(station='IPSM')

    inv_new.plot(projection='local',resolution='h')

    save_xml=True

    if save_xml:
        inv_new.write(meta_data_dir+'/' + filename + '_stations_removed.xml',format='STATIONXML')                        #save
        print('station.xml SAVED!')

#%%% correct stations values in xml file
####################################################
correct_stations=True ########################SWITCH
####################################################

if correct_stations:
    inv_f=read_inventory(stations_xml_name)
    #print(inv_f)

    #CORRECT VALUES:
    norm_factor_CORRECT=571508000.
    g0_CORRECT=800.

    stage_gain_CORRECT_gilda=304878.
    sensitivity_CORRECT_gilda=243902000.   

    stage_gain_CORRECT_affinity=1e6
    sensitivity_CORRECT_affinity=8e8      

    zeros_CORRECT=[0j, 0j]
    poles_CORRECT=[(-0.074016+0.074016j),(-0.074016-0.074016j),(-502.65+0j),(-1005+0j),(-1131+0j)]

    for network in inv_f:
        for station in network:
            for channel in station.channels:
                if channel.sensor.description == 'GURALP CMG-40T-60S' and channel.data_logger.description == 'INGV GILDA':
                        correction=False
                        t1=util.time_to_str(channel.start_date)                   #start of recording time
                        try:
                            t2=util.time_to_str(channel.end_date)                     #end of recording time
                        except:
                            t2='Now'
                        if norm_factor_CORRECT!=channel.response.response_stages[0].normalization_factor:     #normalization factor: A0
                            channel.response.response_stages[0].normalization_factor=norm_factor_CORRECT
                            correction=True
                        if g0_CORRECT != channel.response.response_stages[0].stage_gain:                        #G0
                            channel.response.response_stages[0].stage_gain=g0_CORRECT
                            correction=True
                        try:
                            find_correct_stage=channel.response.response_stages[1].cf_transfer_function_type
                            if find_correct_stage == 'DIGITAL':
                                if stage_gain_CORRECT_gilda!=channel.response.response_stages[1].stage_gain:       #stage gain
                                    channel.response.response_stages[1].stage_gain=stage_gain_CORRECT_gilda
                                    correction=True
                            else:
                                print('!STAGE GAIN ERROR!')
                        except:
                            find_correct_stage=channel.response.response_stages[2].cf_transfer_function_type
                            if find_correct_stage == 'DIGITAL':
                                if stage_gain_CORRECT_gilda!=channel.response.response_stages[2].stage_gain:       #stage gain
                                    channel.response.response_stages[2].stage_gain=stage_gain_CORRECT_gilda
                                    correction=True
                            else:
                                print('!STAGE GAIN ERROR!')
                        if set(zeros_CORRECT)!=set(channel.response.response_stages[0].zeros):                         #zeros
                            channel.response.response_stages[0].zeros=zeros_CORRECT
                            correction=True
                        if set(poles_CORRECT)!=set(channel.response.response_stages[0].poles):                         #poles
                            channel.response.response_stages[0].poles=poles_CORRECT
                            correction=True
                        if sensitivity_CORRECT_gilda!=channel.response.instrument_sensitivity.value:               #sensitivity
                            channel.response.instrument_sensitivity.value=sensitivity_CORRECT_gilda
                            correction=True

                        if correction:
                            print('station',station.code,', channel',channel.code,', in time interval:',t1,'--->',t2,'| CORRECTED!')

                if channel.sensor.description == 'GURALP CMG-40T-60S' and channel.data_logger.description == 'GURALP Affinity':
                        correction=False
                        t1=util.time_to_str(channel.start_date)                   #start of recording time
                        try:
                            t2=util.time_to_str(channel.end_date)                     #end of recording time
                        except:
                            t2='Now'
                        if norm_factor_CORRECT!=channel.response.response_stages[0].normalization_factor:     #normalization factor: A0
                            channel.response.response_stages[0].normalization_factor=norm_factor_CORRECT
                            correction=True
                        if g0_CORRECT != channel.response.response_stages[0].stage_gain:                        #G0
                            channel.response.response_stages[0].stage_gain=g0_CORRECT
                            correction=True
                        try:
                            find_correct_stage=channel.response.response_stages[1].cf_transfer_function_type
                            if find_correct_stage == 'DIGITAL':
                                if stage_gain_CORRECT_affinity!=channel.response.response_stages[1].stage_gain:       #stage gain
                                    channel.response.response_stages[1].stage_gain=stage_gain_CORRECT_affinity
                                    correction=True
                            else:
                                print('!STAGE GAIN ERROR!')
                        except:
                            find_correct_stage=channel.response.response_stages[2].cf_transfer_function_type
                            if find_correct_stage == 'DIGITAL':
                                if stage_gain_CORRECT_affinity!=channel.response.response_stages[2].stage_gain:       #stage gain
                                    channel.response.response_stages[2].stage_gain=stage_gain_CORRECT_affinity
                                    correction=True
                            else:
                                print('!STAGE GAIN ERROR!')
                        if set(zeros_CORRECT)!=set(channel.response.response_stages[0].zeros):                         #zeros
                            channel.response.response_stages[0].zeros=zeros_CORRECT
                            correction=True
                        if set(poles_CORRECT)!=set(channel.response.response_stages[0].poles):                         #poles
                            channel.response.response_stages[0].poles=poles_CORRECT
                            correction=True
                        if sensitivity_CORRECT_affinity!=channel.response.instrument_sensitivity.value:               #sensitivity
                            channel.response.instrument_sensitivity.value=sensitivity_CORRECT_affinity
                            correction=True

                        if correction:
                            print('station',station.code,', channel',channel.code,', in time interval:',t1,'--->',t2,'| CORRECTED!')


    save_xml=True

    if save_xml:
        inv_f.write(meta_data_dir+'/' + filename + '_CORRECTED.xml',format='STATIONXML')                        #save
        print('station.xml SAVED!')