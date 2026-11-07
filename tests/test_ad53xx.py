"""AD53xx converters: frame encoding, reference forms, and writes."""

from typing import Any, NamedTuple

import pytest
from conftest import RecordingTransport

import scietex.hal.dac.ad53xx as ad53xx_module
from scietex.hal.dac import AD5302, AD5312, AD5322, DACCodeError
from scietex.hal.dac.ad53xx import AD53xxChannel, encode_write
from scietex.hal.dac.channel import BufferedChannel, PowerDownChannel, VoltageChannel


class FrameRow(NamedTuple):
    """One documented frame: the part, its channel setup, and the two bytes."""

    part: Any
    index: int
    buffered: bool
    power_down: int
    code: int
    frame: list[int]


# Row 4 of the task table read [0x40, 0x01], which drops the power-down field
# although the row asks for mode 3. BUF is bit 14 and PD1..PD0 are bits 13..12,
# so that row's word is 0x4000 | 0x3000 | 0x0001 = 0x7001.
FRAME_ROWS = [
    FrameRow(AD5322, 1, True, 0, 0xABC, [0xCA, 0xBC]),
    FrameRow(AD5312, 0, False, 0, 0x2BC, [0x0A, 0xF0]),
    FrameRow(AD5302, 0, False, 2, 0xA5, [0x2A, 0x50]),
    FrameRow(AD5322, 0, True, 3, 0x001, [0x70, 0x01]),
]
FRAME_IDS = [
    "ad5322-ch1-buffered-normal",
    "ad5312-ch0-unbuffered-normal",
    "ad5302-ch0-unbuffered-power-down-2",
    "ad5322-ch0-buffered-power-down-3",
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


def test_the_channel_carries_the_buffer_and_power_down_fields() -> None:
    """The part exposes the shared voltage-channel building blocks."""
    dac, _ = built(AD5322)
    channel = dac.channel(0)
    assert isinstance(channel, AD53xxChannel)
    assert isinstance(channel, BufferedChannel)
    assert isinstance(channel, PowerDownChannel)
    assert isinstance(channel, VoltageChannel)
    assert channel.buffered is False
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
            power_down=row.power_down,
        )
        == row.frame
    )


@pytest.mark.parametrize("row", FRAME_ROWS, ids=FRAME_IDS)
def test_a_code_write_sends_exactly_the_datasheet_frame(row: FrameRow) -> None:
    """The same rows reach the bus unchanged through the channel setter."""
    dac, transport = built(row.part, buffered=row.buffered, power_down=row.power_down)
    assert transport.requests == []
    dac.channel(row.index).value = row.code
    assert transport.requests == [row.frame]
    assert dac.channel(row.index).value == row.code


@pytest.mark.parametrize(
    ("part", "code", "word"),
    [
        pytest.param(AD5302, 0xFF, 0x0FF0, id="ad5302-8-bit"),
        pytest.param(AD5312, 0x3FF, 0x0FFC, id="ad5312-10-bit"),
        pytest.param(AD5322, 0xFFF, 0x0FFF, id="ad5322-12-bit"),
    ],
)
def test_a_full_code_fills_the_data_field_from_the_top(
    part: Any, code: int, word: int
) -> None:
    """A narrower code keeps its most significant bit at bit 11."""
    frame = encode_write(part._RESOLUTION, 0, code, buffered=False, power_down=0)
    assert word_of(frame) == word


def test_the_eight_bit_part_sends_a_zero_low_nibble() -> None:
    """The four bits below the 8-bit field are don't-care and sent as zero."""
    word = word_of(encode_write(8, 0, 0xA5, buffered=False, power_down=0))
    assert word & 0x000F == 0
    assert word == 0x0A50


@pytest.mark.parametrize(("buffered", "bit"), [(True, 0x4000), (False, 0x0000)])
def test_the_buffer_bit_sits_below_the_channel_bit(buffered: bool, bit: int) -> None:
    """BUF is bit 14 and nothing else moves when it flips."""
    word = word_of(encode_write(12, 1, 0xABC, buffered=buffered, power_down=0))
    assert word & 0x4000 == bit
    assert word == 0x8000 | bit | 0xABC


@pytest.mark.parametrize(
    ("power_down", "word"),
    [
        pytest.param(0, 0x0ABC, id="normal"),
        pytest.param(1, 0x1ABC, id="1k-to-gnd"),
        pytest.param(2, 0x2ABC, id="100k-to-gnd"),
        pytest.param(3, 0x3ABC, id="high-impedance"),
    ],
)
def test_the_power_down_field_sits_below_the_buffer_bit(
    power_down: int, word: int
) -> None:
    """PD1..PD0 occupy bits 13..12, directly above the 12-bit code."""
    frame = encode_write(12, 0, 0xABC, buffered=False, power_down=power_down)
    assert word_of(frame) == word


@pytest.mark.parametrize(
    ("power_down", "bits"), [(1, 0x1000), (2, 0x2000), (3, 0x3000)]
)
def test_the_two_power_down_bits_are_pd1_above_pd0(power_down: int, bits: int) -> None:
    """Mode 1 sets PD0, mode 2 sets PD1, and mode 3 sets both."""
    frame = encode_write(12, 0, 0xABC, buffered=False, power_down=power_down)
    assert word_of(frame) & 0x3000 == bits


def test_a_scalar_reference_sets_the_device_full_scale() -> None:
    """One number is the VREF of the whole device, with no overrides."""
    dac, transport = built(AD5322, reference=2.5)
    assert dac.reference == pytest.approx(2.5)
    assert [channel.reference_override for channel in dac.channels] == [None, None]
    assert transport.requests == []


def test_a_sequence_sets_per_channel_overrides() -> None:
    """One value per channel becomes an override and leaves the device unset."""
    dac, transport = built(AD5322, reference=(2.5, 5.0))
    assert dac.reference is None
    assert [channel.reference_override for channel in dac.channels] == [
        pytest.approx(2.5),
        pytest.approx(5.0),
    ]
    assert [channel.reference for channel in dac.channels] == [
        pytest.approx(2.5),
        pytest.approx(5.0),
    ]
    assert transport.requests == []


def test_an_absent_reference_stays_absent() -> None:
    """An external-reference part will not guess a full scale."""
    dac, transport = built(AD5312)
    assert dac.reference is None
    assert dac.channel(0).reference is None
    assert dac.channel(0).output is None
    assert transport.requests == []


def test_a_per_channel_override_beats_the_device_reference() -> None:
    """Channel 1 keeps its own VREF while channel 0 follows the device."""
    dac, _ = built(AD5322, reference=2.5)
    dac.channel(1).reference_override = 5.0
    assert dac.channel(0).reference == pytest.approx(2.5)
    assert dac.channel(1).reference == pytest.approx(5.0)


def test_the_buffer_bit_applies_per_channel() -> None:
    """Buffering channel A leaves channel B on its unbuffered default."""
    dac, transport = built(AD5322)
    dac.channel(0).buffered = True
    dac.channel(0).value = 0xABC
    dac.channel(1).value = 0xABC
    assert transport.requests == [[0x4A, 0xBC], [0x8A, 0xBC]]


def test_a_sequence_of_the_wrong_length_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three values cannot describe two channels, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad53xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        AD5322(reference=(2.5, 5.0, 1.0))
    assert opened == []


def test_a_sequence_element_of_the_wrong_type_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A string is not a VREF, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad53xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(TypeError):
        AD5322(reference=("2.5", 5.0))
    assert opened == []


def test_a_sequence_longer_than_the_channel_count_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The length is checked against the channels the caller asked for."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad53xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        AD5322(channels=1, reference=(2.5, 5.0))
    assert opened == []


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        pytest.param({"power_down": 4}, ValueError, id="power-down-out-of-range"),
        pytest.param({"buffered": "yes"}, TypeError, id="buffer-not-a-bool"),
    ],
)
def test_an_invalid_channel_field_never_opens_the_bus(
    kwargs: dict[str, Any], error: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every field is validated before the transport is built."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad53xx_module, "open_transport", refusing_opener(opened))
    with pytest.raises(error):
        AD5322(**kwargs)
    assert opened == []


@pytest.mark.parametrize(
    ("part", "code"),
    [
        pytest.param(AD5302, 0x100, id="ad5302-above-8-bit"),
        pytest.param(AD5312, 0x400, id="ad5312-above-10-bit"),
        pytest.param(AD5322, 0x1000, id="ad5322-above-12-bit"),
    ],
)
def test_a_code_wider_than_the_part_is_rejected(part: Any, code: int) -> None:
    """A code beyond the part's resolution never reaches the bus."""
    dac, transport = built(part)
    with pytest.raises(DACCodeError):
        dac.channel(1).value = code
    assert transport.requests == []


@pytest.mark.parametrize("part", [AD5302, AD5312, AD5322])
def test_construction_issues_no_transfers(part: Any) -> None:
    """Building the channels never touches the bus."""
    dac, transport = built(part, channels=1, reference=2.5, buffered=True, power_down=3)
    assert transport.requests == []
    assert dac.readable is False
    assert dac.channel(0).readable is False
    assert dac.channel(0).buffered is True
    assert dac.channel(0).power_down == 3


def test_fields_are_applied_to_every_channel() -> None:
    """The constructor-wide buffer and power-down reach both outputs."""
    dac, _ = built(AD5322, buffered=True, power_down=2)
    assert [channel.buffered for channel in dac.channels] == [True, True]
    assert [channel.power_down for channel in dac.channels] == [2, 2]


def test_write_all_writes_in_index_order() -> None:
    """Each code becomes one frame, channel 0 first."""
    dac, transport = built(AD5322)
    assert dac.write_all([0xABC, 0x123]) == (0xABC, 0x123)
    assert transport.requests == [[0x0A, 0xBC], [0x81, 0x23]]
    assert dac.read_all() == (0xABC, 0x123)
