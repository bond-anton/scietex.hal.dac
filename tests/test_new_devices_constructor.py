"""Cross-family constructor and lifecycle matrix for the 0.2.0 devices."""

from dataclasses import dataclass
from typing import Any

import pytest
from conftest import FakeStrobe, RecordingTransport, fake

import scietex.hal.dac.__transport as transport_module
from scietex.hal.dac import (
    AD5302,
    AD5312,
    AD5322,
    AD7390,
    AD7391,
    DAC,
    DAC121S101,
    DAC8512,
    DAC8531,
    DAC8551,
    DAC8552,
    MCP4231,
    MCP4241,
    MCP4251,
    MCP4261,
    MCP4802,
    MCP4812,
    MCP4822,
    MCP4902,
    MCP4912,
    MCP4922,
    DACReadbackError,
)


@dataclass(frozen=True)
class Spec:
    """One device under test and the attributes it must report."""

    part: type[DAC]
    channels: int
    resolution: int
    max_code: int
    fixed: float | None
    mode: int
    strobed: bool = False


SPECS = [
    Spec(MCP4802, 2, 8, 255, 2.048, 0),
    Spec(MCP4812, 2, 10, 1023, 2.048, 0),
    Spec(MCP4822, 2, 12, 4095, 2.048, 0),
    Spec(MCP4902, 2, 8, 255, None, 0),
    Spec(MCP4912, 2, 10, 1023, None, 0),
    Spec(MCP4922, 2, 12, 4095, None, 0),
    Spec(DAC8531, 1, 16, 65535, None, 1),
    Spec(DAC8551, 1, 16, 65535, None, 1),
    Spec(DAC8552, 2, 16, 65535, None, 1),
    Spec(DAC121S101, 1, 12, 4095, None, 1),
    Spec(AD5302, 2, 8, 255, None, 1),
    Spec(AD5312, 2, 10, 1023, None, 1),
    Spec(AD5322, 2, 12, 4095, None, 1),
    Spec(DAC8512, 1, 12, 4095, 4.095, 0, strobed=True),
    Spec(AD7390, 1, 12, 4095, None, 0, strobed=True),
    Spec(AD7391, 1, 10, 1023, None, 0, strobed=True),
]

FIXED_SPECS = [spec for spec in SPECS if spec.fixed is not None]

MODE_ONE_PARTS = [DAC8531, DAC121S101, AD5322]

MODE_ZERO_PARTS = [MCP4822, DAC8512, AD7390]

STROBED_PARTS = (DAC8512, AD7390)


def ids(spec: Spec) -> str:
    """Readable parametrization id: the chip class name."""
    return spec.part.__name__


class Bus(RecordingTransport):
    """Recording transport that also exposes a raw SPI handle."""

    def __init__(self) -> None:
        super().__init__()
        self.raw = object()


def build(spec: Spec, **kwargs: Any) -> tuple[DAC, Bus, FakeStrobe | None]:
    """Build `spec` on a recording bus and a fake strobe when it needs one."""
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = Bus()
    strobe = kwargs.pop("strobe", None)
    if spec.strobed:
        strobe = FakeStrobe() if strobe is None else strobe
        kwargs["strobe"] = strobe
    return spec.part(transport=transport, **kwargs), transport, strobe


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_construction_issues_no_bus_traffic(spec: Spec) -> None:
    """Building every part touches neither the bus nor the load line."""
    dac, transport, strobe = build(spec)
    assert transport.requests == []
    assert transport.close_calls == 0
    if strobe is not None:
        assert strobe.pulse_calls == []
        assert strobe.close_calls == 0
    assert dac.closed is False


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_attributes_match_the_matrix(spec: Spec) -> None:
    """Channel count, resolution, full scale, readability, and SPI mode match."""
    dac, _, _ = build(spec)
    assert len(dac.channels) == spec.channels
    assert dac.resolution == spec.resolution
    assert dac.max_code == spec.max_code
    assert dac.readable is False
    assert all(channel.readable is False for channel in dac.channels)
    assert isinstance(dac.channels, tuple)
    assert len({id(channel) for channel in dac.channels}) == spec.channels
    if spec.fixed is None:
        assert dac.reference is None
    else:
        assert dac.reference == pytest.approx(spec.fixed)
    assert spec.mode == spec.part._SPI_MODE


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_channel_indices_out_of_range_raise(spec: Spec) -> None:
    """The channel accessor rejects both ends of the index range."""
    dac, _, _ = build(spec)
    with pytest.raises(IndexError):
        dac.channel(-1)
    with pytest.raises(IndexError):
        dac.channel(spec.channels)


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_transport_is_the_injected_bus(spec: Spec) -> None:
    """The device exposes the caller's transport, never a strobe wrapper."""
    dac, transport, _ = build(spec)
    assert dac.transport is transport
    if spec.strobed:
        assert dac.transport is not dac._backend


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_spi_returns_the_raw_handle(spec: Spec) -> None:
    """A transport that exposes a raw handle reports it through `spi`."""
    dac, transport, _ = build(spec)
    assert dac.spi is transport.raw


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_lifecycle_closes_the_bus_once(spec: Spec) -> None:
    """`closed` flips on close and a second close is harmless."""
    dac, transport, strobe = build(spec)
    assert dac.closed is False
    dac.close()
    assert dac.closed is True
    assert transport.closed is True
    assert transport.close_calls == 1
    dac.close()
    assert dac.closed is True
    if strobe is not None:
        # The backend owns both objects, so its second close is a no-op.
        assert transport.close_calls == 1
        assert strobe.closed is True
        assert strobe.close_calls == 1


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_context_manager_closes_the_device_and_the_strobe(spec: Spec) -> None:
    """Leaving the context releases the bus and, when present, the strobe."""
    dac, transport, strobe = build(spec)
    with dac as entered:
        assert entered is dac
        assert dac.closed is False
    assert dac.closed is True
    assert transport.closed is True
    if strobe is not None:
        assert strobe.closed is True


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_channel_count_out_of_range_is_rejected_before_any_transfer(
    spec: Spec,
) -> None:
    """Both `0` and one past the geometry fail without touching the bus."""
    for count in (0, spec.channels + 1):
        transport = Bus()
        with pytest.raises(ValueError):
            build(spec, transport=transport, channels=count)
        assert transport.requests == []


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_wrong_type_reference_is_rejected_before_any_transfer(spec: Spec) -> None:
    """A string is not a full scale, whatever the family."""
    transport = Bus()
    with pytest.raises(TypeError):
        build(spec, transport=transport, reference="3.3")
    assert transport.requests == []


@pytest.mark.parametrize("spec", FIXED_SPECS, ids=ids)
def test_conflicting_fixed_reference_is_rejected_before_any_transfer(
    spec: Spec,
) -> None:
    """An internal full scale cannot be overridden, and no bus is opened."""
    transport = Bus()
    assert spec.fixed is not None
    with pytest.raises(ValueError):
        build(spec, transport=transport, reference=spec.fixed * 2)
    assert transport.requests == []


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_empty_label_closes_the_transport_exactly_once(spec: Spec) -> None:
    """A late rejection releases every resource the constructor opened."""
    transport = Bus()
    strobe = FakeStrobe() if spec.strobed else None
    with pytest.raises(ValueError):
        build(spec, transport=transport, strobe=strobe, label="")
    assert transport.close_calls == 1
    assert transport.closed is True
    if strobe is not None:
        assert strobe.close_calls == 1
        assert strobe.closed is True


@pytest.mark.parametrize("part", [DAC8531, AD7390])
def test_explicit_transport_wins_over_the_spi_alias(part: type[DAC]) -> None:
    """`transport` takes priority when both transport keywords are given."""
    winner = Bus()
    loser = Bus()
    extra = {"strobe": FakeStrobe()} if part is AD7390 else {}
    dac = part(transport=winner, spi=loser, **extra)
    assert dac.transport is winner


@pytest.mark.parametrize("part", [DAC8531, AD7390])
def test_spi_alias_builds_when_no_transport_is_given(part: type[DAC]) -> None:
    """The legacy keyword alone selects the bus on plain and strobed parts."""
    transport = Bus()
    extra = {"strobe": FakeStrobe()} if part is AD7390 else {}
    dac = part(spi=transport, **extra)
    assert dac.transport is transport


@pytest.mark.parametrize("part", MODE_ONE_PARTS)
def test_mode_one_parts_reject_gpiozero_pins(part: type[DAC]) -> None:
    """A mode-1 bus cannot be built from the gpiozero backend."""
    with pytest.raises(ValueError, match="SPI mode"):
        part(clock_pin=11)


@pytest.mark.parametrize("part", MODE_ZERO_PARTS)
def test_mode_zero_parts_build_the_gpiozero_backend(
    part: type[DAC], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mode-0 bus delegates the pin keywords to the shared builder."""
    built = Bus()
    forwarded: dict[str, Any] = {}

    def builder(**kwargs: Any) -> Bus:
        forwarded.update(kwargs)
        return built

    monkeypatch.setattr(transport_module, "build_default_transport", builder)
    extra = {"strobe": FakeStrobe()} if part in STROBED_PARTS else {}
    dac = part(clock_pin=11, **extra)
    assert dac.transport is built
    assert forwarded["clock_pin"] == 11


@pytest.mark.parametrize("spec", SPECS, ids=ids)
def test_write_only_channels_cache_and_refuse_readback(spec: Spec) -> None:
    """Every 0.2.0 part is write-only and serves the cached power-up code."""
    dac, transport, strobe = build(spec)
    channel = dac.channel(0)
    assert isinstance(channel.value, int)
    assert channel.value == 0
    with pytest.raises(DACReadbackError):
        channel.readback()
    assert isinstance(channel.value, int)
    assert channel.value == 0
    assert transport.requests == []
    if strobe is not None:
        assert strobe.pulse_calls == []


@pytest.mark.parametrize("part", [MCP4231, MCP4241, MCP4251, MCP4261])
def test_potentiometers_stay_readable(part: type[DAC]) -> None:
    """The 0.1.0 pot wrappers keep reporting themselves as readable."""
    assert part(transport=fake()).readable is True
