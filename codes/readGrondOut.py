#!/usr/bin/env python3

from pyrocko import util, model, io, trace, moment_tensor, gmtpy
from pyrocko import orthodrome as od
from pyrocko.client import catalog
from pyrocko.automap import Map
import pyrocko.moment_tensor as pmt
from pyrocko.plot import mpl_color
from pyrocko.guts import load
# from seiscloud import plot as scp
# from seiscloud import cluster as scc
import numpy as np
import os
import sys
# import re
import math
# import shutil
import matplotlib.pyplot as plt
# from matplotlib import collections as mc
from matplotlib import dates
import datetime
# import urllib.request
from pyrocko.plot.gmtpy import GMT
from pyrocko.plot import beachball
import pickle
import shutil
import urllib.request

workdir='../'
reportdir=os.path.join(workdir,'report')                                #main report dir
#reportdir=os.path.join(workdir,'../FULL_DC_runs_and_report/report')        #cd and full report dir
catdir=os.path.join(workdir,'CAT')

catname=os.path.join(catdir,'catalogue_flegrei_mag_2_5.pf')    # CHANGE  catalogue_flegrei_VLP_gilberto catalogue_flegrei_mag_2_5

new_catalogue_name='catalogue_flegrei_MT_final'                           # CHANGE

refevents=model.load_events(catname)

run_get_grond_results = True

# TRUE if you want to use new localization of grond
#######################################
############# SWITCH #############
#######################################
switch_new_localization=False

if run_get_grond_results:
    mttargets = [ev for ev in refevents]
    badmtsols = ['']
    print('All events in catalogue:', len(mttargets))
    goodmttargets = [ev for ev in mttargets if ev.name not in badmtsols]
    print('Good events in catalogue:', len(goodmttargets))
    grondevs = []
    for vrs in ['cmt_devi_XL_final_', 'cmt_devi_L_final_', 'cmt_devi_M_final_','cmt_devi_S_final_','cmt_devi_S_']:                    # main report
    #for vrs in ['cmt_dc_XL_final_', 'cmt_dc_L_final_', 'cmt_dc_M_final_','cmt_dc_S_final_']:                    # dc reports
    #for vrs in ['cmt_full_XL_final_', 'cmt_full_L_final_', 'cmt_full_M_final_','cmt_full_S_final_']:                    # full reports
    #for vrs in ['cmt_LP_oscill_']:
        for ev in goodmttargets:
            targetdir = os.path.join(reportdir, ev.name, vrs + ev.name)
            #if not os.path.isdir(targetdir):
                #print(ev.name, 'missing report dir', targetdir)
            if os.path.isdir(targetdir):
                fname = os.path.join(targetdir, 'event.solution.best.yaml')     # takes BEST results
                if os.path.isfile(fname):
                    fmean = open(fname, 'r')
                    for line in fmean:
                        spl = line.split(':')
                        if len(spl)==2:
                            if spl[0]=='lat':
                                lat = float(spl[1])
                            if spl[0]=='lon':
                                lon = float(spl[1])
                            if spl[0]=='north_shift':
                                north = float(spl[1])
                            if spl[0]=='east_shift':
                                east = float(spl[1])
                            if spl[0]=='time':
                                ev.time = util.str_to_time(spl[1][1:])
                                # print('check time', spl[1][1:])
                            if spl[0]=='depth':
                                ev.depth = float(spl[1])
                            if spl[0]=='magnitude':
                                ev.magnitude = float(spl[1])
                            if spl[0] == '  mnn':
                                mnn = float(spl[1])
                            if spl[0] == '  mee':
                                mee = float(spl[1])
                            if spl[0] == '  mdd':
                                mdd = float(spl[1])
                            if spl[0] == '  mne':
                                mne = float(spl[1])
                            if spl[0] == '  mnd':
                                mnd = float(spl[1])
                            if spl[0] == '  med':
                                med = float(spl[1])
                            if spl[0] == '  moment':
                                m0 = float(spl[1])
                    mt = pmt.MomentTensor(mnn=mnn, mee=mee, mdd=mdd,
                                          mne=mne, mnd=mnd, med=med,
                                          moment=m0)
                    ev.moment_tensor = mt
                    fmean.close()
                    if switch_new_localization:
                        nlat, nlon = od.ne_to_latlon(lat, lon,
                                        np.array([north]),
                                        np.array([east]))
                        ev.lat, ev.lon = nlat[0], nlon[0]
                    else:
                        ev.lat, ev.lon = lat , lon
                    if ev.magnitude >= 1.0:
                        grondevs.append(ev)
                else:
                    print('WARNING: no .yaml file found for event:',ev.name)

        grondevs.sort(key=lambda x: x.time, reverse=False)
        print('events in ',vrs,':', len(grondevs),'+')
    print('Total MT solutions found:',len(grondevs))

    if switch_new_localization:
        new_catalogue_path=os.path.join(catdir,new_catalogue_name+'_reloc.pf')   
        model.dump_events(grondevs, new_catalogue_path)
    else:
        new_catalogue_path=os.path.join(catdir,new_catalogue_name+'.pf')   
        model.dump_events(grondevs, new_catalogue_path)

