"""Reference handling of a device and its channels."""

import pytest
from conftest import RecordingTransport

from scietex.hal.dac import DAC, DACReferenceError, VoltageChannel


class BusChannel(VoltageChannel):
    """Voltage channel that moves one word over the device transport per access."""

    def _read_code(self) -> int:
        return self._dac.transport.transfer([self.index])[0]

    def _write_code(self, code: int) -> int:
        self._dac.transport.transfer([self.index, code])
        return code


class BusDAC(DAC):
    """Two 8-bit voltage channels on a recording transport."""

    _CHANNELS = 2
    _RESOLUTION = 8
    _CHANNEL_CLASS = BusChannel


def make_dac(**kwargs: object) -> tuple[BusDAC, RecordingTransport]:
    """Build a `BusDAC` whose reads answer with code 64."""
    transport = RecordingTransport(default=[64])
    return BusDAC(backend=transport, **kwargs), transport


def test_device_reference_scales_every_channel() -> None:
    """The device reference is the default full scale of all channels."""
    dac, _ = make_dac(reference=5.0)
    assert dac.channel(0).output == pytest.approx(64 / 255 * 5.0)
    assert dac.channel(1).output == pytest.approx(64 / 255 * 5.0)


def test_channel_override_wins_over_the_device_reference() -> None:
    """The override applies to one channel only."""
    dac, _ = make_dac(reference=5.0)
    channel = dac.channel(0)
    channel.reference_override = 3.3
    assert channel.reference == 3.3
    assert channel.output == pytest.approx(64 / 255 * 3.3)
    assert dac.channel(1).output == pytest.approx(64 / 255 * 5.0)


def test_clearing_the_override_restores_the_device_reference() -> None:
    """None clears the override instead of setting a zero scale."""
    dac, _ = make_dac(reference=5.0)
    channel = dac.channel(0)
    channel.reference_override = 3.3
    channel.reference_override = None
    assert channel.reference == 5.0
    assert channel.output == pytest.approx(64 / 255 * 5.0)


def test_setting_the_device_reference_later_starts_scaling() -> None:
    """A reference assigned after construction reaches the existing channels."""
    dac, _ = make_dac()
    channel = dac.channel(0)
    assert channel.output is None
    dac.reference = 2.5
    assert channel.output == pytest.approx(64 / 255 * 2.5)


def test_no_reference_anywhere_leaves_the_output_unset() -> None:
    """Without a reference the channel refuses to guess a full scale."""
    dac, _ = make_dac()
    channel = dac.channel(0)
    assert dac.reference is None
    assert channel.reference is None
    assert channel.output is None


def test_setting_the_output_without_a_reference_raises() -> None:
    """The reference error is a ValueError, so callers can catch it broadly."""
    dac, _ = make_dac()
    with pytest.raises(DACReferenceError) as excinfo:
        dac.channel(0).output = 1.0
    assert isinstance(excinfo.value, ValueError)


def test_an_unset_reference_causes_no_bus_traffic() -> None:
    """Neither the read nor the rejected write touches the transport."""
    dac, transport = make_dac()
    channel = dac.channel(0)
    before = len(transport.requests)
    assert channel.output is None
    with pytest.raises(DACReferenceError):
        channel.output = 1.0
    assert len(transport.requests) == before


@pytest.mark.parametrize("reference", [0, -1, float("nan"), float("inf")])
def test_invalid_device_reference_is_rejected(reference: float) -> None:
    """A reference must be positive and finite."""
    with pytest.raises(ValueError):
        make_dac(reference=reference)


@pytest.mark.parametrize("reference", [0, -1, float("nan"), float("inf")])
def test_invalid_channel_override_is_rejected(reference: float) -> None:
    """The channel override is validated like the device reference."""
    dac, _ = make_dac(reference=5.0)
    with pytest.raises(ValueError):
        dac.channel(0).reference_override = reference


@pytest.mark.parametrize("reference", ["3.3", True])
def test_device_reference_type_errors(reference: object) -> None:
    """A string or a bool is a caller mistake, not a reference."""
    with pytest.raises(TypeError):
        make_dac(reference=reference)


@pytest.mark.parametrize("reference", ["3.3", True])
def test_channel_override_type_errors(reference: object) -> None:
    """The channel override rejects the same types."""
    dac, _ = make_dac(reference=5.0)
    with pytest.raises(TypeError):
        dac.channel(0).reference_override = reference
