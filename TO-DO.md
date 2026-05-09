# AVO alarms To-Do

## :sparkles: Features

- [x] Organize file structure better - like a python package
- [x] Numerous folders with .py scripts that are much more simple and grouped by their tasks
- [x] add `pyproject.toml` file
- [x] change `main.py` to be run as exectuable
- [ ] add memory to RSAM and Infrasound alarms
- [x] change all `string{}.format()` to fstring
- [x] change all SCNL to NSLC!
- [x] Get dependencies up to date. Make all effort to minimize
- [x] sort out cartopy/basemap kerfuffle --> modernize to just use cartopy
- [x] utilize one map making function
- [x] make effort to use `subplot_mosaic` for panel plots 
- [ ] use os.getenv() instead of os.environ[] where appropriate
- [x] move configs to external repository
- [x] implement default "all" message distribution
- [ ] allow for distribution/phonebook to be environment variables
- [x] edit notifications html script to use yml files
- [ ] convert configs to .yml
- [ ] move distribution file to configs repository as (maybe) .yml
- [x] implement Python logger
- [ ] add defaults to infrasound parameters that then can be overwritten if need be (`vmin`, `vmax`, `min_pa`)
- [ ] implement a 'kill' switch - probably from config file
- [ ] change volcano list file to csv. Possibly need separate AVO xlsx file.

## :test_tube: Tests
- [x] sort out `test_flag` vs possible `force` flag
- [ ] implement force & test flag
    - [x] RSAM
    - [x] Infrasound
    - [x] Magnitude
    - [x] Lightning
    - [x] NOAA_CIMSS
    - [x] Pilot_Report
    - [ ] VAA
    - [ ] SO2
    - [ ] Swarm
    - [ ] Tremor
    - [x] utils.messaging
    - [x] utils.plotting (fig watermark)
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
- [x] change all instances of string filepaths to pathlib objects for OS agnostic alarm running. 
