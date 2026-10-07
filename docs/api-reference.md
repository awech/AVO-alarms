# API Reference

This page is generated automatically from the source docstrings via [mkdocstrings](https://mkdocstrings.github.io/). Edit the docstrings in `src/volc_alarms/` to update it.

## Package

::: volc_alarms

## Alarm modules

Each alarm lives in its own package with the same four-file layout: the `run_alarm` entry point (invoked by `run-alarm`) is defined in **`__init__.py`**, with `detection.py`, `figure.py`, and `message.py` holding the data/logic, plotting, and alert-text helpers respectively. Expand "Helper modules" under an alarm to see its `detection`/`figure`/`message` files.

### RSAM

::: volc_alarms.alarms.RSAM

??? note "Helper modules"
    ::: volc_alarms.alarms.RSAM.detection
    ::: volc_alarms.alarms.RSAM.figure
    ::: volc_alarms.alarms.RSAM.message

### Infrasound

::: volc_alarms.alarms.Infrasound

??? note "Helper modules"
    ::: volc_alarms.alarms.Infrasound.detection
    ::: volc_alarms.alarms.Infrasound.figure
    ::: volc_alarms.alarms.Infrasound.message

### Tremor

::: volc_alarms.alarms.Tremor

??? note "Helper modules"
    ::: volc_alarms.alarms.Tremor.detection
    ::: volc_alarms.alarms.Tremor.figure
    ::: volc_alarms.alarms.Tremor.message

### Magnitude

::: volc_alarms.alarms.Magnitude

??? note "Helper modules"
    ::: volc_alarms.alarms.Magnitude.detection
    ::: volc_alarms.alarms.Magnitude.figure
    ::: volc_alarms.alarms.Magnitude.message

### Swarm

::: volc_alarms.alarms.Swarm

??? note "Helper modules"
    ::: volc_alarms.alarms.Swarm.detection
    ::: volc_alarms.alarms.Swarm.figure
    ::: volc_alarms.alarms.Swarm.message

### NOAA_CIMSS

::: volc_alarms.alarms.NOAA_CIMSS

??? note "Helper modules"
    ::: volc_alarms.alarms.NOAA_CIMSS.detection
    ::: volc_alarms.alarms.NOAA_CIMSS.figure
    ::: volc_alarms.alarms.NOAA_CIMSS.message

### SO2

::: volc_alarms.alarms.SO2

??? note "Helper modules"
    ::: volc_alarms.alarms.SO2.detection
    ::: volc_alarms.alarms.SO2.figure
    ::: volc_alarms.alarms.SO2.message

### Lightning

::: volc_alarms.alarms.Lightning

??? note "Helper modules"
    ::: volc_alarms.alarms.Lightning.detection
    ::: volc_alarms.alarms.Lightning.figure
    ::: volc_alarms.alarms.Lightning.message

### Pilot_Report

::: volc_alarms.alarms.Pilot_Report

??? note "Helper modules"
    ::: volc_alarms.alarms.Pilot_Report.detection
    ::: volc_alarms.alarms.Pilot_Report.figure
    ::: volc_alarms.alarms.Pilot_Report.message

### VAA

::: volc_alarms.alarms.VAA

??? note "Helper modules"
    ::: volc_alarms.alarms.VAA.detection
    ::: volc_alarms.alarms.VAA.figure
    ::: volc_alarms.alarms.VAA.message

## Utilities

There are 7 shared utility files: `setup_utils.py`, `alarm_flow.py`, `alarming.py`, `downloading.py`, `processing.py`, `plotting.py`, and `messaging.py`

### Setup &amp; configuration

::: volc_alarms.utils.setup_utils

### Alarm flow

::: volc_alarms.utils.alarm_flow

### Alarming

::: volc_alarms.utils.alarming

### Downloading

::: volc_alarms.utils.downloading

### Processing

::: volc_alarms.utils.processing

### Plotting

::: volc_alarms.utils.plotting

### Notifications (messaging)

::: volc_alarms.utils.messaging
