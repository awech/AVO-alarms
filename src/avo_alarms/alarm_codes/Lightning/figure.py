import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

from avo_alarms.utils import plotting
from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def plot_fig(df, config, T0, test=False):

    fig, ax = plt.subplots(figsize=(3.4, 3.15))

    lat0 = df.iloc[0].api_vlat
    lon0 = df.iloc[0].api_vlon
    v_name = df.iloc[0].v_name
    t_recent = df.iloc[0].time.strftime('%Y-%m-%d %H:%M:%S')

    X_DIST = getattr(config, "dist2", 100)
    Y_DIST = getattr(config, "dist2", 100)

    ax, extent = plotting.make_map(ax, lat0, lon0, basemap="HIGHRES", xdist=X_DIST, ydist=Y_DIST)
    ax.set_title(f"--- {v_name} Lightning ---\n{t_recent} UTC", fontsize=8)
    plotting.map_ticks(ax, extent, grid_kwargs="default")
    plotting.add_volcanoes_to_map(ax, extent, config, c1="k", c2="grey", linewidths=0.1)
    ax.plot(lon0, lat0, "^", mfc="k", mec="w", ms=6, transform=ccrs.Geodetic())
    plotting.add_scale_bar(ax, 15, txt_yoffset=0.01, extent=extent)

    map_hdl = ax.scatter(df.longitude.values,
                            df.latitude.values,
                            s=14,
                            c=date2num(df.time),
                            cmap="plasma",
                            vmin=date2num((T0-config.duration).datetime),
                            vmax=date2num(T0.datetime),
                            ec="k",
                            lw=0.2,
                            transform=ccrs.Geodetic(),
                            zorder=1e5)

    cbaxes = inset_axes(ax, height="70%", width="4%", loc=6, borderpad=-1)
    cbar = plt.colorbar(map_hdl, cax=cbaxes, orientation="vertical")
    cbaxes.yaxis.set_ticks_position("left")
    cbar.set_ticks([date2num((T0-config.duration).datetime), date2num(T0.datetime)])
    cbar.set_ticklabels([f"{config.duration / 60:.0f}\nmin\nago", "Now"])
    cbar.ax.tick_params(labelsize=6)

    ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
    ax_inset, inset_extent = plotting.make_map(ax_inset, lat0, lon0,
                                    xdist=400,
                                    ydist=300,
                                    basemap="land",
                                    projection="orthographic")
    plotting.add_volcanoes_to_map(ax_inset, inset_extent, config, s1=7, s2=4, linewidths=0.1)
    plotting.add_inset_polygon(ax_inset, extent)

    jpg_file = plotting.save_file(fig, config, test=test, dpi=300)

    return jpg_file
