"""DAC85xx converters: frame encoding, power-down tables, and writes."""

from typing import Any, NamedTuple

import pytest
from conftest import RecordingTransport

import scietex.hal.dac.dac85xx as dac85xx_module
from scietex.hal.dac import DAC8531, DAC8551, DAC8552
from scietex.hal.dac.channel import PowerDownChannel, VoltageChannel
from scietex.hal.dac.dac85xx import (
    DAC85xxChannel,
    DAC8552Channel,
    encode_write,
    encode_write_8552,
)


class FrameRow(NamedTuple):
    """One documented frame: the part, its channel setup, and the three bytes."""

    part: Any
    index: int
    power_down: int
    code: int
    frame: list[int]


FRAME_ROWS = [
    FrameRow(DAC8531, 0, 0, 0xBEEF, [0x00, 0xBE, 0xEF]),
    FrameRow(DAC8551, 0, 1, 0xBEEF, [0x01, 0xBE, 0xEF]),
    FrameRow(DAC8552, 0, 0, 0x1234, [0x10, 0x12, 0x34]),
    FrameRow(DAC8552, 1, 0, 0x1234, [0x24, 0x12, 0x34]),
    FrameRow(DAC8552, 1, 2, 0x0001, [0x26, 0x00, 0x01]),
]
FRAME_IDS = [
    "dac8531-ch0-normal",
    "dac8551-ch0-power-down-1",
    "dac8552-ch0-normal",
    "dac8552-ch1-normal",
    "dac8552-ch1-power-down-2",
]


def built(part: Any, **kwargs: Any) -> tuple[Any, RecordingTransport]:
    """Build `part` on a recording bus and return the device with its bus."""
    transport = RecordingTransport()
    return part(transport=transport, **kwargs), transport


def frame_of(row: FrameRow) -> list[int]:
    """Encode a documented row with the part's own encoder."""
    if row.part._CHANNELS == 1:
        return encode_write(row.code, power_down=row.power_down)
    return encode_write_8552(row.index, row.code, power_down=row.power_down)


def word_of(frame: list[int]) -> int:
    """Join a frame into the word it encodes, most significant byte first."""
    word = 0
    for byte in frame:
        word = (word << 8) | byte
    return word


def refusing_opener(opened: list[dict[str, Any]]) -> Any:
    """Build a transport factory that records its call and then fails."""

    def opener(**kwargs: Any) -> Any:
        opened.append(kwargs)
        raise AssertionError("the transport must not be built")

    return opener


def test_the_channel_carries_the_power_down_field() -> None:
    """The part exposes the shared voltage-channel building blocks."""
    dac, _ = built(DAC8531)
    channel = dac.channel(0)
    assert isinstance(channel, DAC85xxChannel)
    assert isinstance(channel, PowerDownChannel)
    assert isinstance(channel, VoltageChannel)
    assert channel.power_down == 0


def test_the_dual_channel_class_has_no_reference_buffer_field() -> None:
    """DB18 selects the data buffer, so it must not surface as `buffered`."""
    dac, _ = built(DAC8552)
    assert len(dac.channels) == 2
    assert all(isinstance(channel, DAC8552Channel) for channel in dac.channels)
    assert not hasattr(dac.channel(0), "buffered")
    assert not hasattr(dac.channel(1), "buffered")


@pytest.mark.parametrize("row", FRAME_ROWS, ids=FRAME_IDS)
def test_encode_write_matches_the_datasheet_frame(row: FrameRow) -> None:
    """Every documented row encodes to its exact three bytes."""
    assert frame_of(row) == row.frame


@pytest.mark.parametrize("row", FRAME_ROWS, ids=FRAME_IDS)
def test_a_code_write_sends_exactly_the_datasheet_frame(row: FrameRow) -> None:
    """The same rows reach the bus unchanged through the channel setter."""
    dac, transport = built(row.part, power_down=row.power_down)
    assert transport.requests == []
    dac.channel(row.index).value = row.code
    assert transport.requests == [row.frame]
    assert dac.channel(row.index).value == row.code


@pytest.mark.parametrize("part", [DAC8531, DAC8551])
@pytest.mark.parametrize("power_down", range(4))
def test_the_power_down_field_sits_above_the_sixteen_bit_code(
    part: Any, power_down: int
) -> None:
    """A single-channel frame is six don't-care bits, PD1..PD0, then the code."""
    assert part._RESOLUTION == 16
    dac, transport = built(part, power_down=power_down)
    dac.channel(0).value = 0xABCD
    assert len(transport.requests) == 1
    frame = transport.requests[0]
    assert len(frame) == 3
    word = word_of(frame)
    assert word == (power_down << 16) | 0xABCD
    assert word & 0xFFFF == 0xABCD


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("power_down", range(4))
def test_the_dual_control_byte_carries_the_load_and_power_down_bits(
    index: int, power_down: int
) -> None:
    """LDA or LDB plus the buffer select, then PD1..PD0, then the code."""
    load = 0x10 if index == 0 else 0x24
    frame = encode_write_8552(index, 0xABCD, power_down=power_down)
    assert len(frame) == 3
    assert frame[0] == load | power_down
    assert word_of(frame) == ((load | power_down) << 16) | 0xABCD


def test_the_dual_part_uses_two_distinct_channel_control_bytes() -> None:
    """Channel A loads buffer A, channel B loads buffer B."""
    channel_a = encode_write_8552(0, 0, power_down=0)[0]
    channel_b = encode_write_8552(1, 0, power_down=0)[0]
    assert channel_a == 0x10
    assert channel_b == 0x24
    assert channel_a != channel_b


@pytest.mark.parametrize("power_down", range(4))
def test_dac8551_and_dac8531_share_the_wire_format(power_down: int) -> None:
    """The two single-channel parts differ only in documentation."""
    frames = []
    for part in (DAC8531, DAC8551):
        dac, transport = built(part, power_down=power_down)
        dac.channel(0).value = 0xBEEF
        frames.append(transport.requests)
    assert frames[0] == frames[1]
    assert frames[0] == [[power_down, 0xBE, 0xEF]]


def test_write_all_writes_channel_a_then_channel_b() -> None:
    """Each code becomes one frame, channel 0 first."""
    dac, transport = built(DAC8552)
    assert dac.write_all([0x1234, 0x5678]) == (0x1234, 0x5678)
    assert transport.requests == [[0x10, 0x12, 0x34], [0x24, 0x56, 0x78]]


def test_limiting_the_dual_part_to_one_channel_exposes_channel_a() -> None:
    """`channels=1` on the dual part builds a single channel, A."""
    dac, transport = built(DAC8552, channels=1)
    assert len(dac.channels) == 1
    assert dac.channel(0).index == 0
    dac.channel(0).value = 0x1234
    assert transport.requests == [[0x10, 0x12, 0x34]]


@pytest.mark.parametrize("part", [DAC8531, DAC8551])
def test_a_wider_channel_count_never_opens_the_bus(
    part: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-channel parts cannot be asked for a second channel."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac85xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        part(channels=2)
    assert opened == []


def test_an_invalid_power_down_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two-bit field ends at 3, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac85xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        DAC8531(power_down=4)
    assert opened == []


def test_a_scalar_reference_sets_the_device_full_scale() -> None:
    """One number is the VREF of the whole device, with no overrides."""
    dac, transport = built(DAC8552, reference=4.096)
    assert dac.reference == pytest.approx(4.096)
    assert [channel.reference_override for channel in dac.channels] == [None, None]
    assert transport.requests == []


def test_a_sequence_sets_per_channel_overrides_on_the_dual_part() -> None:
    """One value per channel becomes an override and leaves the device unset."""
    dac, transport = built(DAC8552, reference=(2.5, 5.0))
    assert dac.reference is None
    assert [channel.reference_override for channel in dac.channels] == [
        pytest.approx(2.5),
        pytest.approx(5.0),
    ]
    assert transport.requests == []


@pytest.mark.parametrize("part", [DAC8531, DAC8551])
def test_a_single_channel_part_rejects_a_reference_sequence(
    part: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the dual part has per-channel reference inputs, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac85xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(TypeError):
        part(reference=(2.5,))
    assert opened == []


def test_a_scaled_output_lands_on_the_expected_code() -> None:
    """Half of a 4.096 V span is code 32000, a hair under the 16-bit midpoint."""
    dac, transport = built(DAC8531, reference=4.096)
    dac.channel(0).output = 2.0
    assert dac.channel(0).value == 32000
    assert transport.requests == [[0x00, 0x7D, 0x00]]


@pytest.mark.parametrize("part", [DAC8531, DAC8551, DAC8552])
def test_construction_issues_no_transfers(part: Any) -> None:
    """Building the channels never touches the bus."""
    dac, transport = built(part, channels=1, reference=2.5, power_down=2)
    assert transport.requests == []
    assert dac.readable is False
    assert dac.channel(0).readable is False
    assert dac.channel(0).power_down == 2


def test_power_down_reaches_every_channel() -> None:
    """The constructor-wide power-down mode reaches both outputs."""
    dac, _ = built(DAC8552, power_down=2)
    assert [channel.power_down for channel in dac.channels] == [2, 2]
