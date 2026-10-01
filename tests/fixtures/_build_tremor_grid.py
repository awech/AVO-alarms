"""One-off: build the coarse Tremor travel-time grid fixture.

Run manually (NOT collected by pytest) to (re)generate the committed
travel-time grid used by the Tremor integration scenarios:

    PYTHONPATH=. python tests/fixtures/_build_tremor_grid.py

(PYTHONPATH=. so the ``tests`` package import resolves outside pytest.)

Uses the coarse grid defined in tests/fixtures/configs/Pavlof_tremor.yml (a
smaller node count than production, to keep the committed .npz small) and the
recorded Tremor waveforms, driving enveloc's grid computation exactly as
run_enveloc would, then saving the result to tests/fixtures/data/.
"""

from __future__ import annotations

import os
from pathlib import Path

import tests.conftest  # noqa: F401  (sets STATION_XML fixture, VOLCANO_LIST, etc.)

os.environ["CONFIGS_DIR"] = str(Path("tests/fixtures/configs").resolve())

from obspy import UTCDateTime, read  # noqa: E402

from volc_alarms.utils import processing, setup_utils  # noqa: E402
from volc_alarms.alarms.Tremor import detection  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent / "data"
GRID_OUT = FIXTURE_DIR / "Pavlof_Tremor_grid.npz"


def main() -> None:
    config = setup_utils.load_config("Pavlof_tremor")
    # Point at a path that does NOT yet exist so run_enveloc computes + saves it.
    config.grid_file = GRID_OUT.resolve()
    config.max_scatter = 1e9
    if GRID_OUT.exists():
        GRID_OUT.unlink()

    st_all = read(str(FIXTURE_DIR / "tremor_Pavlof_20260929T1035.mseed"))
    T0 = UTCDateTime("2026-09-29T10:35:00")
    t1 = T0 - 1.5 * config.window_length - config.taper
    t2 = T0 + config.taper
    st = st_all.copy().trim(t1, t2)

    band_env, high_env, band = detection.preprocess(st, config, t1, t2)
    band = processing.add_metadata(band)
    band_env = processing.add_metadata(band_env)
    high_env = processing.add_metadata(high_env)

    loc = detection.run_enveloc(st.copy(), band_env, high_env, config)
    print(f"Grid written: {GRID_OUT}  ({GRID_OUT.stat().st_size / 1024:.1f} KiB)")
    print(f"Located events on coarse grid: {len(loc.events)}")
    for e in loc.events:
        print(f"  {e.starttime}  lat={e.latitude:.3f} lon={e.longitude:.3f} depth={e.depth:.1f}")


if __name__ == "__main__":
    main()
