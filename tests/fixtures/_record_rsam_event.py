"""One-off recorder: capture a real Pavlof RSAM event window to a fixture.

Run manually (NOT collected by pytest) to (re)generate the offline waveform
fixture used by the RSAM CRITICAL integration scenario:

    python tests/fixtures/_record_rsam_event.py

Downloads the six Pavlof source channels plus the arrestor around the known
event time from the Winston server named in the environment and writes a
compact MiniSEED file to tests/fixtures/data/. The integration scenarios then
load that file and feed it to the faked download_waveforms, so the tests stay
fully offline.
"""

from __future__ import annotations

from pathlib import Path

from obspy import UTCDateTime

from volc_alarms.utils import downloading

# Known Pavlof RSAM event (UTC). run_alarm downloads [T0-duration-taper,
# T0+taper]; grab a wider pad so the fixture is robust to duration/taper tweaks.
T0 = UTCDateTime("2026-09-28T20:40:00")
PAD_BEFORE = 360.0
PAD_AFTER = 30.0

NSLC = [
    "AV.PS4A..BHZ",
    "AV.PVV..BHZ",
    "AV.PS1A..BHZ",
    "AV.HAG..BHZ",
    "AV.PN7A..BHZ",
    "AV.PV6A..BHZ",
    "AV.BLDW..BHZ",  # arrestor
]

OUT = Path(__file__).resolve().parent / "data" / "rsam_Pavlof_20260928T2040.mseed"


def main() -> None:
    t1 = T0 - PAD_BEFORE
    t2 = T0 + PAD_AFTER
    print(f"Downloading {len(NSLC)} Pavlof channels for {t1} - {t2} ...")
    st = downloading.download_waveforms(NSLC, t1, t2)
    print("Got stream:")
    print(st.__str__(extended=True))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    st.write(str(OUT), format="MSEED", encoding="STEIM2", reclen=512)
    print(f"Wrote fixture: {OUT}  ({OUT.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
