#!/usr/bin/env python3

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


km = 1000.

tmin = util.str_to_time('2010-01-01 00:00:00')
tmax = util.str_to_time('2020-01-01 00:00:00')  # ending time of query
depmin = 0. * km                               # minimum magntiude (open end)
depmax = 5. * km
latmin = 40.8
latmax = 40.9
lonmin = 14.1
lonmax = 14.2
magmin = 0.0
magmax = 3.0

workingdir = '.'
catdir = os.path.join(workingdir, 'catalogs')
infodir = os.path.join(workingdir, 'info')
datadir = os.path.join(workingdir, 'data')
resdir = os.path.join(workingdir, 'results')
figdir = os.path.join(workingdir, 'figures')

orig_catname = os.path.join(infodir, 'eventi_loc-md.txt')
catname = os.path.join(catdir, 'campi_flegrei.pf')
stations_fn = os.path.join(infodir, 'stations.pf')

if not os.path.isdir(catdir):
    os.mkdir(catdir)
if not os.path.isdir(datadir):
    os.mkdir(datadir)
if not os.path.isdir(figdir):
    os.mkdir(figdir)


# switches
run_get_catalogue = True
# read original catalog and reformat it
run_view_catalogue = False
# plot map and time history of seismicity
run_sac_to_mseed = False
# convert seismic data from sac to miniSEED and remove response
get_open_data_and_metadata = False
# get additional open data using FDSN web services
run_prepare_flat_stationxml = False
# convert seismic data from sac to miniSEED


def getNetLocCha(stat):
    respdir = os.path.join('.', 'original_resp', 'RESP')
    fnames = os.listdir(respdir)
    respnames = [fname for fname in fnames if stat in fname]
    fnames = os.listdir(respdir)
    respnames = [fname for fname in fnames if stat in fname]
    pzdir = os.path.join('.', 'original_resp', 'PZ')
    fnames = os.listdir(pzdir)
    pznames = [fname for fname in fnames if stat in fname]
    if len(respnames)>0:
        if len(respnames)>3:
            print('WARNING', stat)
        myfname = respnames[0]
        spl = myfname.split('.')
        network = spl[1]
        location = spl[3]
        channel = spl[4][0:2]
        success = True
        r = os.path.join(respdir, respnames[0])
        rtype = 'RESP'
    elif len(pznames)>0:
        if len(pznames)>1:
            print('WARNING', stat)
        network, location, channel = '', '', ''
        success = True
        r = os.path.join(pzdir, pznames[0])
        rtype = 'PZ'
    else:
        network, location, channel = '', '', ''
        success = False
        r = 'none'
        rtype = 'none'
    return network, location, channel, r, rtype, success


# STEP 1.1
# Seismic catalog:
# reformat local catalog
if run_get_catalogue:
    events = []
    f = open(orig_catname, 'r')
    for line in f:
        spl = line.split()
        if len(spl)==5:
            name = spl[0]
            timestr = name[0:4] + '-' + name[4:6] + '-' + name[6:8] + ' ' +\
                      name[8:10] + ':' + name[10:12] + ':' + name[12:14]
            time = util.str_to_time(timestr)
            lat, lon = float(spl[1]), float(spl[2])
            depth = float(spl[3])*km
            magnitude = float(spl[4])
            events.append(model.Event(name=name, time=time,
                                      lat=lat, lon=lon,
                                      depth=depth, magnitude=magnitude))
    f.close()
    events.sort(key=lambda x: x.time, reverse=False)
    model.dump_events(events, catname)
events = model.load_events(catname)
print('Number of events:', len(events))


# STEP 1.2
# Seismic catalog:
# view catalog
if run_view_catalogue:
    lats = [ev.lat for ev in events]
    lons = [ev.lon for ev in events]
    times = [(ev.time-tmin)/(24.*60.*60.) for ev in events]
    mags = [ev.magnitude for ev in events]
    depths = [ev.depth for ev in events]
    dts = dates.date2num([datetime.datetime.fromtimestamp(ev.time)
                          for ev in events])

    dates_format = dates.DateFormatter('%Y-%m-%d')
    dates_loc = dates.YearLocator()
    dmin = dates.date2num(datetime.datetime.fromtimestamp(tmin))
    dmax = dates.date2num(datetime.datetime.fromtimestamp(tmax))

    cum_m0, cum_n = 0., 0.
    times = [tmin]
    eq_cum_m0s = [cum_m0]
    eq_cum_ns = [cum_n]
    for ev in events:
        times.append(ev.time)
        times.append(ev.time)
        eq_cum_m0s.append(cum_m0)
        cum_m0 = cum_m0 + pmt.magnitude_to_moment(ev.magnitude)
        eq_cum_m0s.append(cum_m0)
        eq_cum_ns.append(cum_n)
        cum_n = cum_n + 1
        eq_cum_ns.append(cum_n)
    times.append(tmax)
    eq_cum_m0s.append(cum_m0)
    eq_cum_ns.append(cum_n)
    eq_dates = [datetime.datetime.fromtimestamp(t) for t in times]
    eq_mpl_dates = dates.date2num(eq_dates)

    f = plt.figure(figsize=(10, 7), facecolor='w', edgecolor='k')
    maxmag = max([ev.magnitude for ev in events])

    ax = f.add_subplot(311)
    ax.xaxis.set_major_locator(dates_loc)
    ax.scatter(num.array([datetime.datetime.fromtimestamp(ev.time)
                          for ev in events]),
               num.array([ev.magnitude for ev in events]),
               c='blue', s=10)
    ax.xaxis.set_major_formatter(dates_format)
    ymax = max([ev.magnitude for ev in events])
    plt.xlim(left=dmin, right=dmax)
    plt.ylim(bottom=0., top=1.1*ymax)
    plt.ylabel('Md', fontsize=14)
    plt.tick_params(labelsize=12)
    ax.xaxis.set_visible(False)

    ax = f.add_subplot(312)
    ax.xaxis.set_major_locator(dates_loc)
    ax.plot(eq_mpl_dates, num.array(eq_cum_m0s), c='blue')
    ax.xaxis.set_major_formatter(dates_format)
    ymax = max([eq_cum_m0s[-1:]])[0]
    plt.xlim(left=dmin, right=dmax)
    plt.ylim(bottom=0., top=1.1*ymax)
    plt.ylabel('Cumul. M0 [Nm]', fontsize=14)
    plt.tick_params(labelsize=12)
    ax.xaxis.set_visible(False)

    ax = f.add_subplot(313)
    ax.xaxis.set_major_locator(dates_loc)
    ax.plot(eq_mpl_dates, num.array(eq_cum_ns), c='blue')
    ax.xaxis.set_major_formatter(dates_format)
    ymax = max([eq_cum_ns[-1:]])[0]
    plt.xlim(left=dmin, right=dmax)
    plt.ylim(bottom=0., top=1.1*ymax)
    plt.xticks(rotation=30.)
    plt.tick_params(labelsize=12)
    plt.ylabel('Cumul. N', fontsize=14)
    plt.xlabel('Time', fontsize=14)

    plt.subplots_adjust(bottom=.3)

    figname = os.path.join(workingdir, 'figures', 'plot_tm.pdf')
    f.savefig(figname)
    # plt.show()

    latmean = num.mean([ev.lat for ev in events])
    lonmean = num.mean([ev.lon for ev in events])

    m = Map(
            lat=latmean,
            lon=lonmean,
            radius=10.*km,
            width=40., height=40.,
            show_grid=False,
            show_topo=False,
            color_dry=(238, 236, 230),
            topo_resolution_min=10,
            topo_cpt_wet='light_sea_uniform',
            topo_cpt_dry='light_land_uniform',
            illuminate=True,
            illuminate_factor_ocean=0.15,
            show_rivers=False,
            show_plates=False)
    m.draw_cities()

    stations = model.load_stations(stations_fn)
    lats = [s.lat for s in stations]
    lons = [s.lon for s in stations]
    labels = ['.'.join(s.nsl()) for s in stations]
    m.gmt.psxy(in_columns=(lons, lats), S='t10p', G='black', *m.jxyr)
    for i in range(len(stations)):
        m.add_label(lats[i], lons[i], labels[i])

    no_lons = [ev.lon for ev in events if ev.moment_tensor is None]
    no_lats = [ev.lat for ev in events if ev.moment_tensor is None]
    m.gmt.psxy(in_columns=(no_lons, no_lats), S='c10p',
               G='blue', *m.jxyr)
    print(len(no_lats))

    figname = os.path.join(figdir, 'plot_map_ref.pdf')
    if os.path.isfile(figname):
        os.remove(figname)
    m.save(figname)


if run_sac_to_mseed:
    srcdir = os.path.join(workingdir, 'original_data')
    dstdir = os.path.join(workingdir, 'original_mseed')
    disdir = os.path.join(workingdir, 'displacements')
    if os.path.isdir(dstdir):
        shutil.rmtree(dstdir)
    os.mkdir(dstdir)
    if os.path.isdir(disdir):
        shutil.rmtree(disdir)
    os.mkdir(disdir)

    odirs = os.listdir('original_data')
    bads = []
    for odir in odirs:
        newdir = os.path.join(dstdir, odir)
        os.mkdir(newdir)
        fnames = os.listdir(os.path.join(srcdir, odir))
        for fname in fnames:
            filename = os.path.join('original_data', odir, fname)
            if filename.lower().endswith('.sac'):
                mseed_out_filename = os.path.join(dstdir, odir, fname[:-4] + '.mseed')
                displ_out_filename = os.path.join(disdir, odir, fname[:-4] + '.mseed')
                traces = io.load(filename, format='sac')
                msd_traces, dis_traces = [], []
                for tr in traces:
                    net, loc, cha, r, rtype, success = getNetLocCha(tr.station)
                    tr.set_network(net)
                    tr.set_location(loc)
                    channel = cha + tr.channel
                    tr.set_channel(channel)
                    msd_traces.append(tr)
                    if success:
                        failed = False
                        print(tr.station, rtype)
                        if rtype=='RESP':
                            try:
                                resp = trace.InverseEvalresp(r, tr, target='dis')
                                tr.extend(tr.tmin - 20., tr.tmax + 20., fillmethod='repeat')
                                newtr = tr.transfer(
                                    10.,  # rise and fall of time domain taper in [s]
                                    (0.10, 0.20, 12., 20.),  # frequency domain taper in [Hz]
                                    transfer_function=resp)
                            except:
                                print('failed')
                                failed = 'True'
                        elif rtype=='PZ':
                            zeros, poles, constant = pz.read_sac_zpk(r)
                            # one more zero to convert from velocity->counts to displacement->counts
                            zeros.append(0.0j)

                            resp = trace.PoleZeroResponse(
                                zeros=zeros,
                                poles=poles,
                                constant=constant)
                            tr.extend(tr.tmin - 20., tr.tmax + 20., fillmethod='repeat')
                            newtr = tr.transfer(
                                10.,  # rise and fall of time domain taper in [s]
                                (0.10, 0.20, 12., 20.),  # frequency domain taper in [Hz]
                                transfer_function=resp,
                                invert=True)              # to change to (counts->displacement)
                            pass
                        else:
                            sys.exit('Unknown resp type', rtype)
                        if not failed:
                            dis_traces.append(newtr)
                    if not success:
                        if tr.station not in bads:
                            bads.append(tr.station)
                            # print('nok', tr.station)
                    # else:
                    #     print('ok', tr.station)
                io.save(dis_traces, displ_out_filename)
                io.save(msd_traces, mseed_out_filename)


if get_open_data_and_metadata:
    for ev in events:
        cmd = './rapidown --force --sites=iris,orfeus,geofon,ingv ' +\
              util.time_to_str(ev.time) + ' ' +\
              str(ev.lat) + ' ' +\
              str(ev.lon) + ' ' +\
              str(ev.depth/1000.) + ' 40 0.05 20. ' + ev.name
        os.system(cmd)


if run_prepare_flat_stationxml:
    allstations = model.load_stations(os.path.join(infodir, 'stations.pf'))
    stations = [st for st in allstations if st.network!='IV']
    station_xml = fdsn.FDSNStationXML.from_pyrocko_stations(stations)
    for network in station_xml.network_list:
        for station in network.station_list:
            for channel in station.channel_list:
                channel.response = fdsn.Response(
                    instrument_sensitivity=fdsn.Sensitivity(
                        value=1.0,
                        frequency=1.0,
                        input_units=fdsn.Units('M'),
                        output_units=fdsn.Units('COUNTS')))
    station_xml.validate()
    filename=os.path.join(infodir, 'stations_flat_displacement.xml')
    station_xml.dump_xml(filename=filename)
