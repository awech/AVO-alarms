# volc-alarms

Python codes used for geophysical alarms at AVO. Currently (2026-Jun-18) running on Python 3.13.13.

`volc-alarms` runs a family of near-real-time monitoring alarms (seismic, acoustic, satellite, lightning, and advisory-feed based) that detect volcanic unrest and fan the results out to email/SMS, Mattermost, and Icinga.

## Quick start

It is recommended to do this in a fresh virtual environment:

```bash
# Create a virtual environment (conda example)
conda create -n alarms python=3.13
conda activate alarms
```

Clone the repository and change into the `volc-alarms` directory
```bash
git clone https://code.usgs.gov/vsc/seis/tools/volc-alarms.git
cd volc-alarms
```

```bash
# Install core dependencies
pip install -e .            # core dependencies

# Optionally include AVO-specific extras (mattermost, enveloc, etc.)
pip install -e .[avo]       # include AVO-specific extras (mattermost, enveloc, etc.)
```


Copy `.env_example` to `.env` and fill in the relevant system parameters, then run an alarm:

```bash
run-alarm Pavlof_RSAM                   # run with current time
run-alarm Pavlof_RSAM -t 201701020205   # run with a specific time
run-alarm Pavlof_RSAM --test --force    # test mode, no real notifications
```

## Documentation

Full documentation lives in [`docs/`](docs/index.md) and is published via GitLab Pages:

- [Installation](docs/installation.md) — dependencies, install, and running the alarms
- [System Configuration](docs/system-configuration.md) — paths, data access, URLs, email, logging
- [Alarm Modules](docs/alarm-modules.md) — what each alarm type detects
- [Alarm Configuration](docs/alarm-configuration.md) — per-alarm defaults, config math, rate limiting
- [Alerting](docs/alerting.md) — email/SMS, Icinga heartbeats, and Mattermost posts
- [Helper Scripts](docs/helper-scripts.md) — `list-alerts`, `update-metadata`, `update-html`, and more
- [API Reference](docs/api-reference.md) — auto-generated from source docstrings