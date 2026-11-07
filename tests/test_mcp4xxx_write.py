"""Frame encoding and read-back of the MCP4xxx DAC wrappers."""

import pytest
from conftest import build, wiper_frame
from scietex.hal.spi import FakeSpiTransport

from scietex.hal.dac import (
    MCP4231,
    MCP4241,
    MCP4251,
    MCP4261,
    DACCodeError,
)

PARTS_7_BIT = [MCP4231, MCP4241]
PARTS_8_BIT = [MCP4251, MCP4261]
REFERENCE = 3.3


def write_frame(channel: int, code: int) -> list[int]:
    """Request frame that writes `code` to `channel` on an MCP4xxx."""
    return [0x10 * channel, code & 0xFF]


def read_frame(channel: int) -> list[int]:
    """Request frame that reads `channel` back from an MCP4xxx."""
    return [0x0C | 0x10 * channel, 0x00]


def test_channel_0_write_frame() -> None:
    """Channel 0 writes with the bare wiper command and no address bit."""
    dac, transport = build()
    transport.calls.clear()
    dac.channel(0).value = 5
    assert transport.calls == [[0x00, 0x05], [0x0C, 0x00]]


def test_channel_1_write_frame() -> None:
    """Channel 1 sets AD0, which moves both the write and the read frame."""
    dac, transport = build()
    transport.calls.clear()
    dac.channel(1).value = 5
    assert transport.calls == [[0x10, 0x05], [0x1C, 0x00]]


@pytest.mark.parametrize("channel", [0, 1])
def test_every_write_is_followed_by_a_read_back(channel: int) -> None:
    """A write is two transactions: the command and the register read."""
    dac, transport = build()
    transport.calls.clear()
    dac.channel(channel).value = 9
    assert transport.calls == [write_frame(channel, 9), read_frame(channel)]


@pytest.mark.parametrize(
    ("part", "top_code"),
    [(part, 127) for part in PARTS_7_BIT] + [(part, 255) for part in PARTS_8_BIT],
)
def test_top_code_write_frame(part: type, top_code: int) -> None:
    """The top code is `2**bits - 1`, so D8 stays clear in the write frame."""
    dac, transport = build(part)
    assert dac.max_code == top_code
    transport.calls.clear()
    dac.channel(0).value = top_code
    assert transport.calls[0] == write_frame(0, top_code)
    assert transport.calls[0] == [0x00, top_code]


def test_set_value_reports_the_device_read_back() -> None:
    """A write returns the register value the device reports, not the input."""
    transport = FakeSpiTransport(
        responses=[wiper_frame(0)] * 5,
        default=wiper_frame(42),
    )
    dac, _ = build(transport=transport)
    channel = dac.channel(0)
    channel.value = 5
    assert channel._reported_code == 42
    assert channel.value == 42


def test_a_channel_read_is_one_transaction() -> None:
    """Reading a channel is a single register read, with no cache in between."""
    dac, transport = build()
    transport.calls.clear()
    assert dac.channel(1).value == 0
    assert transport.calls == [[0x1C, 0x00]]


def test_read_all_reads_every_channel_in_index_order() -> None:
    """`read_all` asks each channel once, in order."""
    dac, transport = build()
    transport.calls.clear()
    assert dac.read_all() == (0, 0)
    assert transport.calls == [[0x0C, 0x00], [0x1C, 0x00]]


def test_write_all_writes_both_channels_in_index_order() -> None:
    """The codes are applied channel by channel and echoed back."""
    dac, transport = build()
    transport.calls.clear()
    assert dac.write_all([5, 6]) == (5, 6)
    assert transport.calls == [
        [0x00, 0x05],
        [0x0C, 0x00],
        [0x10, 0x06],
        [0x1C, 0x00],
    ]


@pytest.mark.parametrize(
    ("part", "bad_code"),
    [(MCP4231, 128), (MCP4241, 128), (MCP4251, 256), (MCP4261, 256)],
)
def test_out_of_range_code_never_reaches_the_bus(part: type, bad_code: int) -> None:
    """The code is validated before the first write transaction."""
    dac, transport = build(part)
    transport.calls.clear()
    with pytest.raises(DACCodeError):
        dac.channel(0).value = bad_code
    assert transport.calls == []


def test_write_all_validates_the_whole_sequence_first() -> None:
    """One bad element leaves both channels untouched."""
    dac, transport = build()
    transport.calls.clear()
    with pytest.raises(DACCodeError):
        dac.write_all([5, 256])
    assert transport.calls == []


def test_fractional_code_never_reaches_the_bus() -> None:
    """A fractional code is a value error raised before the write."""
    dac, transport = build()
    transport.calls.clear()
    with pytest.raises(ValueError) as excinfo:
        dac.channel(0).value = 1.5
    assert not isinstance(excinfo.value, DACCodeError)
    assert transport.calls == []


def test_grounded_a_mirrors_the_output_onto_the_code() -> None:
    """Grounding A swaps the endpoints; the raw code keeps its own frame."""
    dac, transport = build(grounded="A", reference=REFERENCE)
    transport.calls.clear()
    channel = dac.channel(0)
    channel.output = REFERENCE
    assert transport.calls[0] == [0x00, 0x00]
    channel.output = 0.0
    assert transport.calls[2] == [0x00, 0xFF]


def test_grounded_b_maps_the_reference_onto_the_top_code() -> None:
    """Grounding B, the default, writes the top code for full scale."""
    dac, transport = build(reference=REFERENCE)
    transport.calls.clear()
    dac.channel(0).output = REFERENCE
    assert transport.calls[0] == [0x00, 0xFF]


def test_voltage_alias_writes_the_same_code() -> None:
    """`voltage` is an alias of `output` and reaches the same frame."""
    dac, transport = build(reference=REFERENCE)
    transport.calls.clear()
    dac.channel(0).voltage = REFERENCE
    assert transport.calls[0] == [0x00, 0xFF]


def test_grounding_a_does_not_invert_the_raw_code() -> None:
    """The DAC layer mirrors the output; the wrapped wiper stays uninverted."""
    dac, transport = build(grounded="A")
    transport.calls.clear()
    dac.channel(0).value = 5
    assert transport.calls[0] == [0x00, 0x05]


@pytest.mark.parametrize("part", PARTS_7_BIT + PARTS_8_BIT)
def test_wrapped_wipers_are_never_inverted(part: type) -> None:
    """Every chip forces `invert=False` on its wrapped wipers."""
    dac, _ = build(part)
    assert all(not wiper.invert for wiper in dac.device.channels.values())
