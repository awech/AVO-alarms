"""One-off recorder: capture a real KENI infrasound event window to a fixture.

Run manually (NOT collected by pytest) to (re)generate the offline waveform
fixture used by the Infrasound CRITICAL integration scenario:

    python tests/fixtures/_record_infrasound_event.py

It downloads the six KENI array channels around the known event time from the
Winston server named in the environment and writes a compact MiniSEED file to
tests/fixtures/data/. The integration scenario then loads that file and feeds it
to the faked download_waveforms, so the test itself stays fully offline.
"""

from __future__ import annotations

from pathlib import Path

from obspy import UTCDateTime

from volc_alarms.utils import downloading

# Known KENI Infrasound event (UTC). run_alarm downloads [T0-duration-taper,
# T0+taper]; we grab a slightly wider pad so the fixture is robust to config
# duration/taper tweaks.
T0 = UTCDateTime("2026-05-14T22:56:00")
PAD_BEFORE = 150.0
PAD_AFTER = 30.0

NSLC = [
    "AV.KENI.01.HDF",
    "AV.KENI.02.HDF",
    "AV.KENI.03.HDF",
    "AV.KENI.04.HDF",
    "AV.KENI.05.HDF",
    "AV.KENI.06.HDF",
]

OUT = Path(__file__).resolve().parent / "data" / "infrasound_KENI_20260514T2256.mseed"


def main() -> None:
    t1 = T0 - PAD_BEFORE
    t2 = T0 + PAD_AFTER
    print(f"Downloading {len(NSLC)} KENI channels for {t1} - {t2} ...")
    st = downloading.download_waveforms(NSLC, t1, t2)
    print("Got stream:")
    print(st.__str__(extended=True))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # STEIM2-compressed MiniSEED keeps the fixture small.
    st.write(str(OUT), format="MSEED", encoding="STEIM2", reclen=512)
    print(f"Wrote fixture: {OUT}  ({OUT.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
