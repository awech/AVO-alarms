"""Volcano monitoring alarm system."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("volc-alarms")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "Infrasound",
    "Lightning",
    "Magnitude",
    "NOAA_CIMSS",
    "Pilot_Report",
    "RSAM",
    "SO2",
    "Swarm",
    "Tremor",
    "VAA",
]


def __getattr__(name):
    """Lazy-load alarm submodules on first access."""
    if name in __all__:
        from importlib import import_module

        module = import_module(f"volc_alarms.alarms.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'volc_alarms' has no attribute {name!r}")
