"""DAC121S101: frame encoding, power-down table, and writes."""

from typing import Any

import pytest
from conftest import RecordingTransport

import scietex.hal.dac.dac121s101 as dac121s101_module
from scietex.hal.dac import DAC121S101, DACCodeError, DACReferenceError
from scietex.hal.dac.channel import PowerDownChannel, VoltageChannel
from scietex.hal.dac.dac121s101 import DAC121S101Channel, encode_write

FRAME_ROWS = [
    pytest.param(0, 0xABC, [0x0A, 0xBC], id="normal"),
    pytest.param(3, 0xABC, [0x3A, 0xBC], id="high-impedance"),
]


def built(**kwargs: Any) -> tuple[Any, RecordingTransport]:
    """Build a DAC121S101 on a recording bus and return it with its bus."""
    transport = RecordingTransport()
    return DAC121S101(transport=transport, **kwargs), transport


def word_of(frame: list[int]) -> int:
    """Join a two-byte frame into the word it encodes."""
    return (frame[0] << 8) | frame[1]


def refusing_opener(opened: list[dict[str, Any]]) -> Any:
    """Build a transport factory that records its call and then fails."""

    def opener(**kwargs: Any) -> Any:
        opened.append(kwargs)
        raise AssertionError("the transport must not be built")

    return opener


def test_the_channel_carries_the_power_down_field() -> None:
    """The part exposes the shared voltage-channel building blocks."""
    dac, _ = built()
    channel = dac.channel(0)
    assert isinstance(channel, DAC121S101Channel)
    assert isinstance(channel, PowerDownChannel)
    assert isinstance(channel, VoltageChannel)
    assert channel.power_down == 0


@pytest.mark.parametrize(("power_down", "code", "frame"), FRAME_ROWS)
def test_encode_write_matches_the_datasheet_frame(
    power_down: int, code: int, frame: list[int]
) -> None:
    """Every documented row encodes to its exact two bytes."""
    assert encode_write(code, power_down=power_down) == frame


@pytest.mark.parametrize(("power_down", "code", "frame"), FRAME_ROWS)
def test_a_code_write_sends_exactly_the_datasheet_frame(
    power_down: int, code: int, frame: list[int]
) -> None:
    """The same rows reach the bus unchanged through the channel setter."""
    dac, transport = built(power_down=power_down)
    assert transport.requests == []
    dac.channel(0).value = code
    assert transport.requests == [frame]
    assert dac.channel(0).value == code


@pytest.mark.parametrize("power_down", range(4))
def test_the_power_down_field_sits_above_the_twelve_bit_code(
    power_down: int,
) -> None:
    """The word is two don't-care bits, PD1..PD0, then the 12-bit code."""
    frame = encode_write(0xABC, power_down=power_down)
    assert len(frame) == 2
    assert word_of(frame) == (power_down << 12) | 0xABC
    assert word_of(frame) & 0x0FFF == 0xABC


def test_a_half_scale_output_writes_the_midpoint() -> None:
    """Half of a 3.3 V rail is code 2048 on a 12-bit part."""
    dac, transport = built(reference=3.3)
    dac.channel(0).output = 1.65
    assert dac.channel(0).value == 2048
    assert transport.requests == [[0x08, 0x00]]


def test_a_code_wider_than_the_part_is_rejected() -> None:
    """A code beyond the 12-bit resolution never reaches the bus."""
    dac, transport = built()
    with pytest.raises(DACCodeError):
        dac.channel(0).value = 4096
    assert transport.requests == []


def test_an_absent_reference_leaves_the_output_unscaled() -> None:
    """The rail voltage is the full scale, and the library will not guess it."""
    dac, transport = built()
    assert dac.reference is None
    assert dac.channel(0).output is None
    with pytest.raises(DACReferenceError):
        dac.channel(0).output = 1.65
    assert transport.requests == []


def test_construction_issues_no_transfers() -> None:
    """Building the channel never touches the bus."""
    dac, transport = built(reference=3.3, power_down=2)
    assert transport.requests == []
    assert dac.readable is False
    assert dac.channel(0).readable is False
    assert dac.channel(0).power_down == 2


def test_a_wider_channel_count_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The part has a single channel."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac121s101_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        DAC121S101(channels=2)
    assert opened == []


def test_an_invalid_power_down_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two-bit field ends at 3, and the bus stays closed."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac121s101_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        DAC121S101(power_down=4)
    assert opened == []
