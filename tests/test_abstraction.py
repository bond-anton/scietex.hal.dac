"""The abstraction is ready for a current-output device."""

import pytest
from conftest import MemoryBackend

from scietex.hal.dac import DAC, CurrentChannel, DACChannel, DACCodeError, DACUnit


class FakeCurrentChannel(CurrentChannel):
    """Current channel backed by the fake device's code list."""

    def _read_code(self) -> int:
        return self._dac.codes[self.index]

    def _write_code(self, code: int) -> int:
        self._dac.codes[self.index] = code
        return code


class FakeCurrentDAC(DAC):
    """Two 12-bit current channels backed by memory."""

    _CHANNELS = 2
    _RESOLUTION = 12
    _CHANNEL_CLASS = FakeCurrentChannel

    def __init__(
        self,
        *,
        backend: object | None = None,
        reference: float | None = None,
        channel_count: int | None = None,
    ) -> None:
        self.codes = [0] * self._CHANNELS
        super().__init__(
            backend=MemoryBackend() if backend is None else backend,
            reference=reference,
            channel_count=channel_count,
        )


class CallableClosedBackend:
    """Backend whose closed probe is a method."""

    def __init__(self, closed: bool) -> None:
        self._closed = closed

    def closed(self) -> bool:
        """Report the closed state."""
        return self._closed

    def close(self) -> None:
        """Mark the backend closed."""
        self._closed = True


class BrokenProbeBackend:
    """Backend whose closed probe raises."""

    @property
    def closed(self) -> bool:
        """Fail the probe on purpose."""
        raise RuntimeError("probe failed")

    def close(self) -> None:
        """Do nothing; the device flag has to carry the state."""


class TransportOwningBackend:
    """Backend that keeps the bus in a separate transport object."""

    def __init__(self) -> None:
        self.transport = MemoryBackend()

    def close(self) -> None:
        """Close the inner transport."""
        self.transport.close()


class FailingCloseBackend(MemoryBackend):
    """Backend whose close fails after releasing its resources."""

    def close(self) -> None:
        """Close, then raise as a stuck bus would."""
        super().close()
        raise RuntimeError("bus stuck")


def test_unit_is_current() -> None:
    """A current device advertises the unit on the class and the channel."""
    channel = FakeCurrentDAC().channel(0)
    assert FakeCurrentChannel.UNIT is DACUnit.CURRENT
    assert channel.unit is DACUnit.CURRENT


def test_unit_compares_and_prints_as_its_symbol() -> None:
    """Str-valued units behave like the bare symbol in logs and tables."""
    channel = FakeCurrentDAC().channel(0)
    assert channel.unit == "A"
    assert str(channel.unit) == "A"


def test_current_is_an_alias_of_output() -> None:
    """The unit-specific name reads and writes the canonical `output`."""
    dac = FakeCurrentDAC(reference=0.02)
    channel = dac.channel(0)
    channel.value = 2048
    assert channel.current == channel.output
    channel.current = 0.01
    assert channel.value == 2048


def test_current_channel_has_no_voltage_property() -> None:
    """The alias lives on the unit subclass, never on the shared base."""
    channel = FakeCurrentDAC().channel(0)
    assert not hasattr(channel, "voltage")


def test_full_scale_reaches_the_reference() -> None:
    """The top code maps exactly onto the reference."""
    dac = FakeCurrentDAC(reference=0.02)
    dac.channel(0).value = 4095
    assert dac.channel(0).output == 0.02


def test_mid_code_scales_by_the_code_fraction() -> None:
    """Output is the code fraction times the reference."""
    dac = FakeCurrentDAC(reference=0.02)
    dac.channel(0).value = 2048
    assert dac.channel(0).output == pytest.approx(2048 / 4095 * 0.02)


def test_output_round_trips_through_the_code() -> None:
    """A half-scale output lands on the middle code and reads back unchanged."""
    dac = FakeCurrentDAC(reference=0.02)
    channel = dac.channel(0)
    channel.output = 0.01
    assert channel.value == 2048
    assert dac.codes[0] == 2048


def test_reference_override_changes_only_that_channel() -> None:
    """A channel override wins over the device reference, others keep it."""
    dac = FakeCurrentDAC(reference=0.02)
    first, second = dac.channels
    first.reference_override = 0.004
    first.value = 4095
    second.value = 4095
    assert first.output == 0.004
    assert second.output == 0.02


def test_fake_overrides_only_the_codec() -> None:
    """Scaling stays in the shared base, so a fake implements two methods."""
    assert FakeCurrentChannel._code_to_fraction is DACChannel._code_to_fraction
    assert FakeCurrentChannel._fraction_to_code is DACChannel._fraction_to_code


def test_device_reference_has_a_v_ref_alias() -> None:
    """`v_ref` mirrors `reference` on the device as well."""
    dac = FakeCurrentDAC(reference=0.02)
    assert dac.v_ref == dac.reference == 0.02


def test_base_codec_hooks_are_not_implemented() -> None:
    """The base classes define the hooks but no frame format."""
    dac = FakeCurrentDAC()
    with pytest.raises(NotImplementedError):
        dac._read_code(0)
    with pytest.raises(NotImplementedError):
        dac._write_code(0, 0)
    channel = DACChannel(dac, 0)
    with pytest.raises(NotImplementedError):
        channel._read_code()
    with pytest.raises(NotImplementedError):
        channel._write_code(0)


def test_geometry_comes_from_the_class() -> None:
    """Resolution, full scale, and channel order follow the class geometry."""
    dac = FakeCurrentDAC()
    assert dac.resolution == 12
    assert dac.max_code == 4095
    assert len(dac.channels) == 2
    assert [channel.index for channel in dac.channels] == [0, 1]


def test_channel_count_selects_a_subset_of_the_geometry() -> None:
    """A smaller count builds fewer channels and nothing more."""
    dac = FakeCurrentDAC(channel_count=1)
    assert len(dac.channels) == 1
    with pytest.raises(IndexError):
        dac.channel(1)


@pytest.mark.parametrize("count", [0, 3, -1])
def test_channel_count_outside_the_geometry_is_rejected(count: int) -> None:
    """At least one channel and never more than the device has."""
    with pytest.raises(ValueError):
        FakeCurrentDAC(channel_count=count)


@pytest.mark.parametrize("index", [-1, 2])
def test_channel_index_outside_the_range_is_rejected(index: int) -> None:
    """Channel lookup is bounds-checked."""
    with pytest.raises(IndexError):
        FakeCurrentDAC().channel(index)


def test_read_all_returns_codes_in_index_order() -> None:
    """Every channel is read once, in order."""
    dac = FakeCurrentDAC(reference=0.02)
    dac.codes = [7, 42]
    assert dac.read_all() == (7, 42)


def test_write_all_writes_in_order_and_returns_the_codes() -> None:
    """The whole sequence is applied and echoed back."""
    dac = FakeCurrentDAC()
    assert dac.write_all([1, 2]) == (1, 2)
    assert dac.codes == [1, 2]


def test_write_all_rejects_a_wrong_length_before_writing() -> None:
    """A short sequence leaves the device untouched."""
    dac = FakeCurrentDAC()
    dac.codes = [9, 8]
    with pytest.raises(ValueError):
        dac.write_all([1])
    assert dac.codes == [9, 8]


def test_write_all_rejects_an_out_of_range_code_before_writing() -> None:
    """An invalid element cannot leave the device partially updated."""
    dac = FakeCurrentDAC()
    dac.codes = [9, 8]
    with pytest.raises(DACCodeError):
        dac.write_all([1, 5000])
    assert dac.codes == [9, 8]


def test_transport_falls_back_to_the_backend() -> None:
    """A transport-shaped backend is its own transport."""
    backend = MemoryBackend()
    assert FakeCurrentDAC(backend=backend).transport is backend


def test_transport_prefers_the_backend_transport() -> None:
    """A wrapping backend exposes the transport it owns."""
    backend = TransportOwningBackend()
    assert FakeCurrentDAC(backend=backend).transport is backend.transport


def test_spi_falls_back_to_the_backend() -> None:
    """No `spi` and no `raw` attribute means the backend is the handle."""
    backend = MemoryBackend()
    assert FakeCurrentDAC(backend=backend).spi is backend


def test_spi_prefers_the_backend_spi_handle() -> None:
    """An explicit `spi` handle wins over everything else."""
    handle = object()
    backend = MemoryBackend()
    backend.spi = handle
    assert FakeCurrentDAC(backend=backend).spi is handle


def test_spi_prefers_the_raw_attribute_over_the_backend() -> None:
    """A raw handle is unwrapped before falling back to the backend."""
    handle = object()
    backend = MemoryBackend()
    backend.raw = handle
    assert FakeCurrentDAC(backend=backend).spi is handle


def test_closed_follows_the_backend() -> None:
    """A backend flag is reported as the device state."""
    backend = MemoryBackend()
    dac = FakeCurrentDAC(backend=backend)
    assert dac.closed is False
    backend.closed = True
    assert dac.closed is True


def test_closed_calls_a_callable_probe() -> None:
    """A method probe is called rather than taken as a truthy attribute."""
    assert FakeCurrentDAC(backend=CallableClosedBackend(False)).closed is False
    assert FakeCurrentDAC(backend=CallableClosedBackend(True)).closed is True


def test_closed_swallows_a_broken_probe() -> None:
    """A failing probe counts as not closed and never leaks."""
    dac = FakeCurrentDAC(backend=BrokenProbeBackend())
    assert dac.closed is False
    dac.close()
    assert dac.closed is True


def test_close_closes_the_backend_and_flags_the_device() -> None:
    """Closing runs once and is idempotent in effect."""
    backend = MemoryBackend()
    dac = FakeCurrentDAC(backend=backend)
    dac.close()
    assert backend.close_calls == 1
    assert dac.closed is True


def test_close_flags_the_device_even_when_the_backend_raises() -> None:
    """A stuck bus still leaves the device unusable, as reported by `closed`."""
    backend = FailingCloseBackend()
    dac = FakeCurrentDAC(backend=backend)
    with pytest.raises(RuntimeError):
        dac.close()
    assert backend.close_calls == 1
    assert dac.closed is True


def test_context_manager_closes_the_backend() -> None:
    """Leaving the block closes the device."""
    backend = MemoryBackend()
    with FakeCurrentDAC(backend=backend) as dac:
        assert dac.closed is False
    assert backend.close_calls == 1
    assert dac.closed is True
