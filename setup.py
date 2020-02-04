#!/usr/bin/env python

from distutils.core import setup
from os.path import abspath, dirname, join

from setuptools import find_packages

with open(
    join(dirname(abspath(__file__)), "saga_tools", "version.py")
) as version_file:
    exec(compile(version_file.read(), "version.py", "exec"))

setup(
    name="saga_tools",
    version=version,  # noqa
    author="Ryan Gabbard",
    author_email="gabbard@isi.edu",
    description="Tools for more convenient use of the ISI VISTA SAGA Cluster",
    url="https://github.com/isi-vista/saga-tools",
    packages=[],
    # 3.6 and up, but not Python 4
    python_requires="~=3.6",
    install_requires=[],
    scripts=[],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
