"""Unit tests for ``volc_alarms.utils.setup_utils``.

These cover the config-parsing and file-loading helpers with crafted strings
and tmp files. No network is involved. ``load_config`` reads the real repo
``config/*.yml`` (CONFIGS_DIR is set by the top-level conftest).

Covered:
* looks_like_path        — path vs NSLC vs plain-value discrimination
* _evaluate_math_expr    — arithmetic string eval, int coercion, passthrough
* _apply_math_expressions — top-level + nested "value"/"duration" resolution
* load_config            — real YAML -> SimpleNamespace with expected attrs
* load_volcano_list      — CSV load, missing-column error, bad-format error
* _detect_system_tz      — returns a non-empty IANA-ish string

TODO: load_environment / setup_root_logger / get_logger touch process-global
state (env, logging handlers) and are exercised via the integration harness.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from volc_alarms.utils import setup_utils

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# looks_like_path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        ("data/file.csv", True),
        ("./relative/path", True),
        ("~/home/thing", True),
        ("$ENV_VAR/path", True),
        ("config.yml", True),
        ("AV.DLL.01.BDF", False),   # NSLC channel, not a path
        ("plainstring", False),
        (12345, False),             # non-string
    ],
)
def test_looks_like_path_discriminates_paths_from_values(value, expected):
    """looks_like_path treats separators/extensions as paths but not NSLC codes."""
    assert setup_utils.looks_like_path(value) is expected


# ---------------------------------------------------------------------------
# _evaluate_math_expr
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        ("3600 * 24", 86400),
        ("350/100", 3.5),
        ("6000", 6000),
        ("not-math", "not-math"),  # non-arithmetic string passes through
        (42, 42),                   # non-string passes through
    ],
)
def test_evaluate_math_expr_resolves_arithmetic_strings(value, expected):
    """_evaluate_math_expr evaluates safe arithmetic and passes anything else through."""
    assert setup_utils._evaluate_math_expr(value) == expected


def test_evaluate_math_expr_returns_int_for_whole_number_results():
    """_evaluate_math_expr coerces whole-number float results to int."""
    result = setup_utils._evaluate_math_expr("10 / 2")
    assert result == 5
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# _apply_math_expressions
# ---------------------------------------------------------------------------
def test_apply_math_expressions_resolves_top_level_and_nested_keys():
    """_apply_math_expressions evaluates 'value'/'duration' at top level and in nested dicts/lists."""
    config = SimpleNamespace(
        duration="3600 * 2",
        rsam_stations=[{"nslc": "AV.X..BHZ", "value": "350/100"}],
        arrestor={"nslc": "AV.Y..BHZ", "value": "200"},
    )

    setup_utils._apply_math_expressions(config)

    assert config.duration == 7200
    assert config.rsam_stations[0]["value"] == 3.5
    assert config.arrestor["value"] == 200


# ---------------------------------------------------------------------------
# load_config (real repo config)
# ---------------------------------------------------------------------------
def test_load_config_parses_real_rsam_yaml_to_namespace():
    """load_config wraps a real config/*.yml into a SimpleNamespace with attributes."""
    config = setup_utils.load_config("RSAM")
    assert config.alarm_type == "RSAM"
    assert config.alarm_name == "Semisopochnoi RSAM"
    # A math-eligible nested value has been resolved to a number.
    assert all(
        isinstance(sta["value"], (int, float)) for sta in config.rsam_stations
    )


# ---------------------------------------------------------------------------
# load_volcano_list
# ---------------------------------------------------------------------------
def test_load_volcano_list_reads_csv_with_required_columns(tmp_path):
    """load_volcano_list loads a CSV that has Name/Latitude/Longitude."""
    csv = tmp_path / "volcs.csv"
    csv.write_text("Name,Latitude,Longitude\nPavlof,55.417,-161.894\n")
    df = setup_utils.load_volcano_list(csv)
    assert list(df["Name"]) == ["Pavlof"]
    assert {"Name", "Latitude", "Longitude"}.issubset(df.columns)


def test_load_volcano_list_missing_columns_raises_valueerror(tmp_path):
    """load_volcano_list raises ValueError when required columns are absent."""
    csv = tmp_path / "bad.csv"
    csv.write_text("Name,Lat,Lon\nPavlof,55.4,-161.9\n")
    with pytest.raises(ValueError, match="Missing required columns"):
        setup_utils.load_volcano_list(csv)


def test_load_volcano_list_unsupported_format_raises_valueerror(tmp_path):
    """load_volcano_list raises ValueError for an unsupported file extension."""
    bad = tmp_path / "volcs.json"
    bad.write_text("{}")
    with pytest.raises(ValueError, match="Unsupported file format"):
        setup_utils.load_volcano_list(bad)


# ---------------------------------------------------------------------------
# _detect_system_tz
# ---------------------------------------------------------------------------
def test_detect_system_tz_returns_nonempty_string():
    """_detect_system_tz returns a non-empty timezone name (falls back to UTC)."""
    tz = setup_utils._detect_system_tz()
    assert isinstance(tz, str)
    assert tz
