"""Load strobe and strobed-backend tests."""

import sys
import types
from typing import Any

import pytest
from conftest import FakeStrobe, RecordingTransport

import scietex.hal.dac.__strobe as strobe_module
from scietex.hal.dac.__strobe import GpiozeroStrobe, StrobedBackend


class FakeDigitalOutputDevice:
    """Minimal gpiozero digital output that records its driven states."""

    def __init__(self, pin: int, *, initial_value: bool | None = None) -> None:
        self.pin = pin
        self.states: list[bool] = []
        if initial_value is not None:
            self.states.append(bool(initial_value))
        self.close_calls = 0
        self.closed = False

    @property
    def value(self) -> bool | None:
        """Last driven state, or None before the first drive."""
        return self.states[-1] if self.states else None

    @value.setter
    def value(self, value: bool) -> None:
        self.states.append(bool(value))

    def on(self) -> None:
        """Drive the output high."""
        self.value = True

    def off(self) -> None:
        """Drive the output low."""
        self.value = False

    def close(self) -> None:
        """Count the release and mark the fake device closed."""
        self.close_calls += 1
        self.closed = True


def fake_gpiozero(monkeypatch: pytest.MonkeyPatch) -> list[FakeDigitalOutputDevice]:
    """Install a fake gpiozero module and return the devices it builds."""

    devices: list[FakeDigitalOutputDevice] = []

    def build(pin: int, *, initial_value: bool | None = None) -> Any:
        device = FakeDigitalOutputDevice(pin, initial_value=initial_value)
        devices.append(device)
        return device

    module = types.ModuleType("gpiozero")
    module.DigitalOutputDevice = build
    monkeypatch.setitem(sys.modules, "gpiozero", module)
    return devices


def backend() -> tuple[StrobedBackend, RecordingTransport, FakeStrobe, list[str]]:
    """Build a backend whose transport and strobe share one ordering log."""
    log: list[str] = []
    transport = RecordingTransport(log=log)
    strobe = FakeStrobe(log=log)
    return StrobedBackend(transport, strobe), transport, strobe, log


def test_the_backend_exposes_the_transport_and_its_handles() -> None:
    """The wrapper is transport-shaped and reports both owned objects."""
    wrapper, transport, strobe, _ = backend()
    assert wrapper.transport is transport
    assert wrapper.strobe is strobe
    assert wrapper.spi is transport
    assert wrapper.raw is None
    assert wrapper.closed is False


def test_spi_prefers_an_explicit_handle_over_the_raw_one() -> None:
    """A transport SPI handle wins, otherwise its raw handle is unwrapped."""
    wrapper, transport, _, _ = backend()
    handle = object()
    transport.spi = handle
    transport.raw = object()
    assert wrapper.spi is handle
    assert wrapper.raw is transport.raw


def test_transfer_delegates_and_does_not_pulse() -> None:
    """A transfer alone never latches: the device family pulses afterwards."""
    wrapper, transport, strobe, log = backend()
    assert wrapper.transfer([1, 2]) == []
    assert transport.requests == [[1, 2]]
    assert strobe.pulse_calls == []
    assert log == ["transfer"]


def test_close_releases_the_strobe_and_the_transport() -> None:
    """Both objects are closed, strobe first, and a second close is safe."""
    wrapper, transport, strobe, log = backend()
    wrapper.close()
    assert strobe.closed is True
    assert transport.closed is True
    assert wrapper.closed is True
    assert log == ["strobe-close", "transport-close"]
    wrapper.close()
    assert strobe.close_calls == 1
    assert transport.close_calls == 1


def test_a_failing_strobe_still_releases_the_transport() -> None:
    """The transport is closed even when the strobe's close raises."""
    wrapper, transport, strobe, _ = backend()
    strobe.raise_on_close = True
    with pytest.raises(RuntimeError, match="strobe close failed"):
        wrapper.close()
    assert transport.closed is True
    assert wrapper.closed is True


def test_the_pin_is_driven_high_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load line idles high before the first frame is clocked."""
    devices = fake_gpiozero(monkeypatch)
    strobe = GpiozeroStrobe(17)
    assert devices[0].pin == 17
    assert devices[0].value is True
    assert strobe.closed is False


def test_pulse_drives_low_then_high_for_the_configured_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One pulse is low, a sleep of `pulse_width`, then high."""
    devices = fake_gpiozero(monkeypatch)
    sleeps: list[float] = []
    monkeypatch.setattr(strobe_module.time, "sleep", sleeps.append)
    strobe = GpiozeroStrobe(17, pulse_width=2e-4)
    strobe.pulse()
    assert devices[0].states == [True, False, True]
    assert sleeps == [pytest.approx(2e-4)]


def test_close_releases_the_pin_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing releases the pin and repeated calls have no effect."""
    devices = fake_gpiozero(monkeypatch)
    strobe = GpiozeroStrobe(17)
    strobe.close()
    assert devices[0].closed is True
    assert strobe.closed is True
    strobe.close()
    assert devices[0].close_calls == 1


def test_a_missing_gpiozero_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy import reports the extra that provides gpiozero."""
    monkeypatch.setitem(sys.modules, "gpiozero", None)
    with pytest.raises(ImportError) as excinfo:
        GpiozeroStrobe(17)
    message = str(excinfo.value)
    assert "gpiozero" in message
    assert "scietex.hal.dac[gpiozero]" in message
