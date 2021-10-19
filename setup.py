"""
avo_alarm_codes -- modules implementing AVO's routine alarm codes.
"""

from setuptools import setup, find_packages

DOCSTRING = __doc__.split("\n")

setup(
    name="avo_alarm_codes",
    version="0.0.1",
    author="Aaron Wech",
    author_email="awech@usgs.gov",
    description=(DOCSTRING[1]),
    license="CC0",
    url="https://github.com/awech/AVO-alarms",
    packages=find_packages(),
    long_description="\n".join(DOCSTRING[3:]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Topic :: Software Development :: Libraries",
        "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication",
    ],
    install_requires=["dotenv", "obspy", "numpy", "pandas", "matplotlib"],
    setup_requires=[""],
    tests_require=[""],
    entry_points={
        "console_scripts": [
        ]
    },
)
