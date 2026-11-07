"""AD739x: frame encoding, external reference, and strobed writes."""

from collections.abc import Sequence
from typing import Any

import pytest
from conftest import FakeStrobe, RecordingTransport

import scietex.hal.dac.ad739x as ad739x_module
from scietex.hal.dac import (
    AD7390,
    AD7391,
    DACCodeError,
    DACReferenceError,
    DACStrobeError,
)
from scietex.hal.dac.ad739x import AD739xChannel, encode_write
from scietex.hal.dac.channel import VoltageChannel

FRAME_ROWS = [
    pytest.param(AD7390, 0xABC, [0x0A, 0xBC], id="ad7390-12-bit"),
    pytest.param(AD7391, 0x2BC, [0x02, 0xBC], id="ad7391-10-bit"),
]


def built(
    part: Any = AD7390, **kwargs: Any
) -> tuple[Any, RecordingTransport, FakeStrobe, list[str]]:
    """Build `part` on a recording bus and a fake strobe sharing one log."""
    log: list[str] = []
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = RecordingTransport(log=log)
    else:
        transport.log = log
    strobe = kwargs.pop("strobe", None)
    if strobe is None:
        strobe = FakeStrobe(log=log)
    else:
        strobe.log = log
    return part(transport=transport, strobe=strobe, **kwargs), transport, strobe, log


def refusing_opener(opened: list[dict[str, Any]]) -> Any:
    """Build a transport factory that records its call and then fails."""

    def opener(**kwargs: Any) -> Any:
        opened.append(kwargs)
        raise AssertionError("the transport must not be built")

    return opener


class FailingTransport:
    """Transport that records the attempt and then fails."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.closed = False

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Record the attempt and fail without answering."""
        self.log.append("transfer")
        raise RuntimeError("bus failure")

    def close(self) -> None:
        """Mark the transport closed."""
        self.closed = True


def test_the_channel_is_a_voltage_output() -> None:
    """Both parts expose one voltage channel."""
    dac, _, _, _ = built()
    channel = dac.channel(0)
    assert isinstance(channel, AD739xChannel)
    assert isinstance(channel, VoltageChannel)


@pytest.mark.parametrize(("part", "code", "frame"), FRAME_ROWS)
def test_encode_write_matches_the_datasheet_frame(
    part: Any, code: int, frame: list[int]
) -> None:
    """Extra leading bits are ignored and the frame stays byte aligned."""
    assert encode_write(part._RESOLUTION, code) == frame


@pytest.mark.parametrize(("part", "code", "frame"), FRAME_ROWS)
def test_a_code_write_sends_exactly_the_datasheet_frame(
    part: Any, code: int, frame: list[int]
) -> None:
    """The same frame reaches the bus through the channel setter."""
    dac, transport, _, _ = built(part)
    assert transport.requests == []
    dac.channel(0).value = code
    assert transport.requests == [frame]
    assert dac.channel(0).value == code


def test_the_ten_bit_part_rejects_a_wider_code() -> None:
    """AD7391 tops out at 1023 and a wider code never reaches the bus."""
    dac, transport, strobe, _ = built(AD7391)
    assert dac.max_code == 1023
    with pytest.raises(DACCodeError):
        dac.channel(0).value = 1024
    assert transport.requests == []
    assert strobe.pulse_calls == []


@pytest.mark.parametrize(("part", "code", "frame"), FRAME_ROWS)
def test_one_pulse_follows_the_transfer(part: Any, code: int, frame: list[int]) -> None:
    """A write is one transfer and then exactly one latch pulse."""
    dac, transport, strobe, log = built(part)
    dac.channel(0).value = code
    assert transport.requests == [frame]
    assert len(strobe.pulse_calls) == 1
    assert log == ["transfer", "pulse"]


def test_a_transport_error_skips_the_pulse() -> None:
    """A failed frame never reaches the load line."""
    transport = FailingTransport()
    strobe = FakeStrobe(log=transport.log)
    dac = AD7390(transport=transport, strobe=strobe)
    with pytest.raises(RuntimeError, match="bus failure"):
        dac.channel(0).value = 0xABC
    assert transport.log == ["transfer"]
    assert strobe.pulse_calls == []


def test_a_full_scale_output_writes_the_top_code() -> None:
    """2.5 V on a 2.5 V reference is exactly code 4095 on AD7390."""
    dac, transport, _, _ = built(AD7390, reference=2.5)
    dac.channel(0).output = 2.5
    assert dac.channel(0).value == 4095
    assert transport.requests == [[0x0F, 0xFF]]


def test_an_absent_reference_leaves_the_output_unset() -> None:
    """The parts have no reference of their own, so the library will not guess."""
    dac, transport, strobe, _ = built(AD7390)
    assert dac.reference is None
    assert dac.channel(0).output is None
    with pytest.raises(DACReferenceError):
        dac.channel(0).output = 1.0
    assert transport.requests == []
    assert strobe.pulse_calls == []


def test_a_missing_strobe_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strobed part rejects a device without a load line before the bus."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad739x_module, "open_transport", refusing_opener(opened))
    with pytest.raises(DACStrobeError):
        AD7390()
    assert opened == []


def test_both_strobe_and_load_pin_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller cannot name the load line twice."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad739x_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        AD7390(strobe=FakeStrobe(), load_pin=17)
    assert opened == []


@pytest.mark.parametrize("part", [AD7390, AD7391])
def test_construction_issues_no_transfers_or_pulses(part: Any) -> None:
    """Building the channel never touches the bus or the load line."""
    dac, transport, strobe, _ = built(part)
    assert transport.requests == []
    assert strobe.pulse_calls == []
    assert dac.readable is False
    assert dac.channel(0).readable is False
