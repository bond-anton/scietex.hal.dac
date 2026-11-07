"""Lifecycle of the MCP4xxx DAC wrappers."""

import pytest
from BDPotentiometer import DigitalPotentiometerDevice
from conftest import RecordingTransport, build, wiper_frame
from scietex.hal.spi import TransportClosed

from scietex.hal.dac import MCP4251


class FailingCloseTransport(RecordingTransport):
    """Transport whose `close()` reports a stuck bus after releasing it."""

    def close(self) -> None:
        """Close, then fail as a stuck bus would."""
        super().close()
        raise RuntimeError("bus stuck")


def test_close_closes_the_wrapped_transport() -> None:
    """Closing the device releases the bus the wrapped part owns."""
    dac, transport = build()
    dac.close()
    assert transport.closed is True
    assert dac.closed is True
    assert dac.device.closed is True


def test_an_open_device_reports_itself_open() -> None:
    """Nothing is closed before `close()` runs."""
    dac, transport = build()
    assert dac.closed is False
    assert transport.closed is False


def test_context_manager_closes_the_transport() -> None:
    """Leaving the block closes the device."""
    dac, transport = build()
    with dac as entered:
        assert entered is dac
        assert dac.closed is False
    assert transport.closed is True
    assert dac.closed is True


def test_context_manager_closes_after_an_exception() -> None:
    """An exception in the block still releases the bus."""
    dac, transport = build()
    with pytest.raises(RuntimeError), dac:
        raise RuntimeError("failed inside the block")
    assert transport.closed is True


def test_a_closed_device_rejects_a_read() -> None:
    """The transport refuses traffic once the device is closed."""
    dac, _ = build()
    dac.close()
    with pytest.raises(TransportClosed):
        _ = dac.channel(0).value


def test_a_closed_device_rejects_a_write() -> None:
    """A write reaches the same closed transport."""
    dac, _ = build()
    dac.close()
    with pytest.raises(TransportClosed):
        dac.channel(0).value = 5


def test_close_flags_the_device_when_the_transport_raises() -> None:
    """A stuck bus still leaves the device unusable, as reported by `closed`."""
    transport = FailingCloseTransport(default=wiper_frame(0))
    dac = MCP4251(transport=transport)
    with pytest.raises(RuntimeError):
        dac.close()
    assert transport.close_calls == 1
    assert dac.closed is True


def test_device_exposes_the_wrapped_part() -> None:
    """The escape hatch returns the `BDPotentiometer` device it composes."""
    dac, transport = build()
    assert isinstance(dac.device, DigitalPotentiometerDevice)
    assert not isinstance(dac, DigitalPotentiometerDevice)
    assert dac.device.transport is transport
    assert dac.device.closed is False


def test_transport_and_spi_accessors_reach_the_bus() -> None:
    """Both accessors return the transport the wrapped part talks over."""
    dac, transport = build()
    assert dac.transport is transport
    assert dac.spi is transport


def test_closing_the_wrapped_part_closes_the_device() -> None:
    """The DAC reports the backend state, so an independent close is visible."""
    dac, transport = build()
    dac.device.close()
    assert transport.closed is True
    assert dac.closed is True
