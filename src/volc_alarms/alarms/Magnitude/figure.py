import cartopy.crs as ccrs
import matplotlib.pyplot as plt

from volc_alarms.utils import processing, downloading, plotting
from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def plot_event(eq, volcs, config, n_stations=8, test=False):

    ################### Download data ###################
    channels = processing.eq_picks_to_dataframe(eq)
    plot_chans = channels[:n_stations]
    origin = eq.preferred_origin()
    st = downloading.download_waveforms(
        list(plot_chans.NSLC.values), origin.time - 20, origin.time + 50
    )

    logger.info("Plotting traces...")
    axes_list, h_ratios = plotting.get_axes_and_ratios(st)
    fig, ax = plt.subplot_mosaic(
        axes_list,
        figsize=(4, 9),
        height_ratios=h_ratios,
    )

    plotting.plot_station_traces(ax, st, plot_chans)

    vlat = volcs.iloc[0]["Latitude"]
    vlon = volcs.iloc[0]["Longitude"]
    ax["map"], extent = plotting.make_map(
        ax["map"],
        vlat,
        vlon,
        basemap="hillshade",
        xdist=getattr(config, "map_distance", 50),
        ydist=getattr(config, "map_distance", 50)
    )

    plotting.map_ticks(ax["map"], extent, grid_kwargs="default", y_rotate=90)
    ax["map"].tick_params(length=0)

    plotting.add_volcanoes_to_map(ax["map"], extent, config)
    ax["map"].plot(channels.Longitude, channels.Latitude, 's', c='orange', ms=4, mec='k', mew=0.4, transform=ccrs.PlateCarree())
    ax["map"].plot(origin.longitude, origin.latitude, 'o', c='firebrick', ms=6, mec='k', mew=0.7, transform=ccrs.PlateCarree())
    for i, row in channels.iterrows():
        t = ax["map"].annotate(row.NS.split('.')[-1], (row.Longitude, row.Latitude), xytext=(10,10), textcoords="offset pixels", fontsize=6, transform=ccrs.Geodetic())
        t.clipbox = ax["map"].bbox

    plotting.add_scale_bar(ax["map"], 10, txt_yoffset=0.01, extent=extent)

    eq_t = origin.time.strftime("%Y-%m-%d %H:%M:%S")
    eq_mag = eq.preferred_magnitude().mag
    eq_dist = volcs.iloc[0].distance
    volc = volcs.iloc[0].Name
    eq_depth = origin.depth / 1000
    title_str = (
        f"{eq_t}\n"
        f"M{eq_mag:.1f}, {eq_dist:.1f} km from {volc}\n"
        f"Depth: {eq_depth:.1f} km"
        )
    ax["map"].set_title(title_str, fontsize=8)

    ax_inset = fig.add_axes([0.66, 0.80, 0.12, 0.12])
    ax_inset, _ = plotting.make_map(
        ax_inset,
        vlat,
        vlon,
        xdist=getattr(config, "inset_map_distance", 150),
        ydist=getattr(config, "inset_map_distance", 150),
        basemap="land",
        projection="orthographic",
    )

    plotting.add_inset_polygon(ax_inset, extent)

    logger.info('Saving figure...')
    jpg_file = plotting.save_file(fig, config, test=test)

    return jpg_file
