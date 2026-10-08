# Quickstart

`volc-alarms` currently runs on python 3.11–3.14.

This page gets you from a clean environment to one working alarm: install the
package, verify email delivery, then run a test alarm. For the full picture of
paths, data access, and configuration, see
[System Configuration](system-configuration.md).

## Dependencies

**Core:** `obspy`, `pandas`, `pyyaml`, `jinja2`, `cartopy`, `cmcrameri`, 
`matplotlib`, `numba`, `numpy`, `python-dotenv`, `utm`, `scikit-learn`, 
`requests`, `scipy`, `tabulate`

**Optional** (AVO-specific, install with `pip install ".[avo]"`): `beautifulsoup4`,
`enveloc`, `pillow`, `mattermostdriver`, `openpyxl`

## Installation

It is recommended to do this in a fresh virtual environment:

```bash
# Create a virtual environment (conda example)
conda create -n alarms python=3.13
conda activate alarms
```

Clone the repository and change into the `volc-alarms` directory:

```bash
git clone https://code.usgs.gov/vsc/seis/tools/volc-alarms.git
cd volc-alarms
```

```bash
# Install core dependencies
pip install -e .

# Optionally include AVO-specific extras (mattermost, enveloc, etc.)
pip install -e ".[avo]"
```

## Setup email delivery

1. Copy `.env_example` to `.env` and edit:
    - `SMTP_IP`
    - `SMTP_PORT`
    - `SMTP_SECURITY` (optional; set to `starttls` if your server needs it instead of the `ssl` default)

2. Set up a test recipient:
    - edit `config/phonebook.yml`
        ```yaml
        # config/phonebook.yml
        Your Name: youremail@email.com
        ```

    - edit the `Test` recipient in `config/distribution.yml`
        ```yaml
        # config/distribution.yml
        Test:
            - Your Name     # must match an entry in config/phonebook.yml
        ```

3. Verify email delivery end-to-end with `email-test`, which sends a single
   message (and attachment) to the `Test` recipients:
    ```bash
    email-test  # can be slow the first time
    ```

## Test alarm

1. Edit the `All Alarms` recipient in `config/distribution.yml`:
    ```yaml
    # config/distribution.yml
    All Alarms:
      - Your Name     # must match an entry in config/phonebook.yml
    ```

2. Run a test alarm. This example uses the bundled `config/RSAM.yml` and the
   `--earthscope` flag, which pulls waveforms from EarthScope:
    ```bash
    run-alarm RSAM -t 202607161210 --earthscope  # can be slow the first time
    ```
