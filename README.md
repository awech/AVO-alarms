# volc-alarms

Python codes used for geophysical alarms at AVO. Currently (2026-Jun-18) running on Python 3.13.13.

`volc-alarms` runs a family of near-real-time monitoring alarms (seismic, acoustic, satellite, lightning, and advisory-feed based) that detect volcanic unrest and fan the results out to email/SMS, Mattermost, and Icinga.

## Quick start

### Installation
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
pip install -e ".[avo]"     # include AVO-specific extras (mattermost, enveloc, etc.)
```

### Setup email delivery
1. Copy `.env_example` to `.env` and edit:
- `SMTP_IP`
- `SMTP_PORT`
- `SMTP_SECURITY` (optional you need TLS inspection)

2. Set up a test recipient
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

3. Verify email delivery end-to-end with `email-test`, which sends a
single message (and attachment) to the `Test` recipients
    ```bash
    email-test # can be slow the first time
    ```

### Test alarm
1. edit the `All Alarms` recipient in `config/distribution.yml`
    ```yaml
    # config/distribution.yml
    All Alarms:
    - Your Name     # must match an entry in config/phonebook.yml
    ```
2. Run a test alarm. This example uses the bundled `config/RSAM.yml` and the 
`--earthscope` flag, which pulls waveforms from EarthScope
    ```bash
    run-alarm RSAM -t 202607161210 --earthscope # can be slow the first time
    ```

## Documentation

Full documentation lives in [`docs/`](docs/index.md) and is published via GitLab Pages:

- [Quickstart](docs/quickstart.md) — install, verify email delivery, and run a test alarm
- [System Configuration](docs/system-configuration.md) — directory structure, environment variables, data access, email setup, logging
- [Alarm Workflow](docs/alarm-workflow.md) — how a run flows from dispatch to detection to the send sequence
- [Alerting](docs/alerting.md) – distribution setup, icinga, mattermost, test messages
- [Alarm Modules](docs/alarm-modules.md) — what each alarm type detects
- [Alarm Configuration](docs/alarm-configuration.md) — per-alarm defaults, config math, rate limiting
- [Helper Scripts](docs/helper-scripts.md) — `list-alerts`, `update-metadata`, `update-html`, and more