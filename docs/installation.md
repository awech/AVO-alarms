# Installation

`volc-alarms` currently runs on python 3.11–3.14.

## Python dependencies

**Core:**

- obspy
- pandas
- pyyaml
- jinja2
- cartopy
- cmcrameri
- matplotlib
- numba
- numpy
- python-dotenv
- utm
- scikit-learn
- requests
- scipy
- tabulate

**Optional (AVO-specific, install with `pip install .[avo]`):**

- beautifulsoup4
- enveloc
- pillow
- mattermostdriver
- openpyxl

## Install

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
pip install -e .

# Optionally include AVO-specific extras (mattermost, enveloc, etc.)
pip install -e .[avo]
```
