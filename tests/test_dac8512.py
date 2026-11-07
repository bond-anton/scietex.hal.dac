"""DAC8512: frame encoding, fixed reference, and strobed writes."""

from collections.abc import Sequence
from typing import Any

import pytest
from conftest import FakeStrobe, RecordingTransport

import scietex.hal.dac.dac8512 as dac8512_module
from scietex.hal.dac import DAC8512, DACCodeError, DACStrobeError
from scietex.hal.dac.channel import VoltageChannel
from scietex.hal.dac.dac8512 import DAC8512Channel, encode_write

FIXED_REFERENCE = 4.095


def built(**kwargs: Any) -> tuple[DAC8512, RecordingTransport, FakeStrobe, list[str]]:
    """Build a DAC8512 on a recording bus and a fake strobe sharing one log."""
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
    return DAC8512(transport=transport, strobe=strobe, **kwargs), transport, strobe, log


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
    """The part exposes one voltage channel."""
    dac, _, _, _ = built()
    channel = dac.channel(0)
    assert isinstance(channel, DAC8512Channel)
    assert isinstance(channel, VoltageChannel)


def test_encode_write_matches_the_datasheet_frame() -> None:
    """The 12-bit code is the whole frame, most significant byte first."""
    assert encode_write(0xABC) == [0x0A, 0xBC]


def test_a_code_write_sends_exactly_the_datasheet_frame() -> None:
    """The same frame reaches the bus through the channel setter."""
    dac, transport, _, _ = built()
    assert transport.requests == []
    dac.channel(0).value = 0xABC
    assert transport.requests == [[0x0A, 0xBC]]
    assert dac.channel(0).value == 0xABC


def test_one_pulse_follows_the_transfer() -> None:
    """A write is one transfer and then exactly one latch pulse."""
    dac, transport, strobe, log = built()
    dac.channel(0).value = 0xABC
    assert transport.requests == [[0x0A, 0xBC]]
    assert len(strobe.pulse_calls) == 1
    assert log == ["transfer", "pulse"]


def test_a_transport_error_skips_the_pulse() -> None:
    """A failed frame never reaches the load line."""
    transport = FailingTransport()
    strobe = FakeStrobe(log=transport.log)
    dac = DAC8512(transport=transport, strobe=strobe)
    with pytest.raises(RuntimeError, match="bus failure"):
        dac.channel(0).value = 0xABC
    assert transport.log == ["transfer"]
    assert strobe.pulse_calls == []


def test_an_absent_reference_resolves_to_the_fixed_full_scale() -> None:
    """None selects the internal 4.095 V full scale."""
    dac, _, _, _ = built()
    assert dac.reference == pytest.approx(FIXED_REFERENCE)
    assert dac.channel(0).reference == pytest.approx(FIXED_REFERENCE)


def test_the_fixed_reference_is_accepted_explicitly() -> None:
    """Passing the constant is not a conflict."""
    dac, _, _, _ = built(reference=FIXED_REFERENCE)
    assert dac.reference == pytest.approx(FIXED_REFERENCE)


def test_another_reference_is_rejected_before_the_bus_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The internal reference is not adjustable, and no bus is opened."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac8512_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        DAC8512(reference=3.3, strobe=FakeStrobe())
    assert opened == []


def test_full_scale_output_writes_the_top_code() -> None:
    """4.095 V is exactly code 4095."""
    dac, transport, _, _ = built()
    dac.channel(0).output = FIXED_REFERENCE
    assert dac.channel(0).value == 4095
    assert transport.requests == [[0x0F, 0xFF]]


def test_one_millivolt_output_writes_code_one() -> None:
    """The fixed full scale gives exactly 1 mV per LSB."""
    dac, transport, _, _ = built()
    dac.channel(0).output = 0.001
    assert dac.channel(0).value == 1
    assert transport.requests == [[0x00, 0x01]]


def test_a_missing_strobe_never_opens_the_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strobed part rejects a device without a load line before the bus."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac8512_module, "open_transport", refusing_opener(opened))
    with pytest.raises(DACStrobeError):
        DAC8512()
    assert opened == []


def test_both_strobe_and_load_pin_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller cannot name the load line twice."""
    opened: list[dict[str, Any]] = []
    monkeypatch.setattr(dac8512_module, "open_transport", refusing_opener(opened))
    with pytest.raises(ValueError):
        DAC8512(strobe=FakeStrobe(), load_pin=17)
    assert opened == []


def test_load_pin_builds_a_gpiozero_strobe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin keyword is enough; the constructor owns the strobe it builds."""
    built_pins: list[int] = []

    class BuiltStrobe(FakeStrobe):
        def __init__(self, pin: int) -> None:
            super().__init__()
            built_pins.append(pin)

    monkeypatch.setattr(dac8512_module, "GpiozeroStrobe", BuiltStrobe)
    transport = RecordingTransport()
    dac = DAC8512(transport=transport, load_pin=17)
    dac.channel(0).value = 0xABC
    assert built_pins == [17]
    assert transport.requests == [[0x0A, 0xBC]]


def test_construction_issues_no_transfers_or_pulses() -> None:
    """Building the channel never touches the bus or the load line."""
    dac, transport, strobe, _ = built()
    assert transport.requests == []
    assert strobe.pulse_calls == []
    assert dac.readable is False
    assert dac.channel(0).readable is False


def test_a_code_wider_than_the_part_is_rejected() -> None:
    """A code beyond the 12-bit resolution never reaches the bus or strobe."""
    dac, transport, strobe, _ = built()
    with pytest.raises(DACCodeError):
        dac.channel(0).value = 4096
    assert transport.requests == []
    assert strobe.pulse_calls == []


def test_a_rejected_late_keyword_closes_the_strobe_and_the_transport() -> None:
    """A failure after the bus opens releases both resources."""
    transport = RecordingTransport()
    strobe = FakeStrobe()
    with pytest.raises(ValueError):
        DAC8512(transport=transport, strobe=strobe, label=" ")
    assert strobe.closed is True
    assert transport.closed is True


def test_a_failed_transport_open_releases_a_built_strobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strobe already driving its pin is released when the bus cannot open."""
    closed: list[bool] = []

    class BuiltStrobe(FakeStrobe):
        def __init__(self, pin: int) -> None:
            super().__init__()

        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr(dac8512_module, "GpiozeroStrobe", BuiltStrobe)
    monkeypatch.setattr(dac8512_module, "open_transport", refusing_opener([]))
    with pytest.raises(AssertionError):
        DAC8512(load_pin=17)
    assert closed == [True]
