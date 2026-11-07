"""Constructor wiring of the MCP4xxx DAC wrappers."""

import sys
import types
from unittest import mock

import pytest
import scietex.hal.spi.spidev_spi as spidev_spi
from conftest import RecordingTransport, build, fake, wiper_frame

from scietex.hal.dac import MCP4251

GPIOZERO_BACKEND = "scietex.hal.spi.gpiozero_spi"


class _RecordingGpiozeroTransport:
    """Stand-in for GpiozeroSpiTransport that records its keywords."""

    instances: list["_RecordingGpiozeroTransport"] = []

    def __init__(self, **spi_args: object) -> None:
        self.spi_args = spi_args
        self.closed = False
        _RecordingGpiozeroTransport.instances.append(self)

    def transfer(self, tx: list[int]) -> list[int]:
        """Answer with a zero-code wiper frame of the request length."""
        return wiper_frame(0)

    def close(self) -> None:
        """Mark the stand-in closed."""
        self.closed = True


def _fake_gpiozero_module() -> types.ModuleType:
    """Build a stand-in for the gpiozero backend module."""
    module = types.ModuleType(GPIOZERO_BACKEND)
    module.GpiozeroSpiTransport = _RecordingGpiozeroTransport
    return module


def test_r_ab_reaches_the_wrapped_model() -> None:
    """The resistance is forwarded to the potentiometer model."""
    dac, _ = build(r_ab=50e3)
    assert dac.device.channels[0].potentiometer.r_ab == 50e3


def test_unsupported_r_ab_is_rejected() -> None:
    """Only the resistances the part is offered in are accepted."""
    with pytest.raises(ValueError):
        MCP4251(r_ab=1234, transport=fake())


def test_channels_one_builds_a_single_dac_channel() -> None:
    """A one-channel part exposes channel 0 only."""
    dac, _ = build(channels=1)
    assert len(dac.channels) == 1
    assert dac.channels[0].index == 0
    with pytest.raises(IndexError):
        dac.channel(1)


def test_channels_one_consumes_three_construction_reads() -> None:
    """The wrapped part still reads channel 0 three times while it is built."""
    _, transport = build(channels=1)
    assert transport.calls == [[0x0C, 0x00], [0x0C, 0x00], [0x0C, 0x00]]


def test_transport_is_forwarded_to_the_part() -> None:
    """An injected transport is the one the part talks over."""
    transport = fake()
    dac = MCP4251(transport=transport)
    assert dac.transport is transport
    assert dac.device.transport is transport


def test_spi_is_an_alias_for_transport() -> None:
    """The legacy `spi` keyword reaches the same transport slot."""
    transport = fake()
    dac = MCP4251(spi=transport)
    assert dac.transport is transport


def test_port_and_device_select_the_spidev_bus() -> None:
    """port maps to the spidev bus number, device to the chip select."""
    with mock.patch.object(spidev_spi, "SpiDevTransport") as constructor:
        constructor.return_value.transfer.return_value = wiper_frame(0)
        dac = MCP4251(port=1, device=2)
    constructor.assert_called_once_with(bus=1, device=2)
    assert dac.transport is constructor.return_value


def test_pin_keywords_select_the_gpiozero_transport() -> None:
    """Any pin keyword switches the constructor to the gpiozero backend."""
    _RecordingGpiozeroTransport.instances = []
    with mock.patch.dict(sys.modules, {GPIOZERO_BACKEND: _fake_gpiozero_module()}):
        dac = MCP4251(clock_pin=11, mosi_pin=10, miso_pin=9, select_pin=8)
    transport = _RecordingGpiozeroTransport.instances[0]
    assert dac.transport is transport
    assert transport.spi_args == {
        "clock_pin": 11,
        "mosi_pin": 10,
        "miso_pin": 9,
        "select_pin": 8,
    }


def test_grounded_a_is_accepted() -> None:
    """Grounding A is valid and reaches every channel."""
    dac, _ = build(grounded="A")
    assert dac.grounded == "A"
    assert all(channel.grounded == "A" for channel in dac.channels)


@pytest.mark.parametrize("grounded", ["a", "C", ""])
def test_unknown_grounded_terminal_is_rejected(grounded: str) -> None:
    """Only the exact terminal names are accepted, with no case folding."""
    transport = fake()
    with pytest.raises(ValueError):
        MCP4251(transport=transport, grounded=grounded)
    assert transport.calls == []


def test_non_string_grounded_terminal_is_rejected() -> None:
    """A number is a type error, not an unknown terminal name."""
    transport = fake()
    with pytest.raises(TypeError):
        MCP4251(transport=transport, grounded=1)  # type: ignore[arg-type]
    assert transport.calls == []


def test_reference_is_validated_before_the_bus_opens() -> None:
    """A bad reference never reaches the transport constructor."""
    with (
        mock.patch.object(spidev_spi, "SpiDevTransport") as constructor,
        pytest.raises(ValueError),
    ):
        MCP4251(reference=0)
    constructor.assert_not_called()


@pytest.mark.parametrize("keyword", [{"invert": True}, {"max_value": 256}])
def test_hidden_pot_keywords_are_rejected(keyword: dict[str, object]) -> None:
    """`invert` and `max_value` are not part of the DAC constructor."""
    with pytest.raises(TypeError):
        MCP4251(transport=fake(), **keyword)


def test_an_empty_label_closes_the_part_it_built() -> None:
    """The DAC layer releases the wrapped part when it rejects the label."""
    transport = RecordingTransport(default=wiper_frame(0))
    with pytest.raises(ValueError):
        MCP4251(transport=transport, label="")
    assert transport.close_calls == 1
    assert transport.closed is True


def test_the_wrapped_part_keeps_its_default_logger() -> None:
    """The DAC label never leaks into the wrapped part's logger."""
    dac, _ = build()
    assert dac.device.logger.name == "DigiPot"
