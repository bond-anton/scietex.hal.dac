"""Shared infrastructure: frame packing, channel mixins, and transport choice."""

from typing import Any

import pytest
from conftest import MemoryBackend, RecordingTransport

import scietex.hal.dac as dac_package
import scietex.hal.dac.__transport as transport_module
from scietex.hal.dac import DAC, VoltageChannel
from scietex.hal.dac.__frames import pack
from scietex.hal.dac.channel import BufferedChannel, GainChannel, PowerDownChannel


class CombinedChannel(GainChannel, BufferedChannel, PowerDownChannel, VoltageChannel):
    """Voltage channel carrying every shared chip-family field."""

    def _read_code(self) -> int:
        return self._dac.codes[self.index]

    def _write_code(self, code: int) -> int:
        self._dac.transport.transfer([self.index, code])
        self._dac.codes[self.index] = code
        return code


class CombinedDAC(DAC):
    """Single 12-bit channel with the full mixin stack."""

    _CHANNELS = 1
    _RESOLUTION = 12
    _CHANNEL_CLASS = CombinedChannel

    def __init__(
        self,
        *,
        backend: object | None = None,
        reference: float | None = None,
    ) -> None:
        self.codes = [0]
        super().__init__(
            backend=MemoryBackend() if backend is None else backend,
            reference=reference,
        )


class WriteOnlyChannel(GainChannel, BufferedChannel, PowerDownChannel, VoltageChannel):
    """Combined channel on a device with no readback path."""

    def _read_code(self) -> int:
        raise AssertionError("a write-only device must not read the bus")

    def _write_code(self, code: int) -> int:
        self._dac.transport.transfer([code])
        return code


class WriteOnlyDAC(DAC):
    """Single 12-bit write-only channel with the full mixin stack."""

    _CHANNELS = 1
    _RESOLUTION = 12
    _READABLE = False
    _CHANNEL_CLASS = WriteOnlyChannel


def combined(
    reference: float | None = 1.0,
) -> tuple[CombinedDAC, CombinedChannel, MemoryBackend]:
    """Build a readable combined-mixin device and return channel and backend."""
    backend = MemoryBackend()
    dac = CombinedDAC(backend=backend, reference=reference)
    return dac, dac.channel(0), backend


def write_only(
    reference: float | None = 2.048,
) -> tuple[WriteOnlyDAC, WriteOnlyChannel, RecordingTransport]:
    """Build a write-only combined-mixin device and return channel and bus."""
    transport = RecordingTransport()
    dac = WriteOnlyDAC(backend=transport, reference=reference)
    return dac, dac.channel(0), transport


@pytest.mark.parametrize(
    ("word", "length", "expected"),
    [
        (0xABC, 2, [0x0A, 0xBC]),
        (0xBEEF, 3, [0x00, 0xBE, 0xEF]),
        (0, 1, [0]),
    ],
)
def test_pack_splits_a_word_most_significant_byte_first(
    word: int, length: int, expected: list[int]
) -> None:
    """The most significant byte leads the frame."""
    assert pack(word, length) == expected


def test_pack_rejects_a_word_that_does_not_fit() -> None:
    """One byte cannot hold 0x100."""
    with pytest.raises(ValueError):
        pack(0x100, 1)


@pytest.mark.parametrize("length", [0, -1])
def test_pack_rejects_a_non_positive_length(length: int) -> None:
    """A frame has at least one byte."""
    with pytest.raises(ValueError):
        pack(1, length)


def test_mixin_defaults_match_the_power_on_state() -> None:
    """Gain 2x, no buffer, and normal operation are the chip defaults."""
    _, channel, _ = combined()
    assert channel.gain == 2
    assert channel.buffered is False
    assert channel.power_down == 0


def test_mixins_combine_ahead_of_a_channel_class() -> None:
    """All three fields live on one channel object."""
    _, channel, _ = combined()
    assert isinstance(channel, GainChannel)
    assert isinstance(channel, BufferedChannel)
    assert isinstance(channel, PowerDownChannel)


def test_mixins_stay_out_of_the_package_root() -> None:
    """The mixins are building blocks, not public channels."""
    assert not hasattr(dac_package, "GainChannel")


def test_gain_scales_the_effective_reference() -> None:
    """The override stays unscaled while `reference` follows the gain."""
    _, channel, _ = combined(reference=5.0)
    channel.reference_override = 1.0
    assert channel.reference == pytest.approx(2.0)
    channel.gain = 1
    assert channel.reference == pytest.approx(1.0)
    assert channel.reference_override == 1.0


def test_gain_scales_the_device_reference_as_well() -> None:
    """Without an override the device full scale is the unscaled reference."""
    _, channel, _ = combined(reference=2.048)
    assert channel.reference == pytest.approx(4.096)


def test_an_absent_reference_stays_absent_under_gain() -> None:
    """No full scale means no output, whatever the gain."""
    _, channel, _ = combined(reference=None)
    assert channel.reference is None
    assert channel.output is None


def test_gain_moves_the_clamp_bound() -> None:
    """A request above the scaled full scale lands on the top code."""
    _, channel, _ = combined(reference=2.048)
    channel.output = 10.0
    assert channel.value == 4095
    assert channel.output == pytest.approx(4.096)


def test_changing_the_fields_keeps_the_code_and_issues_no_transfers() -> None:
    """Gain, buffer, and power-down reach the chip only on the next write."""
    _, channel, transport = write_only()
    channel.value = 100
    assert len(transport.requests) == 1
    channel.gain = 1
    channel.buffered = True
    channel.power_down = 3
    assert channel.value == 100
    assert len(transport.requests) == 1


def test_output_uses_the_gain_scaled_reference_on_a_write_only_device() -> None:
    """Full code reaches the scaled full scale without reading the bus."""
    _, channel, transport = write_only(reference=2.048)
    channel.value = 4095
    assert channel.output == pytest.approx(4.096)
    channel.gain = 1
    assert channel.output == pytest.approx(2.048)
    assert len(transport.requests) == 1


@pytest.mark.parametrize("gain", [True, "1", 1.5])
def test_gain_rejects_a_wrong_type(gain: object) -> None:
    """A gain factor is an integer, not a flag or a string."""
    channel = combined()[1]
    with pytest.raises(TypeError):
        channel.gain = gain


@pytest.mark.parametrize("gain", [0, 3])
def test_gain_rejects_an_unsupported_factor(gain: int) -> None:
    """Only the factors the gain bit can select are accepted."""
    channel = combined()[1]
    with pytest.raises(ValueError):
        channel.gain = gain
    assert channel.gain == 2


def test_buffered_accepts_both_states() -> None:
    """The buffer flag round-trips as a bool."""
    channel = combined()[1]
    channel.buffered = True
    assert channel.buffered is True
    channel.buffered = False
    assert channel.buffered is False


@pytest.mark.parametrize("buffered", [1, 0, "yes", None])
def test_buffered_rejects_a_non_bool(buffered: object) -> None:
    """A numeric or textual flag is a caller mistake."""
    channel = combined()[1]
    with pytest.raises(TypeError):
        channel.buffered = buffered
    assert channel.buffered is False


@pytest.mark.parametrize("power_down", [0, 1, 2, 3])
def test_power_down_accepts_every_documented_mode(power_down: int) -> None:
    """Each mode of a two-bit power-down field round-trips."""
    channel = combined()[1]
    channel.power_down = power_down
    assert channel.power_down == power_down


def test_power_down_rejects_a_bool() -> None:
    """A flag is not a mode number."""
    channel = combined()[1]
    with pytest.raises(TypeError):
        channel.power_down = True


@pytest.mark.parametrize("power_down", [4, -1])
def test_power_down_rejects_an_unknown_mode(power_down: int) -> None:
    """The field is two bits wide."""
    channel = combined()[1]
    with pytest.raises(ValueError):
        channel.power_down = power_down
    assert channel.power_down == 0


def test_an_explicit_transport_is_returned_unchanged() -> None:
    """A caller-supplied transport outranks every keyword."""
    chosen = object()
    assert transport_module.open_transport(mode=1, transport=chosen) is chosen


def test_spi_is_an_alias_for_transport() -> None:
    """The legacy keyword selects the same transport."""
    chosen = object()
    assert transport_module.open_transport(mode=0, spi=chosen) is chosen


def test_pin_keywords_with_a_nonzero_mode_are_rejected() -> None:
    """The gpiozero backend cannot express any mode but 0."""
    with pytest.raises(ValueError) as excinfo:
        transport_module.open_transport(mode=1, clock_pin=11)
    message = str(excinfo.value)
    assert "mode" in message
    assert "SpiDevTransport" in message


def test_pin_keywords_at_mode_zero_delegate_to_the_default_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gpiozero selection is the shared builder's job."""
    built = object()
    forwarded: dict[str, Any] = {}

    def builder(**kwargs: Any) -> object:
        forwarded.update(kwargs)
        return built

    monkeypatch.setattr(transport_module, "build_default_transport", builder)
    result = transport_module.open_transport(
        mode=0,
        port=1,
        device=2,
        clock_pin=11,
        mosi_pin=10,
        miso_pin=9,
        select_pin=8,
    )
    assert result is built
    assert forwarded == {
        "port": 1,
        "device": 2,
        "clock_pin": 11,
        "mosi_pin": 10,
        "miso_pin": 9,
        "select_pin": 8,
    }


def test_without_keywords_a_spidev_transport_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spidev backend takes the requested bus, device, and mode."""
    built: list[dict[str, int]] = []

    class FakeSpiDevTransport:
        """Record the settings it was opened with."""

        def __init__(self, *, bus: int = 0, device: int = 0, mode: int = 0) -> None:
            built.append({"bus": bus, "device": device, "mode": mode})

    monkeypatch.setattr(transport_module, "SpiDevTransport", FakeSpiDevTransport)
    assert isinstance(
        transport_module.open_transport(mode=1, port=2, device=3),
        FakeSpiDevTransport,
    )
    transport_module.open_transport(mode=0)
    assert built == [
        {"bus": 2, "device": 3, "mode": 1},
        {"bus": 0, "device": 0, "mode": 0},
    ]
