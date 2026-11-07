"""Write-only devices and devices with a fixed full scale."""

from collections.abc import Sequence

import pytest
from conftest import MemoryBackend, RecordingTransport

from scietex.hal.dac import DAC, DACError, DACReadbackError, VoltageChannel

FIXED_REFERENCE = 2.048


class BusChannel(VoltageChannel):
    """Channel that moves one frame over the device transport per access."""

    def _read_code(self) -> int:
        return self._dac.transport.transfer([self.index])[0]

    def _write_code(self, code: int) -> int:
        self._dac.transport.transfer([self.index, code])
        return code


class BusDAC(DAC):
    """Two 8-bit readable channels on a recording transport."""

    _CHANNELS = 2
    _RESOLUTION = 8
    _CHANNEL_CLASS = BusChannel


class WriteOnlyChannel(BusChannel):
    """Channel on a device with no readback pin."""

    def _read_code(self) -> int:
        raise AssertionError("a write-only device must not read the bus")


class WriteOnlyDAC(BusDAC):
    """Two 8-bit write-only channels."""

    _READABLE = False
    _CHANNEL_CLASS = WriteOnlyChannel


class FixedReferenceDAC(BusDAC):
    """Two 8-bit channels with an internal full scale."""

    _FIXED_REFERENCE = FIXED_REFERENCE


class SwitchableTransport(RecordingTransport):
    """Transport that can be made to fail on demand."""

    def __init__(self) -> None:
        super().__init__()
        self.failing = False

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Fail once switched, otherwise record and answer."""
        if self.failing:
            raise RuntimeError("bus failure")
        return super().transfer(data)


def write_only(
    transport: RecordingTransport | None = None,
) -> tuple[WriteOnlyDAC, RecordingTransport]:
    """Build a write-only device and return it with its transport."""
    transport = RecordingTransport() if transport is None else transport
    return WriteOnlyDAC(backend=transport), transport


def test_construction_issues_no_transfers() -> None:
    """Building the channels never touches the bus."""
    dac, transport = write_only()
    assert transport.requests == []
    assert dac.readable is False
    assert dac.channel(0).readable is False


def test_value_starts_at_zero_without_a_transfer() -> None:
    """The power-up register value is served from the shadow cache."""
    dac, transport = write_only()
    channel = dac.channel(0)
    assert channel.value == 0
    assert channel.value == 0
    assert transport.requests == []


def test_a_write_is_one_transfer_and_the_value_becomes_cached() -> None:
    """The setter writes once; the getter stops asking the bus."""
    dac, transport = write_only()
    channel = dac.channel(0)
    channel.value = 5
    assert transport.requests == [[0, 5]]
    assert channel.value == 5
    assert len(transport.requests) == 1


def test_read_all_returns_the_cached_codes() -> None:
    """Cached codes are reported without extra bus traffic."""
    dac, transport = write_only()
    dac.write_all([1, 2])
    before = len(transport.requests)
    assert dac.read_all() == (1, 2)
    assert len(transport.requests) == before


def test_write_all_writes_once_per_channel_in_order() -> None:
    """The whole sequence is applied in index order and read back nowhere."""
    dac, transport = write_only()
    assert dac.write_all([1, 2]) == (1, 2)
    assert transport.requests == [[0, 1], [1, 2]]


def test_a_failed_write_keeps_the_previous_cached_code() -> None:
    """Both caches only advance after a successful transfer."""
    transport = SwitchableTransport()
    dac, _ = write_only(transport)
    channel = dac.channel(0)
    channel.value = 5
    transport.failing = True
    with pytest.raises(RuntimeError):
        channel.value = 7
    assert channel.value == 5
    assert channel._reported_code == 5
    assert channel._shadow_code == 5


def test_readback_raises_on_a_write_only_device() -> None:
    """A register read is an unsupported operation, not a bad argument."""
    dac, _ = write_only()
    with pytest.raises(DACReadbackError) as excinfo:
        dac.channel(1).readback()
    assert isinstance(excinfo.value, RuntimeError)
    assert isinstance(excinfo.value, DACError)
    assert "1" in str(excinfo.value)
    assert ".value" in str(excinfo.value)


def test_a_readable_device_reads_the_bus_every_time() -> None:
    """Zero reads stay live: 0.1.0 behaviour is unchanged by the cache."""
    transport = RecordingTransport(default=[64])
    channel = BusDAC(backend=transport).channel(0)
    assert channel.value == 64
    assert channel.value == 64
    assert transport.requests == [[0], [0]]


def test_a_readable_device_ignores_the_shadow_cache() -> None:
    """The getter never falls back to the last written code when readable."""
    transport = RecordingTransport(default=[64])
    channel = BusDAC(backend=transport).channel(0)
    channel.value = 5
    assert channel._shadow_code == 5
    assert channel.value == 64


def test_readback_reads_the_register_on_a_readable_device() -> None:
    """The explicit read path still works where the bus supports it."""
    transport = RecordingTransport(default=[64])
    channel = BusDAC(backend=transport).channel(1)
    assert channel.readback() == 64
    assert transport.requests == [[1]]


def test_a_fixed_reference_resolves_from_none() -> None:
    """The constant fills in a reference the caller left unset."""
    dac = FixedReferenceDAC(backend=MemoryBackend())
    assert dac.readable is True
    assert dac.reference == FIXED_REFERENCE


def test_a_fixed_reference_accepts_its_own_value() -> None:
    """Passing the constant explicitly is not a conflict."""
    dac = FixedReferenceDAC(backend=MemoryBackend(), reference=FIXED_REFERENCE)
    assert dac.reference == FIXED_REFERENCE


def test_a_conflicting_reference_is_rejected_at_construction() -> None:
    """A different full scale can never be silently substituted."""
    with pytest.raises(ValueError):
        FixedReferenceDAC(backend=MemoryBackend(), reference=3.3)


def test_a_late_conflict_is_rejected_and_keeps_the_constant() -> None:
    """The setter applies the same rule as the constructor."""
    dac = FixedReferenceDAC(backend=MemoryBackend())
    with pytest.raises(ValueError):
        dac.reference = 3.3
    assert dac.reference == FIXED_REFERENCE


def test_clearing_a_fixed_reference_re_resolves_to_the_constant() -> None:
    """None never clears the full scale of a fixed-reference device."""
    dac = FixedReferenceDAC(backend=MemoryBackend())
    dac.reference = None
    assert dac.reference == FIXED_REFERENCE
