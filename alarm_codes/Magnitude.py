import os
import sys
import pandas as pd
import numpy as np
from obspy import Catalog, UTCDateTime, Stream
from obspy.geodetics.base import gps2dist_azimuth
from obspy.clients.fdsn import Client
import cartopy
from cartopy.io.img_tiles import GoogleTiles
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
from matplotlib.ticker import FormatStrFormatter
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
import matplotlib as m
import shapely.geometry as sgeom
import warnings
import traceback
import time
from pathlib import Path

current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
from utils import messaging, plotting, processing


warnings.filterwarnings("ignore")

attempt = 1
while attempt <= 3:
    try:
        client = Client("IRIS")
        break
    except:
        time.sleep(2)
        attempt += 1
        client = None

def run_alarm(config, T0, test=False):

    # Download the event data
    T0_str = T0.strftime('%Y-%m-%d %H:%M')
    print(f"{T0_str}\nDownloading events...")
    T2 = T0
    T1 = T2 - config.DURATION
    
    URL = "{}starttime={}&endtime={}&minmagnitude={}&maxdepth={}&includearrivals=true&format=xml".format(
        os.environ["GUGUAN_URL"],
        T1.strftime("%Y-%m-%dT%H:%M:%S"),
        T2.strftime("%Y-%m-%dT%H:%M:%S"),
        config.MAGMIN,
        config.MAXDEP,
    )
    CAT = processing.download_hypocenters(URL)

    # Error pulling events
    if CAT is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) FDSN connection error"
        messaging.icinga(config, state, state_message)
        return

    # No events
    if len(CAT) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message)
        return

    # Compare new event distance with volcanoes
    VOLCS = pd.read_excel(config.volc_file)
    CAT_DF = processing.catalog_to_dataframe(CAT, VOLCS)
    CAT_DF = CAT_DF[CAT_DF["V_DIST"] < config.DISTANCE]

    # New events, but not close enough to volcanoes
    if len(CAT_DF) == 0:
        print("Earthquakes detected, but not near any volcanoes")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message)
        return

    # Read in old events. Write all recent events. Filter to new events
    OLD_EVENTS = pd.read_csv(config.outfile) 
    CAT_DF[["ID"]].to_csv(config.outfile, index=False)
    NEW_EVENTS=CAT_DF[~CAT_DF["ID"].isin(OLD_EVENTS.ID)]
    NEW_EVENTS = NEW_EVENTS.sort_values("Time")

    # No new events to process
    if len(NEW_EVENTS) == 0:
        print("Earthquakes detected, but already processed in previous run")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Old event detected"
        messaging.icinga(config, state, state_message)
        return

    print(f"{len(NEW_EVENTS)} new events found. Looping through events...")
    # Filter Obspy catalog to new events near volcanoes
    CAT_NEW = Catalog()
    for i, row in NEW_EVENTS.iterrows():
        t0_str = row.Time.strftime("%Y-%m-%dT%H:%M:%S.%f")
        filter1 = f"time >= {t0_str}"
        filter2 = f"time <= {t0_str}"
        CAT_NEW.append(CAT.filter(filter1, filter2)[0])

    # Add phase info to new events
    try:
        CAT_NEW = processing.addPhaseHint(CAT_NEW)
    except:
        print("Could not add phase type...")

    for eq in CAT_NEW:
        print(f"Processing {eq.short_str()}, {eq.resource_id.id}")
        volcs = processing.volcano_distance(
            eq.preferred_origin().longitude, eq.preferred_origin().latitude, VOLCS
        )
        volcs = volcs.sort_values("distance")

        #### Generate Figure ####
        try:
            attachment = plot_event(eq, volcs, config)
            fig_dir = Path(os.environ["TMP_FIGURE_DIR"])
            eq_time = eq.preferred_origin().time.strftime("%Y%m%dT%H%M%S")
            eq_mag = eq.preferred_magnitude().mag
            eq_id = "".join(eq.resource_id.id.split("/")[-2:]).lower()
            new_filename = fig_dir / f"{eq_time}_M{eq_mag:.1f}_{eq_id}.png"
            os.rename(attachment, new_filename)
            attachment = new_filename
        except:
            attachment = []
            print("Problem making figure. Continue anyway")
            b = traceback.format_exc()
            err_message = "".join(f"{a}\n" for a in b.splitlines())
            print(err_message)

        # craft and send the message
        subject, message = create_message(eq, volcs)

        print("Sending message...")
        # messaging.send_alert(config.alarm_name, subject, message, attachment)
        print("Posting to mattermost...")
        messaging.post_mattermost(config, subject, message, filename=attachment)

        # Post to dedicated response channels for volcnoes listed in config file
        if "mm_response_channels" in dir(config):
            if volcs.iloc[0].Volcano in config.mm_response_channels.keys():
                config.mattermost_channel_id = config.mm_response_channels[volcs.iloc[0].Volcano]
                messaging.post_mattermost(config, subject, message, filename=attachment)

        # delete the file you just sent
        if attachment:
            os.remove(attachment)

        state = "CRITICAL"
        eq_str = eq.preferred_origin().time.strftime("%Y-%m-%d %H:%M:%S")
        state_message = f"{eq_str} (UTC) {subject}"

    messaging.icinga(config, state, state_message)

    return


def create_message(eq, volcs):
    origin = eq.preferred_origin()
    t = pd.Timestamp(origin.time.datetime, tz="UTC")
    t_local = t.tz_convert(os.environ["TIMEZONE"])
    Local_time_text = f"{t_local.strftime("%Y-%m-%d %H:%M:%S")} {t_local.tzname()}"

    message = f"{t.strftime('%Y-%m-%d %H:%M:%S')} UTC\n{Local_time_text}"
    message = f"{message}\n\n**Magnitude:** {eq.preferred_magnitude().mag:.1f}"
    message = f"{message}\n**Latitude:** {origin.latitude:.3f}\n**Longitude:** {origin.longitude:.3f}"
    message = f"{message}\n**Depth:** {origin.depth / 1000:.1f} km"
    message = f"{message}\n**Event ID:** {''.join(eq.resource_id.id.split('/')[-2:]).lower()}"

    volcs = volcs.sort_values("distance")
    v_text = ""
    for _, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Volcano} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}\n**Nearest volcanoes:** {v_text[:-2]}"

    try:
        message = f"{message}\n\n***--- {origin.evaluation_mode.replace('manual', 'reviewed').upper()} Location ---***"
        message = f"{message}\nUsing {origin.quality.used_phase_count:g} phases from {origin.quality.used_station_count:g} stations"
        message = f"{message}\n**Azimuthal Gap:** {origin.quality.azimuthal_gap:g} degrees"
        message = f"{message}\n**Standard Error:** {origin.quality.standard_error:g} s"
        message = f"{message}\n**Vertical/Horizontal Error:** {origin.depth_errors['uncertainty'] / 1000:.1f} km / {origin.origin_uncertainty.horizontal_uncertainty / 1000:.1f} km"
    except:
        pass

    subject = f"M{eq.preferred_magnitude().mag:.1f} earthquake at {volcs.iloc[0].Volcano}"

    return subject, message


def get_channels(eq):

    NS = []
    NSLC = []
    SCNL = []
    LATS = []
    LONS = []
    DIST = []
    P = []
    S = []
    for p in eq.picks:
        wid = p.waveform_id
        net, sta, loc, chan = wid.id.split(".")
        ns = ".".join([net, sta])
        if ns not in NS:
            print(f"Getting lat/lon info for {wid.id}")
            inventory = client.get_stations(
                network=net, station=sta, location=loc, channel=chan
            )
            # NSLC.append(wid.id.replace('..','.--.'))
            NS.append(ns)
            NSLC.append(wid.id)
            SCNL.append(".".join([sta, chan, net, loc]))
            LATS.append(inventory[0][0].latitude)
            LONS.append(inventory[0][0].longitude)
    for i, nslc in enumerate(NSLC):
        dist = (
            gps2dist_azimuth(
                eq.preferred_origin().latitude,
                eq.preferred_origin().longitude,
                LATS[i],
                LONS[i],
            )[0]
            / 1000.0
        )
        DIST.append(dist)

    STAS = pd.DataFrame(
        {
            "NS": NS,
            "NSLC": NSLC,
            "SCNL": SCNL,
            "Latitude": LATS,
            "Longitude": LONS,
            "Distance": DIST,
        }
    )

    STAS["P"] = np.nan
    STAS["S"] = np.nan
    for p in eq.picks:
        ns = ".".join(p.waveform_id.id.split(".")[:2])
        STAS.loc[STAS.NS == ns, p.phase_hint] = p.time

    STAS = STAS.sort_values("Distance")

    return STAS


def get_axes_and_ratios(st):
    axes_list = np.array([tr.stats.station for tr in st])
    h_ratios = np.full(axes_list.shape, 1 / len(axes_list))
    axes_list = np.insert(axes_list, 0, "map")
    h_ratios = np.insert(h_ratios, 0, h_ratios.sum() * 0.5)
    axes_list = axes_list.reshape(axes_list.shape[0], 1)

    return axes_list, h_ratios


def get_xticks(st, fmt="15s"):
    trace_t1 = pd.to_datetime(st[0].stats.starttime.datetime)
    trace_t2 = pd.to_datetime(st[0].stats.endtime.datetime)
    tick_df = pd.DataFrame({"datetime": pd.date_range(trace_t1, trace_t2, freq="15s")})
    x_tick_labels = tick_df["datetime"].dt.ceil(fmt)
    x_ticks = [(xt - trace_t1).total_seconds() for xt in x_tick_labels]
    x_tick_labels = [xt.strftime("%H:%M:%S") for xt in x_tick_labels]
    if x_ticks[-1] > st[0].times()[-1]:
        x_ticks = x_ticks[:-1]
        x_tick_labels = x_tick_labels[:-1]
    return x_ticks, x_tick_labels


def plot_event(eq, volcs, config):
    m.use('Agg')
    n_blank = 4

    ################### Download data ###################
    channels = get_channels(eq)
    plot_chans = channels[:8]
    st = processing.grab_data(list(plot_chans.SCNL.values), 
                        eq.preferred_origin().time-20, 
                        eq.preferred_origin().time+50)
    try:
        client._attach_responses(st)
        st.remove_response()
        velocity = True
    except:
        velocity = False

    print("Plotting traces...")
    st.trim(st[0].stats.starttime + 5, st[0].stats.endtime - 5)
    st.detrend()

    axes_list, h_ratios = get_axes_and_ratios(st)

    fig, ax = plt.subplot_mosaic(
        axes_list,
        figsize=(4, 9),
        height_ratios=h_ratios,
        layout="constrained",
    )

    x_ticks, x_tick_labels = get_xticks(st)
        
    for i, tr in enumerate(st):
        sta = tr.stats.station
        ax[sta].plot(tr.times("relative"), tr.data, lw=0.5, c="0.2")
        ax[sta].text(
            0.01,
            0.7,
            tr.id,
            fontsize=6,
            transform=ax[sta].transAxes,
            bbox=dict(boxstyle="round", fc="w", ec="w", alpha=0.8, linewidth=0),
        )
        try:
            p_time = (plot_chans.iloc[i].P.datetime - trace_t1).total_seconds()
            ax[sta].axvline(p_time, ymin=0.25, ymax=0.75, color="r", linewidth=1)
        except:
            pass
        try:
            s_time = (plot_chans.iloc[i].S.datetime - trace_t1).total_seconds()
            ax[sta].axvline(s_time, ymin=0.25, ymax=0.75, color="dodgerblue", linewidth=1)
        except:
            pass
        if i == 4:
            tr.data = tr.data * 1e3
        if velocity:
            label_color = "black"
            fw = "normal"
            peak_num = np.abs(tr.data).max()
            if np.log10(peak_num) < -6:
                tmp_str = f"{peak_num*1e9:.1f}\n$nm/s$"
            elif np.log10(peak_num) < -3:
                tmp_str = f"{peak_num*1e6:.1f}\n$\mu$$m/s$"
            elif np.log10(peak_num) < 0:
                tmp_str = f"{peak_num*1e3:.2f}\n$mm/s$"
                label_color = "firebrick"
                fw = "bold"
            ax[sta].text(
                ax[sta].get_xlim()[0] - 1 / 86400,
                tr.data[0],
                tmp_str,
                fontsize=6,
                horizontalalignment="center",
                verticalalignment="bottom",
                rotation_mode="anchor",
                rotation=90,
                color=label_color,
                fontweight=fw,
            )
        ax[sta].set_yticks([])
        ax[sta].set_xticks(x_ticks)
        ax[sta].set_xticklabels([])
        ax[sta].grid(axis="x", linewidth=0.2, linestyle="--")
        ax[sta].tick_params("x", length=0)
        for spine in ["top", "bottom", "left", "right"]:
            ax[sta].spines[spine].set_visible(False)
    ax[sta].set_xticklabels(x_tick_labels, fontsize=6)

    # #################### Add main map ####################
    # grid = plt.GridSpec(len(ST), 1, wspace=0.05, hspace=0.6)
    # print('Plotting main map...')
    # extent = get_extent(volcs.iloc[0].Latitude, volcs.iloc[0].Longitude, dist=25)
    # # CRS = cartopy.crs.Mercator(central_longitude=np.mean(extent[:2]), min_latitude=extent[2], max_latitude=extent[3], globe=None)
    # # ax1 = plt.subplot(grid[:n_blank,0], projection=CRS)
    # # ax1.set_extent(extent,cartopy.crs.PlateCarree())
    # # coast = cartopy.feature.GSHHSFeature(scale="high", rasterized=True)
    # # ax1.add_feature(coast, facecolor="lightgray", linewidth=0.5)
    # # water_col=tuple(np.array([165,213,229])/255.)
    # # ax1.set_facecolor(water_col)
    # # ax1.background_patch.set_facecolor(water_col)
    # ax1 = plt.subplot(grid[:n_blank,0], projection=ShadedReliefESRI().crs)
    # ax1.set_extent(extent)
    # ax1.add_image(ShadedReliefESRI(), 11)
    # lon_grid = [np.mean(extent[:2])-np.diff(extent[:2])[0]/4, np.mean(extent[:2])+np.diff(extent[:2])[0]/4]
    # lat_grid = [np.mean(extent[-2:])-np.diff(extent[-2:])[0]/4, np.mean(extent[-2:])+np.diff(extent[-2:])[0]/4]
    # # gl = ax1.gridlines(draw_labels={"bottom": "x", "right": "y"},
    # # 				   xlocs=lon_grid, ylocs=lat_grid,
    # # 				   xformatter=LongitudeFormatter(number_format='.2f', direction_label=False),
    # # 				   yformatter=LatitudeFormatter(number_format='.2f', direction_label=False),
    # # 				   alpha=0.2,
    # # 				   color='gray',
    # # 				   linewidth=0.5,
    # # 				   xlabel_style={'fontsize':6},
    # # 				   ylabel_style={'fontsize':6})
    # gl = ax1.gridlines(draw_labels=True, xlocs=lon_grid, ylocs=lat_grid,
    #                    alpha=0.0,
    #                    color='gray',
    #                    linewidth=0.5)
    # gl.xlabels_top = False
    # gl.ylabels_left = False
    # gl.xformatter = LONGITUDE_FORMATTER
    # gl.yformatter = LATITUDE_FORMATTER
    # gl.xlabel_style = {'size': 6}
    # gl.ylabel_style = {'size': 6}

    # ax1.plot(volcs[:10].Longitude, volcs[:10].Latitude, '^', markerfacecolor='g', markersize=8, markeredgecolor='k', markeredgewidth=0.5, transform=cartopy.crs.PlateCarree())
    # ax1.plot(channels.Longitude, channels.Latitude, 's', markerfacecolor='orange', markersize=5, markeredgecolor='k', markeredgewidth=0.4, transform=cartopy.crs.PlateCarree())
    # ax1.plot(eq.preferred_origin().longitude, eq.preferred_origin().latitude, 'o', markerfacecolor='firebrick', markersize=8, markeredgecolor='k', markeredgewidth=0.7, transform=cartopy.crs.PlateCarree())
    # for i, row in channels.iterrows():
    #     t = ax1.text(row.Longitude+0.006, row.Latitude+0.006, row.NS.split('.')[-1], clip_on=True, fontsize=6, transform=cartopy.crs.PlateCarree())
    #     t.clipbox = ax1.bbox

    # ax1.set_title('{}\nM{:.1f}, {:.1f} km from {}\nDepth: {:.1f} km'.format(eq.preferred_origin().time.strftime('%Y-%m-%d %H:%M:%S'),
    #                                                            eq.preferred_magnitude().mag,
    #                                                            volcs.iloc[0].distance,
    #                                                            volcs.iloc[0].Volcano,
    #                                                            eq.preferred_origin().depth/1000,
    #                                                            ),
    #               fontsize=8)

    # fig.subplots_adjust(top=0.94)
    # fig.subplots_adjust(bottom=0.03)

    # ################### Add inset map ###################
    # print('Plotting inset map...')
    # extent2 = get_extent(volcs.iloc[0].Latitude, volcs.iloc[0].Longitude, dist=150)
    # CRS2 = cartopy.crs.AlbersEqualArea(central_longitude=np.mean(extent2[:2]), central_latitude=np.mean(extent[2:]), globe=None)
    # glb_ax = fig.add_axes([0.75, 0.84, 0.17, 0.17], projection=CRS2)
    # glb_ax.set_boundary(make_path(extent2), transform=cartopy.crs.Geodetic())
    # glb_ax.set_extent(extent2,cartopy.crs.Geodetic())
    # coast = cartopy.feature.GSHHSFeature(scale="intermediate", rasterized=True)
    # glb_ax.add_feature(coast, facecolor="lightgray", linewidth=0.1)
    # extent_lons=np.concatenate( (np.linspace(extent[0],extent[1],100),
    #                              extent[1]*np.ones(100),
    #                              np.linspace(extent[1],extent[0],100),
    #                              extent[0]*np.ones(100)
    #                             )
    #                           )
    # extent_lats=np.concatenate( (extent[2]*np.ones(100),
    #                              np.linspace(extent[2],extent[3],100),
    #                              extent[3]*np.ones(100),
    #                              np.linspace(extent[3],extent[2],100),
    #                             )
    #                           )
    # pointList = [sgeom.Point(x,y) for x,y in zip(extent_lons,extent_lats)]
    # poly = sgeom.Polygon([[p.x, p.y] for p in pointList])
    # glb_ax.add_geometries([poly], cartopy.crs.Geodetic(), facecolor='none', edgecolor='crimson', linewidth=.75,zorder=1e3)
    # #####################################################

    print('Saving figure...')
    jpg_file = plotting.save_file(fig, config, dpi=250)
    plt.close(fig)

    return jpg_file
