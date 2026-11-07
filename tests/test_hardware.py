"""Hardware smoke test; opt in with RUN_HARDWARE_TESTS=1."""

import os

import pytest

from scietex.hal.dac import MCP4251

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_HARDWARE_TESTS") != "1",
        reason="hardware tests are opt-in; set RUN_HARDWARE_TESTS=1",
    ),
    pytest.mark.skipif(
        not os.path.exists("/dev/spidev0.1"),
        reason="no SPI device node at /dev/spidev0.1",
    ),
]


def test_mcp4251_on_spidev0_1_round_trips_both_channels() -> None:
    """A wired MCP4251 accepts and reports codes on both channels."""
    dac = MCP4251(port=0, device=1, reference=3.3)
    try:
        original = dac.read_all()
        dac.write_all((0, 128))
        assert dac.read_all() == (0, 128)
    finally:
        dac.write_all(original)
        dac.close()
