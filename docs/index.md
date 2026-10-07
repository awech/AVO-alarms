# `volc-alarms` documentation

`volc-alarms` is a python package that runs a family of near-real-time monitoring alarms
(seismic, acoustic, satellite, lightning, and advisory-feed based) that detect volcanic unrest 
and fan the results out to email/SMS, Mattermost, and Icinga.

The codes were developed for and are used operational at the Alaska Volcano Observatory.

## Documentation

| Section | What's inside |
|---------|---------------|
| [Installation](installation.md) | Dependencies, install commands, and running the alarms |
| [Getting Started](getting-started.md) | Directory/file paths, data access, URLs, email, logging defaults |
| [Alarm Modules](alarm-modules.md) | Overview of each alarm type and what it detects |
| [Alarm Configuration](alarm-configuration.md) | Per-alarm defaults, config math, rate limiting, notifications |
| [Alerting](alerting.md) | Email/SMS, Icinga heartbeats, and Mattermost posting |
| [Helper Scripts](helper-scripts.md) | `list-alerts`, `update-metadata`, `update-html`, and friends |
| [API Reference](api-reference.md) | Auto-generated reference from the source docstrings |