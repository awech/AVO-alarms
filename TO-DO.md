# AVO alarms To-Do

## :sparkles: Features

- [x] Organize file structure better - like a python package
- [ ] Numerous folders with .py scripts that are much more simple and grouped by their tasks
- [ ] add `pyproject.toml` file
- [ ] change `main.py` to be run as exectuable
- [ ] change all `string{}.format()` to fstring
- [ ] change all SCNL to NSLC!
- [ ] Get dependencies up to date. Make all effort to minimize
- [ ] sort out cartopy/basemap kerfuffle --> modernize to just use cartopy
- [ ] utilize one map making function
- [ ] make effort to use `subplot_mosaic` for panel plots 
- [x] move configs to external repository
- [x] implement default "all" message distribution
- [ ] allow for distribution/phonebook to be environment variables
- [ ] edit notifications html script to use yml files
- [ ] move distribution file to configs repository as (maybe) .yml
- [x] implement Python logger
- [ ] add defaults to infrasound parameters that then can be overwritten if need be (`vmin`, `vmax`, `min_pa`)
- [ ] implement a 'kill' switch - probably from config file

## :test_tube: Tests
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
- [ ] implement CI/CD with test data to run tests once a month 

## :books: Documentation
- [ ] Add version
- [ ] `numpy` flavored docstrings
- [ ] better line-by-line comments throughout
- [ ] create better HOW-TO style docs using the Wiki
- [ ] publish with DOI :shrug:

## :bug: Bug Fixes

## Ops
- [x] Move away from tomputils mattermost (unsupported)
- [ ] Switch to mattermost token
- [x] implement new file lock strategy
- [x] Spin up VM for back up and testing
- [x] start fresh with miniforge for venv
- [ ] change all instances of string filepaths to pathlib objects for OS agnostic alarm running. 
