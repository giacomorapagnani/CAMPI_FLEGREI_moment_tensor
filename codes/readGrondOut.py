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
reportdir=os.path.join(workdir,'report')
reportdir=os.path.join('/Users/giaco/UNI/PhD_CODE/GIT/CAMPI_FLEGREI_moment_tensor/report/report')
catdir=os.path.join(workdir,'CAT')

catname=os.path.join(catdir,'catalogue_flegrei_mag_2_5.pf')               # CHANGE
new_cataloguename=os.path.join(catdir,'catalogue_flegrei_MT_final.pf')    # CHANGE

refevents=model.load_events(catname)

run_get_grond_results = True

if run_get_grond_results:
    mttargets = [ev for ev in refevents]
    badmtsols = ['']
    print('All events in catalogue:', len(mttargets))
    goodmttargets = [ev for ev in mttargets if ev.name not in badmtsols]
    print('Good events in catalogue:', len(goodmttargets))
    for vrs in ['cmt_devi_XL_final_', 'cmt_devi_L_final_', 'cmt_devi_M_final_']:                    # CHANGE
        grondevs = []
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
                    nlat, nlon = od.ne_to_latlon(lat, lon,
                                                 np.array([north]),
                                                 np.array([east]))
                    ev.lat, ev.lon = nlat[0], nlon[0]
                    if ev.magnitude >= 1.0:
                        grondevs.append(ev)
                else:
                    print('WARNING: no .yaml file found for event:',ev.name)
    print('Total MT solutions found:',len(grondevs))
    model.dump_events(grondevs, new_cataloguename)
