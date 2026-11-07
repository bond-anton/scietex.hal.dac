"""MCP49xx converters: frame encoding, reference forms, and writes."""

from typing import Any, NamedTuple

import pytest
from conftest import RecordingTransport

import scietex.hal.dac.mcp49xx as mcp49xx_module
from scietex.hal.dac import MCP4902, MCP4912, MCP4922
from scietex.hal.dac.channel import BufferedChannel, GainChannel, PowerDownChannel
from scietex.hal.dac.mcp49xx import MCP49xxChannel, encode_write


class FrameRow(NamedTuple):
    """One documented frame: the part, its channel setup, and the two bytes."""

    part: Any
    index: int
    buffered: bool
    gain: int
    code: int
    frame: list[int]


# Row 1 of the task table read [0x6A, 0xBC], which clears SHDN while the row is
# labelled "active". The part, like the MCP48xx family, powers down when SHDN is
# clear, and the other two rows only reproduce their bytes with SHDN set, so the
# frame is 0x7ABC.
FRAME_ROWS = [
    FrameRow(MCP4922, 0, True, 1, 0xABC, [0x7A, 0xBC]),
    FrameRow(MCP4912, 1, False, 2, 0x2BC, [0x9A, 0xF0]),
    FrameRow(MCP4902, 1, True, 2, 0xA5, [0xDA, 0x50]),
]
FRAME_IDS = [
    "mcp4922-ch0-buffered-gain1-active",
    "mcp4912-ch1-unbuffered-gain2-active",
    "mcp4902-ch1-buffered-gain2-active",
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


def test_the_channel_carries_the_buffer_gain_and_power_down_fields() -> None:
    """The part exposes the shared voltage-channel building blocks."""
    dac, _ = built(MCP4922)
    channel = dac.channel(0)
    assert isinstance(channel, MCP49xxChannel)
    assert isinstance(channel, BufferedChannel)
    assert isinstance(channel, GainChannel)
    assert isinstance(channel, PowerDownChannel)
    assert channel.buffered is False
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
            buffered=row.buffered,
            gain=row.gain,
            power_down=0,
        )
        == row.frame
    )


@pytest.mark.parametrize("row", FRAME_ROWS, ids=FRAME_IDS)
def test_a_code_write_sends_exactly_the_datasheet_frame(row: FrameRow) -> None:
    """The same rows reach the bus unchanged through the channel setter."""
    dac, transport = built(row.part, buffered=row.buffered, gain=row.gain, power_down=0)
    assert transport.requests == []
    dac.channel(row.index).value = row.code
    assert transport.requests == [row.frame]
    assert dac.channel(row.index).value == row.code


def test_a_scalar_reference_sets_the_device_full_scale() -> None:
    """One number is the VREF of the whole device, with no overrides."""
    dac, transport = built(MCP4922, reference=2.5)
    assert dac.reference == pytest.approx(2.5)
    assert [channel.reference_override for channel in dac.channels] == [None, None]
    assert transport.requests == []


def test_a_sequence_sets_per_channel_overrides() -> None:
    """One value per channel becomes an override and leaves the device unset."""
    dac, transport = built(MCP4922, reference=(2.5, 5.0))
    assert dac.reference is None
    assert [channel.reference_override for channel in dac.channels] == [
        pytest.approx(2.5),
        pytest.approx(5.0),
    ]
    assert transport.requests == []


def test_an_absent_reference_stays_absent() -> None:
    """An external-reference part will not guess a full scale."""
    dac, transport = built(MCP4922)
    assert dac.reference is None
    assert dac.channel(0).reference is None
    assert dac.channel(0).output is None
    assert transport.requests == []


def test_a_per_channel_override_beats_the_device_reference() -> None:
    """Channel 1 keeps its own VREF while channel 0 follows the device."""
    dac, _ = built(MCP4922, reference=2.5, gain=1)
    dac.channel(1).reference_override = 5.0
    assert dac.channel(0).reference == pytest.approx(2.5)
    assert dac.channel(1).reference == pytest.approx(5.0)


def test_gain_applies_per_channel_independently() -> None:
    """Each output scales its own reference by its own gain bit."""
    dac, _ = built(MCP4922, reference=(1.0, 2.0))
    assert dac.channel(0).reference == pytest.approx(2.0)
    assert dac.channel(1).reference == pytest.approx(4.0)
    dac.channel(0).gain = 1
    assert dac.channel(0).reference == pytest.approx(1.0)
    assert dac.channel(1).reference == pytest.approx(4.0)


@pytest.mark.parametrize(("buffered", "bit"), [(True, 0x4000), (False, 0x0000)])
def test_the_buffer_bit_sits_below_the_channel_bit(buffered: bool, bit: int) -> None:
    """BUF is bit 14 and nothing else moves when it flips."""
    word = word_of(encode_write(12, 1, 0xABC, buffered=buffered, gain=1, power_down=0))
    assert word & 0x4000 == bit
    assert word == 0x8000 | bit | 0x2000 | 0x1000 | 0xABC


def test_a_sequence_of_the_wrong_length_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three values cannot describe two channels, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp49xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        MCP4922(reference=(2.5, 5.0, 3.3))
    assert opened == []


def test_a_sequence_element_of_the_wrong_type_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A string is not a VREF, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp49xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(TypeError):
        MCP4922(reference=("2.5", 5.0))
    assert opened == []


def test_a_sequence_longer_than_the_channel_count_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The length is checked against the channels the caller asked for."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(mcp49xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        MCP4922(channels=1, reference=(2.5, 5.0))
    assert opened == []


@pytest.mark.parametrize("part", [MCP4902, MCP4912, MCP4922])
def test_construction_issues_no_transfers(part: Any) -> None:
    """Building the channels never touches the bus."""
    dac, transport = built(
        part, channels=1, reference=2.5, buffered=True, gain=1, power_down=1
    )
    assert transport.requests == []
    assert dac.readable is False
    assert dac.channel(0).readable is False


def test_fields_are_applied_to_every_channel() -> None:
    """The constructor-wide buffer, gain, and power-down reach both outputs."""
    dac, _ = built(MCP4922, buffered=True, gain=1, power_down=1)
    assert [channel.buffered for channel in dac.channels] == [True, True]
    assert [channel.gain for channel in dac.channels] == [1, 1]
    assert [channel.power_down for channel in dac.channels] == [1, 1]


def test_write_all_writes_in_index_order() -> None:
    """Each code becomes one frame, channel 0 first."""
    dac, transport = built(MCP4922, gain=1)
    assert dac.write_all([0xABC, 0xFFF]) == (0xABC, 0xFFF)
    assert transport.requests == [[0x3A, 0xBC], [0xBF, 0xFF]]


def test_an_empty_label_closes_the_transport_it_opened() -> None:
    """The DAC layer rejects the label after the bus exists; release it."""
    transport = RecordingTransport()
    with pytest.raises(ValueError):
        MCP4922(transport=transport, label="")
    assert transport.close_calls == 1


def test_one_channel_part_keeps_a_single_reference() -> None:
    """`channels=1` accepts a one-item sequence and builds one channel."""
    dac, transport = built(MCP4922, channels=1, reference=(2.5,))
    assert len(dac.channels) == 1
    assert dac.channel(0).reference_override == pytest.approx(2.5)
    dac.channel(0).value = 0xABC
    assert transport.requests == [[0x1A, 0xBC]]
