#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-3.0-only
# LLNL-CODE-805542
"""Setuptools configuration for the MTtime fork."""

from __future__ import annotations

import codecs
import os
from setuptools import find_packages, setup

NAME = "mttime"
VERSION = "1.1.0"
HERE = os.path.abspath(os.path.dirname(__file__))
PYFK_PY310_COMMIT = "fd7fc91ad36f900c8d77cc413b2f95a728cb0eca"


def read(*parts: str) -> str:
    """Read a UTF-8 text file relative to the repository root."""
    with codecs.open(os.path.join(HERE, *parts), "rb", "utf-8") as file:
        return file.read()


def env_flag(name: str) -> bool:
    """Return True for common truthy environment-variable spellings."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


INSTALL_REQUIRES = [
    "numpy>=1.21",
    "scipy>=1.7",
    "obspy>=1.3",
    "pandas>=1.0",
    "matplotlib>=3.5",
    "pyproj>=3.3",
    "requests>=2.25",
    "tqdm>=4.60",
]

# PyFK is the default Green's-function backend on Linux/WSL.  The published
# PyFK 0.3.x metadata is restricted to Python <3.10, whereas PR #20 modernizes
# it for Python 3.10-3.12.  Pinning the PR head keeps VCS installs reproducible
# until an upstream release supersedes it.  Windows/macOS installs remain
# Syngine-capable without attempting to build PyFK.  Linux users who explicitly
# want a Syngine-only installation can set MTTIME_NO_PYFK=1 for the pip command.
if not env_flag("MTTIME_NO_PYFK"):
    INSTALL_REQUIRES.extend([
        "pyfk>=0.3.0,<0.4; platform_system == 'Linux' and python_version < '3.10'",
        (
            "pyfk @ git+https://github.com/ziyixi/pyfk.git@"
            f"{PYFK_PY310_COMMIT} ; platform_system == 'Linux' and "
            "python_version >= '3.10' and python_version < '3.13'"
        ),
    ])

CLASSIFIERS = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "Intended Audience :: Developers",
    "Operating System :: POSIX :: Linux",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: MacOS",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Physics",
]

ENTRY_POINTS = {"console_scripts": ["mttime-run = mttime.scripts.run:main"]}


if __name__ == "__main__":
    setup(
        name=NAME,
        version=VERSION,
        description="Time-domain moment tensor inversion with additive workflow helpers",
        long_description=read("README.rst"),
        long_description_content_type="text/x-rst",
        license="LGPL-3.0-only",
        license_files=("LICENSE", "NOTICE"),
        url="https://github.com/AaronJR474/mttime",
        project_urls={
            "Upstream": "https://github.com/LLNL/mttime",
            "Upstream documentation": "https://mttime.readthedocs.io/en/latest/index.html",
        },
        author="Andrea Chiang and MTtime contributors",
        maintainer="Aaron J. Rampersad",
        keywords=["seismology", "moment tensor", "inversion", "green functions"],
        packages=find_packages(where="src"),
        package_dir={"": "src"},
        entry_points=ENTRY_POINTS,
        python_requires=">=3.8,<3.13",
        classifiers=CLASSIFIERS,
        install_requires=INSTALL_REQUIRES,
        extras_require={
            "maps": ["cartopy>=0.20"],
            "test": ["pytest>=7"],
            "docs": ["sphinx>=4", "sphinx-rtd-theme>=1", "packaging>=21"],
        },
        include_package_data=True,
        zip_safe=False,
    )
