"""AD420: declared ranges, 16-bit frame writes, and rising-edge latching."""

from collections.abc import Sequence
from typing import Any, NamedTuple

import pytest
from conftest import FakeRisingStrobe, RecordingTransport

import scietex.hal.dac.__transport as transport_module
import scietex.hal.dac.ad420 as ad420_module
from scietex.hal.dac import AD420, DACCodeError, DACReadbackError, DACStrobeError
from scietex.hal.dac.ad420 import (
    AD420CurrentChannel,
    AD420VoltageChannel,
    encode_write,
)
from scietex.hal.dac.channel import CurrentChannel, DACUnit, VoltageChannel


class Range(NamedTuple):
    """One selectable range and the channel the declaration produces."""

    name: str
    channel_class: type
    reference: float
    lower: float
    unit: DACUnit
    zero: float
    full: float


RANGES = [
    Range("0-5V", AD420VoltageChannel, 5.0, 0.0, DACUnit.VOLTAGE, 0.0, 5.0),
    Range("4-20mA", AD420CurrentChannel, 0.020, 0.004, DACUnit.CURRENT, 0.004, 0.020),
    Range("0-20mA", AD420CurrentChannel, 0.020, 0.0, DACUnit.CURRENT, 0.0, 0.020),
    Range("0-24mA", AD420CurrentChannel, 0.024, 0.0, DACUnit.CURRENT, 0.0, 0.024),
]


def built(
    **kwargs: Any,
) -> tuple[AD420, RecordingTransport, FakeRisingStrobe, list[str]]:
    """Build an AD420 on a recording bus and a fake strobe sharing one log."""
    log: list[str] = []
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = RecordingTransport(log=log)
    else:
        transport.log = log
    strobe = kwargs.pop("strobe", None)
    if strobe is None:
        strobe = FakeRisingStrobe(log=log)
    else:
        strobe.log = log
    return AD420(transport=transport, strobe=strobe, **kwargs), transport, strobe, log


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


@pytest.mark.parametrize("spec", RANGES, ids=lambda spec: spec.name)
def test_each_range_selects_the_channel_and_its_span(spec: Range) -> None:
    """The declared range picks the channel class, the span, and the unit."""
    dac, _, _, _ = built(range=spec.name)
    channel = dac.channel(0)
    assert isinstance(channel, spec.channel_class)
    assert dac.reference == pytest.approx(spec.reference)
    assert channel.reference == pytest.approx(spec.reference)
    assert channel.lower_bound == pytest.approx(spec.lower)
    assert channel.unit is spec.unit


@pytest.mark.parametrize("spec", RANGES, ids=lambda spec: spec.name)
def test_code_zero_reaches_the_floor_of_the_range(spec: Range) -> None:
    """Code 0 is the declared floor, aliased by the unit-specific accessor."""
    dac, transport, _, _ = built(range=spec.name)
    channel = dac.channel(0)
    assert channel.output == pytest.approx(spec.zero)
    if spec.unit is DACUnit.VOLTAGE:
        assert isinstance(channel, VoltageChannel)
        assert channel.voltage == pytest.approx(spec.zero)
        assert channel.v_ref == pytest.approx(spec.reference)
    else:
        assert isinstance(channel, CurrentChannel)
        assert channel.current == pytest.approx(spec.zero)
        assert channel.i_full_scale == pytest.approx(spec.reference)
    assert transport.requests == []


@pytest.mark.parametrize("spec", RANGES, ids=lambda spec: spec.name)
def test_the_top_code_reaches_the_reference(spec: Range) -> None:
    """The 16-bit top code maps to the declared full scale of the range."""
    dac, transport, _, _ = built(range=spec.name)
    dac.channel(0).value = dac.max_code
    assert dac.channel(0).output == pytest.approx(spec.full)
    assert transport.requests == [[0xFF, 0xFF]]


def test_twelve_milliamps_writes_the_midscale_code() -> None:
    """12 mA is exactly half of the 4-20 mA span, which is code 32768."""
    dac, transport, _, _ = built()
    dac.channel(0).output = 0.012
    assert dac.channel(0).value == 32768
    assert transport.requests == [[0x80, 0x00]]


@pytest.mark.parametrize(
    "code, frame",
    [
        (0x1234, [0x12, 0x34]),
        (0x0000, [0x00, 0x00]),
        (0xFFFF, [0xFF, 0xFF]),
    ],
)
def test_encode_write_matches_the_datasheet_frame(code: int, frame: list[int]) -> None:
    """The 16-bit code is the whole frame, most significant byte first."""
    assert encode_write(code) == frame


def test_a_code_write_sends_exactly_the_datasheet_frame() -> None:
    """The same frame reaches the bus through the channel setter."""
    dac, transport, _, _ = built()
    dac.channel(0).value = 0x1234
    assert transport.requests == [[0x12, 0x34]]
    assert dac.channel(0).value == 0x1234


def test_one_pulse_follows_the_transfer() -> None:
    """A write is one transfer and then exactly one latch pulse."""
    dac, transport, strobe, log = built()
    dac.channel(0).value = 0x1234
    assert transport.requests == [[0x12, 0x34]]
    assert len(strobe.pulse_calls) == 1
    assert log == ["transfer", "pulse"]


def test_a_transport_error_skips_the_pulse() -> None:
    """A failed frame never reaches the latch and leaves the shadow code."""
    transport = FailingTransport()
    strobe = FakeRisingStrobe(log=transport.log)
    dac = AD420(transport=transport, strobe=strobe)
    with pytest.raises(RuntimeError, match="bus failure"):
        dac.channel(0).value = 0x1234
    assert transport.log == ["transfer"]
    assert strobe.pulse_calls == []
    assert dac.channel(0).value == 0


def test_construction_issues_no_transfers_or_pulses() -> None:
    """Building the device never touches the bus or the latch line."""
    dac, transport, strobe, _ = built()
    assert transport.requests == []
    assert strobe.pulse_calls == []
    assert dac.readable is False
    assert dac.channel(0).readable is False


def test_the_part_is_sixteen_bits_wide() -> None:
    """The geometry matches the 16-bit frame the part latches."""
    dac, _, _, _ = built()
    assert dac.resolution == 16
    assert dac.max_code == 65535


def test_readback_is_refused_on_a_write_only_part() -> None:
    """DATA OUT is a daisy-chain pin, not a register readback path."""
    dac, _, _, _ = built()
    with pytest.raises(DACReadbackError):
        dac.channel(0).readback()


def test_an_unknown_range_is_rejected_before_the_bus_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo in the declared wiring never opens a transport."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad420_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        AD420(range="bogus", strobe=FakeRisingStrobe())
    assert opened == []


def test_a_non_string_range_is_a_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The range name is checked by type before its value."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad420_module, "open_transport", refusing_opener(opened))
    with pytest.raises(TypeError):
        AD420(range=123, strobe=FakeRisingStrobe())  # type: ignore[arg-type]
    assert opened == []


def test_a_missing_latch_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rising-edge latch is mandatory, so a bare device is rejected."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad420_module, "open_transport", refusing_opener(opened))
    with pytest.raises(DACStrobeError):
        AD420()
    assert opened == []


def test_both_strobe_and_latch_pin_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller cannot name the latch line twice."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(ad420_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        AD420(strobe=FakeRisingStrobe(), latch_pin=17)
    assert opened == []


def test_latch_pin_builds_a_rising_strobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin keyword builds the rising-edge strobe, not the falling one."""
    built_pins: list[int] = []

    class BuiltStrobe(FakeRisingStrobe):
        def __init__(self, pin: int) -> None:
            super().__init__()
            built_pins.append(pin)

    monkeypatch.setattr(ad420_module, "GpiozeroRisingStrobe", BuiltStrobe)
    transport = RecordingTransport()
    dac = AD420(transport=transport, latch_pin=17)
    dac.channel(0).value = 0x1234
    assert built_pins == [17]
    assert transport.requests == [[0x12, 0x34]]


def test_pin_keywords_delegate_to_the_gpiozero_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode 0 lets the pin keywords select the built-in GPIO backend."""
    calls: list[dict[str, Any]] = []
    transport = RecordingTransport()

    def build(**kwargs: Any) -> RecordingTransport:
        calls.append(kwargs)
        return transport

    monkeypatch.setattr(transport_module, "build_default_transport", build)
    dac = AD420(
        strobe=FakeRisingStrobe(),
        clock_pin=11,
        mosi_pin=10,
        miso_pin=9,
        select_pin=8,
    )
    assert AD420._SPI_MODE == 0
    assert calls == [
        {
            "port": None,
            "device": None,
            "clock_pin": 11,
            "mosi_pin": 10,
            "miso_pin": 9,
            "select_pin": 8,
        }
    ]
    dac.close()


def test_a_code_wider_than_the_part_is_rejected() -> None:
    """A code beyond 16 bits never reaches the bus or the latch."""
    dac, transport, strobe, _ = built()
    with pytest.raises(DACCodeError):
        dac.channel(0).value = 65536
    assert transport.requests == []
    assert strobe.pulse_calls == []


def test_a_rejected_late_keyword_closes_the_strobe_and_the_transport() -> None:
    """A failure after the bus opens releases both resources."""
    transport = RecordingTransport()
    strobe = FakeRisingStrobe()
    with pytest.raises(ValueError):
        AD420(transport=transport, strobe=strobe, label=" ")
    assert strobe.closed is True
    assert transport.closed is True
