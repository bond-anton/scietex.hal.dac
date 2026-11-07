"""Test package version is correctly set"""

import re

import pytest

from scietex.hal.dac import __version__


def test_version_matches_the_release():
    """
    The package version is the one this release documents.
    """
    assert __version__ == "0.1.0"


def test_version_is_semver_shaped():
    """
    Version must be three integers separated by dots. Example: `0.1.4`.
    """
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


if __name__ == "__main__":
    pytest.main()
