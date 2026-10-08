# `volc-alarms` documentation

`volc-alarms` is a python package that runs a family of near-real-time monitoring alarms
(seismic, acoustic, satellite, lightning, and advisory-feed based) that detect volcanic unrest 
and fan the results out to email/SMS, Mattermost, and Icinga.

The codes were developed for and are used operational at the Alaska Volcano Observatory.

## Documentation

| Section | What's inside |
|---------|---------------|
| [Quickstart](quickstart.md) | Install, verify email delivery, and run a test alarm |
| [System Configuration](system-configuration.md) | Directory structure, environment variables, data access, email setup, logging |
| [Alarm Workflow](alarm-workflow.md) | How a run flows from dispatch to detection to the send sequence |
| [Alerting](alerting.md) | Distribution setup, icinga, mattermost, test messages |
| [Alarm Modules](alarm-modules.md) | Overview of each alarm type and what it detects |
| [Alarm Configuration](alarm-configuration.md) | Per-alarm defaults, config math, rate limiting, notifications |
| [Helper Scripts](helper-scripts.md) | `list-alerts`, `update-metadata`, `update-html`, and friends |
| [API Reference](api-reference.md) | Auto-generated reference from the source docstrings |