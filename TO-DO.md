# AVO alarms To-Do

## :sparkles: Features

- [ ] Organize file structure better - like a python package
- [ ] Numerous folders with .py scripts that are much more simple and grouped by their tasks
- [ ] add `pyproject.toml` file
- [ ] change all `string{}.format()` to fstring
- [ ] Get dependencies up to date. Make all effort to minimize
- [ ] sort out cartopy/basemap kerfuffle --> modernize to just use cartopy
- [ ] utilize one map making function
- [ ] make effort to use `subplot_mosaic` for panel plots 
- [ ] implement test flag
    - [ ] RSAM
    - [ ] Infrasound
    - [ ] Magnitude
    - [ ] NOAA_CIMSS
    - [ ] Pilot_Report
    - [ ] SIGMET
    - [ ] SO2
    - [ ] Swarm
    - [ ] Tremor
    - [ ] utils.messaging
    - [ ] utils.plotting (fig watermark)
- [ ] add test data in own directory
- [x] implement default "all" message distribution
- [ ] implement Python logger
- [ ] implement CI/CD with test data to run tests once a month 
- [ ] add defaults to infrasound parameters that then can be overwritten if need be (`vmin`, `vmax`, `min_pa`)

## :books: Documentation
- [ ] Add version
- [ ] `numpy` flavored docstrings
- [ ] better line-by-line comments throughout
- [ ] create better HOW-TO style docs using the Wiki

## :bug: Bug Fixes

## Ops
- [ ] Switch to mattermost token
- [x] Spin up VM for back up and testing
- [x] start fresh with miniforge for venv
- [ ] change all instances of string filepaths to pathlib objects for OS agnostic alarm running. 
