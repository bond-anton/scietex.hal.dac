"""MCP48xx converters: frame encoding, reference resolution, and writes."""

from typing import Any, NamedTuple

import pytest
from conftest import RecordingTransport

import scietex.hal.dac.mcp48xx as mcp48xx_module
from scietex.hal.dac import MCP4802, MCP4812, MCP4822, DACCodeError
from scietex.hal.dac.channel import GainChannel, PowerDownChannel, VoltageChannel
from scietex.hal.dac.mcp48xx import MCP48xxChannel, encode_write


class FrameRow(NamedTuple):
    """One documented frame: the part, its channel setup, and the two bytes."""

    part: Any
    index: int
    gain: int
    power_down: int
    code: int
    frame: list[int]


FRAME_ROWS = [
    FrameRow(MCP4822, 0, 2, 0, 0xABC, [0x1A, 0xBC]),
    FrameRow(MCP4822, 1, 1, 0, 0xFFF, [0xBF, 0xFF]),
    FrameRow(MCP4812, 0, 2, 0, 0x3FF, [0x1F, 0xFC]),
    FrameRow(MCP4802, 0, 1, 0, 0xA5, [0x3A, 0x50]),
    FrameRow(MCP4802, 0, 1, 1, 0xA5, [0x2A, 0x50]),
]
FRAME_IDS = [
    "mcp4822-ch0-gain2-active",
    "mcp4822-ch1-gain1-active",
    "mcp4812-ch0-gain2-active",
    "mcp4802-ch0-gain1-active",
    "mcp4802-ch0-gain1-shutdown",
]


def built(part: Any, **kwargs: Any) -> tuple[Any, RecordingTransport]:
    """Build `part` on a recording bus and return the device with its bus."""
    transport = RecordingTransport()
    return part(transport=transport, **kwargs), transport


def word_of(frame: list[int]) -> int:
    """Join a two-byte frame into the word it encodes."""
    return (frame[0] << 8) | frame[1]


def refusing_opener(opened: list[dict[str, Any]]) -> Any:
    """Build a transport factory that records its call and then fails."""

    def opener(**kwargs: Any) -> Any:
        opened.append(kwargs)
        raise AssertionError("the transport must not be built")

    return opener


def test_the_channel_carries_the_gain_and_power_down_fields() -> None:
    """The part exposes the shared voltage-channel building blocks."""
    dac, _ = built(MCP4822)
    channel = dac.channel(0)
    assert isinstance(channel, MCP48xxChannel)
    assert isinstance(channel, GainChannel)
    assert isinstance(channel, PowerDownChannel)
    assert isinstance(channel, VoltageChannel)
    assert channel.gain == 2
    assert channel.power_down == 0


@pytest.mark.parametrize("row", FRAME_ROWS, ids=FRAME_IDS)
def test_encode_write_matches_the_datasheet_frame(row: FrameRow) -> None:
    """Every documented row encodes to its exact two bytes."""
    assert (
        encode_write(
            row.part._RESOLUTION,
            row.index,
            row.code,
            gain=row.gain,
            power_down=row.power_down,
        )
        == row.frame
    )


@pytest.mark.parametrize("row", FRAME_ROWS, ids=FRAME_IDS)
def test_a_code_write_sends_exactly_the_datasheet_frame(row: FrameRow) -> None:
    """The same rows reach the bus unchanged through the channel setter."""
    dac, transport = built(row.part, gain=row.gain, power_down=row.power_down)
    assert transport.requests == []
    dac.channel(row.index).value = row.code
    assert transport.requests == [row.frame]
    assert dac.channel(row.index).value == row.code


@pytest.mark.parametrize(("part", "bits"), [(MCP4802, 8), (MCP4812, 10), (MCP4822, 12)])
def test_codes_are_left_aligned_in_the_twelve_bit_data_field(
    part: Any, bits: int
) -> None:
    """A narrower part keeps its code in the high bits of the field."""
    top_code = (1 << bits) - 1
    assert bits == part._RESOLUTION
    word = word_of(encode_write(bits, 0, top_code, gain=2, power_down=0))
    assert word & 0x0FFF == top_code << (12 - bits)


def test_an_eight_bit_code_leaves_the_low_nibble_zero() -> None:
    """The 8-bit part pads its four unused data bits with zeros."""
    frame = encode_write(8, 0, 0xA5, gain=2, power_down=0)
    assert frame == [0x1A, 0x50]
    assert frame[1] & 0x0F == 0


@pytest.mark.parametrize(("gain", "set_bit"), [(1, True), (2, False)])
def test_the_gain_bit_selects_one_times(gain: int, set_bit: bool) -> None:
    """GA is set for 1x and clear for the 2x power-on state."""
    word = word_of(encode_write(12, 0, 0, gain=gain, power_down=0))
    assert bool(word & 0x2000) is set_bit


@pytest.mark.parametrize(("power_down", "active"), [(0, True), (1, False)])
def test_the_shutdown_bit_inverts_the_power_down_mode(
    power_down: int, active: bool
) -> None:
    """SHDN is set while the channel is active and clear while it is down."""
    word = word_of(encode_write(12, 0, 0, gain=2, power_down=power_down))
    assert bool(word & 0x1000) is active


def test_power_down_above_one_is_rejected() -> None:
    """The part has a single SHDN bit, not a two-bit mode field."""
    dac, transport = built(MCP4822)
    with pytest.raises(ValueError):
        dac.channel(0).power_down = 2
    assert transport.requests == []


def test_the_internal_reference_fills_in_none() -> None:
    """A device with a fixed full scale reports it even when None was given."""
    dac, _ = built(MCP4822, reference=None)
    assert dac.reference == pytest.approx(2.048)
    assert dac.v_ref == pytest.approx(2.048)


def test_the_fixed_reference_is_accepted_explicitly() -> None:
    """Passing the constant itself is not a conflict."""
    dac, _ = built(MCP4822, reference=2.048)
    assert dac.reference == pytest.approx(2.048)


def test_gain_doubles_the_effective_reference() -> None:
    """The internal 2.048 V spans 4.096 V at the 2x power-on gain."""
    dac, _ = built(MCP4822)
    channel = dac.channel(0)
    assert channel.reference == pytest.approx(4.096)
    channel.gain = 1
    assert channel.reference == pytest.approx(2.048)


def test_a_conflicting_reference_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full scale the internal reference cannot meet is rejected up front."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp48xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        MCP4822(reference=3.3)
    assert opened == []


def test_a_non_positive_reference_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The type and positivity check runs before the transport is built too."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp48xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        MCP4822(reference=0)
    assert opened == []


def test_a_full_scale_output_reaches_the_top_code_through_the_gain() -> None:
    """4.096 V is full scale of a 2x channel and lands on 4095."""
    dac, transport = built(MCP4822)
    dac.channel(0).output = 4.096
    assert dac.channel(0).value == 4095
    assert transport.requests == [[0x1F, 0xFF]]


def test_a_full_scale_output_clamps_on_a_gain_one_channel() -> None:
    """At 1x the span is 2.048 V, so 4.096 V clamps instead of overflowing."""
    dac, transport = built(MCP4822, gain=1)
    channel = dac.channel(0)
    channel.output = 4.096
    assert channel.value == 4095
    assert channel.output == pytest.approx(2.048)
    assert len(transport.requests) == 1


@pytest.mark.parametrize("part", [MCP4802, MCP4812, MCP4822])
def test_construction_issues_no_transfers(part: Any) -> None:
    """Building the channels never touches the bus."""
    dac, transport = built(part, channels=1, gain=1, power_down=1)
    assert transport.requests == []
    assert dac.readable is False
    assert dac.channel(0).readable is False


def test_fields_are_applied_to_every_channel() -> None:
    """The constructor-wide gain and power-down reach both outputs."""
    dac, _ = built(MCP4822, gain=1, power_down=1)
    assert [channel.gain for channel in dac.channels] == [1, 1]
    assert [channel.power_down for channel in dac.channels] == [1, 1]


def test_write_all_writes_in_index_order() -> None:
    """Each code becomes one frame, channel 0 first."""
    dac, transport = built(MCP4822, gain=1)
    assert dac.write_all([0xABC, 0xFFF]) == (0xABC, 0xFFF)
    assert transport.requests == [[0x3A, 0xBC], [0xBF, 0xFF]]


@pytest.mark.parametrize(
    ("part", "code"), [(MCP4802, 256), (MCP4812, 1024), (MCP4822, 4096)]
)
def test_a_code_wider_than_the_part_is_rejected(part: Any, code: int) -> None:
    """A code beyond the resolution never reaches the bus."""
    dac, transport = built(part)
    with pytest.raises(DACCodeError):
        dac.channel(0).value = code
    assert transport.requests == []


def test_an_empty_label_closes_the_transport_it_opened() -> None:
    """The DAC layer rejects the label after the bus exists; release it."""
    transport = RecordingTransport()
    with pytest.raises(ValueError):
        MCP4822(transport=transport, label="")
    assert transport.close_calls == 1


def test_one_channel_part_exposes_a_single_index() -> None:
    """`channels=1` builds one channel whose frames keep A/B clear."""
    dac, transport = built(MCP4822, channels=1)
    assert len(dac.channels) == 1
    assert dac.channel(0).index == 0
    with pytest.raises(IndexError):
        dac.channel(1)
    dac.channel(0).value = 0xABC
    assert transport.requests == [[0x1A, 0xBC]]
