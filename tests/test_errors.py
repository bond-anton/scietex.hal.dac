"""Error reporting of the MCP4xxx DAC wrappers."""

import pytest
from conftest import RecordingTransport, build, wiper_frame
from scietex.hal.spi import FakeSpiTransport, TransportError

from scietex.hal.dac import MCP4231, MCP4251, DACCodeError


def test_transport_error_propagates_from_a_read() -> None:
    """A bus failure is never turned into a code error."""
    transport = FakeSpiTransport(responses=[wiper_frame(0)] * 5)
    dac, _ = build(transport=transport)
    with pytest.raises(TransportError) as excinfo:
        _ = dac.channel(0).value
    assert not isinstance(excinfo.value, DACCodeError)


def test_transport_error_propagates_from_a_write() -> None:
    """The write command fails before any read-back is attempted."""
    transport = FakeSpiTransport(responses=[wiper_frame(0)] * 5)
    dac, _ = build(transport=transport)
    with pytest.raises(TransportError):
        dac.channel(0).value = 5
    assert dac.channel(0)._reported_code is None


def test_malformed_read_frame_is_a_value_error() -> None:
    """A device answer with broken framing is rejected by the wrapped part."""
    transport = RecordingTransport(
        responses=[wiper_frame(0)] * 5,
        default=[0x00, 0x00],
    )
    dac, _ = build(transport=transport)
    with pytest.raises(ValueError) as excinfo:
        _ = dac.channel(0).value
    assert "[0, 0]" in str(excinfo.value)


@pytest.mark.parametrize(
    ("part", "bad_code"),
    [(MCP4231, 128), (MCP4251, 256), (MCP4251, -1)],
)
def test_out_of_range_code_is_a_dac_code_error(part: type, bad_code: int) -> None:
    """A code outside `0..max_code` is reported as this package's error."""
    dac, _ = build(part)
    with pytest.raises(DACCodeError) as excinfo:
        dac.channel(0).value = bad_code
    assert isinstance(excinfo.value, ValueError)


def test_a_missing_channel_is_an_index_error() -> None:
    """A channel outside the geometry never reaches the bus."""
    dac, transport = build()
    transport.calls.clear()
    with pytest.raises(IndexError):
        dac.channel(2)
    assert transport.calls == []


def test_a_missing_channel_never_reaches_the_wrapped_part() -> None:
    """The DAC geometry rejects the index before the device is asked."""
    dac, transport = build(channels=1)
    transport.calls.clear()
    with pytest.raises(IndexError):
        dac.channel(1)
    assert transport.calls == []
