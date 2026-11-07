"""Hardware smoke test; opt in with RUN_HARDWARE_TESTS=1."""

import os

import pytest

from scietex.hal.dac import AD420, AD5420, MCP4251

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


def test_ad5420_round_trips_a_code_over_the_real_bus() -> None:
    """A wired AD5420 accepts a code and reports the same code back.

    This is the test that pins the SDO byte order. If it fails while the
    write succeeded, `AD54x0._READ_SHIFT` and `AD54x0._READ_SWAP` are the only
    adjustment points: the first shifts the received word, the second treats
    its three bytes as little-endian.
    """
    dac = AD5420(port=0, device=1)
    try:
        dac.configure(range="4-20mA")
        dac.enable_output()
        dac.channel(0).value = 0x1234
        assert dac.channel(0).value == 0x1234
    finally:
        dac.close()


def test_ad420_accepts_a_code_without_raising() -> None:
    """A wired AD420 latches a code; there is no readback to confirm it.

    The part has no register read path, so correctness can only be checked
    with an external ammeter on the loop.
    """
    dac = AD420(range="4-20mA", port=0, device=1, latch_pin=17)
    try:
        dac.channel(0).value = 0x8000
    finally:
        dac.close()
