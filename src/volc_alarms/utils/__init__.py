"""Utility subpackage: re-exports submodules and applies the shared matplotlib style on import."""

from pathlib import Path

import matplotlib.pyplot as plt

from . import messaging, plotting, processing, setup_utils, downloading

plt.style.use(Path(__file__).parent.parent / "data" / "alarms.mplstyle")

__all__ = ["downloading", "messaging", "plotting", "processing", "setup_utils"]
