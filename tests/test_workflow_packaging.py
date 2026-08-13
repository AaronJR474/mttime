"""Packaging regressions for the additive workflow subpackage."""

from pathlib import Path
from setuptools import find_packages


def test_workflows_is_discovered_as_an_installable_package():
    root = Path(__file__).resolve().parents[1]
    packages = set(find_packages(where=str(root / "src")))
    assert "mttime.workflows" in packages
