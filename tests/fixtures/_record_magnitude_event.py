"""One-off recorder: capture a real Magnitude event's data to offline fixtures.

Run manually (NOT collected by pytest) to (re)generate the fixtures used by the
Magnitude CRITICAL integration scenario:

    python tests/fixtures/_record_magnitude_event.py

The event (M3.25 near Denison, 2026-01-04 20:16:41 UTC) is already captured as:
  - magnitude_Denison_20260104T2016.csv      (the FDSN hypocenters CSV row)
  - magnitude_Denison_20260104T2016.quakeml  (the per-event QuakeML with picks)

This recorder adds the two data-heavy pieces the figure path needs, pulling from
the live services named in the deployment .env:
  - magnitude_Denison_20260104T2016.mseed    waveforms for the nearest N stations
                                             (origin-20 .. origin+50), what
                                             plot_event actually plots
  - magnitude_Denison_20260104T2016_inv.xml  a level=response StationXML covering
                                             every pick station, so the offline
                                             scenario can resolve station coords
                                             (eq_picks_to_dataframe) and remove
                                             responses (plot_station_traces)
                                             without touching the network

The integration scenario then feeds the CSV/QuakeML/MiniSEED to the faked
downloaders and points a local-inventory client at the StationXML, so the test
runs fully offline.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from obspy import read_events
from obspy.clients.fdsn import Client as FDSN_Client

# Deployment .env (one dir above the volc-alarms repo) supplies WINSTON_* etc.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from volc_alarms.utils import downloading, processing  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
STEM = "magnitude_Denison_20260104T2016"
QUAKEML = DATA / f"{STEM}.quakeml"
MSEED_OUT = DATA / f"{STEM}.mseed"
INV_OUT = DATA / f"{STEM}_inv.xml"

# plot_event plots the nearest n_stations (default 8); grab a couple extra so the
# fixture is robust if that default changes.
N_STATIONS = 10
PAD_BEFORE = 20.0   # plot_event downloads origin.time - 20 ...
PAD_AFTER = 50.0    # ... to origin.time + 50


def main() -> None:
    cat = read_events(str(QUAKEML))
    eq = cat[0]
    origin = eq.preferred_origin() or eq.origins[0]

    print("Resolving pick-station distances (live)...")
    channels = processing.eq_picks_to_dataframe(eq)
    print(f"{len(channels)} pick stations; nearest {N_STATIONS}:")
    plot_chans = channels[:N_STATIONS]
    print(plot_chans[["NS", "NSLC", "Distance"]].to_string(index=False))

    # --- waveforms for the nearest stations ------------------------------
    t1 = origin.time - PAD_BEFORE
    t2 = origin.time + PAD_AFTER
    nslc_list = list(plot_chans.NSLC.values)
    print(f"\nDownloading {len(nslc_list)} channels {t1} - {t2} ...")
    st = downloading.download_waveforms(nslc_list, t1, t2)
    print(st.__str__(extended=True))
    MSEED_OUT.parent.mkdir(parents=True, exist_ok=True)
    st.write(str(MSEED_OUT), format="MSEED", encoding="STEIM2", reclen=512)
    print(f"Wrote {MSEED_OUT}  ({MSEED_OUT.stat().st_size / 1024:.1f} KiB)")

    # --- StationXML (level=response) for EVERY pick station --------------
    # eq_picks_to_dataframe resolves coords for all pick stations; the offline
    # scenario serves those (and responses for the plotted ones) from this file.
    client = FDSN_Client("earthscope")
    inv = None
    for _, row in channels.iterrows():
        net, sta = row.NS.split(".")
        try:
            sub = client.get_stations(
                network=net, station=sta, location="*", channel="*HZ",
                starttime=origin.time - 60, endtime=origin.time + 120,
                level="response",
            )
            inv = sub if inv is None else inv + sub
        except Exception as e:
            print(f"  WARN: no inventory for {net}.{sta}: {e}")
    inv.write(str(INV_OUT), format="STATIONXML")
    print(f"Wrote {INV_OUT}  ({INV_OUT.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
