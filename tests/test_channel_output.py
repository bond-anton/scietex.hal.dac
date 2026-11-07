"""Scaled output of voltage and divider channels."""

import pytest
from conftest import MemoryBackend

from scietex.hal.dac import DAC, DividerChannel, VoltageChannel

SEVEN_BIT_FULL_SCALE = 127
EIGHT_BIT_FULL_SCALE = 255
REFERENCE = 3.3


class MemoryCodes:
    """Read and write the code the device keeps in memory."""

    def _read_code(self) -> int:
        return self._dac.codes[self.index]

    def _write_code(self, code: int) -> int:
        self._dac.codes[self.index] = code
        return code


class FixedVoltageChannel(MemoryCodes, VoltageChannel):
    """Voltage channel with a code held in memory."""


class FixedDividerChannel(MemoryCodes, DividerChannel):
    """Divider channel with a code held in memory."""


class VoltageDAC(DAC):
    """Two 7-bit voltage channels backed by memory."""

    _CHANNELS = 2
    _RESOLUTION = 7
    _CHANNEL_CLASS = FixedVoltageChannel

    def __init__(self, reference: float | None = None) -> None:
        self.codes = [0] * self._CHANNELS
        super().__init__(backend=MemoryBackend(), reference=reference)


class EightBitDAC(VoltageDAC):
    """The same device at 8-bit resolution."""

    _RESOLUTION = 8


def divider(dac: DAC, grounded: str, code: int) -> FixedDividerChannel:
    """Build a divider channel reporting `code`."""
    channel = FixedDividerChannel(dac, 0, grounded=grounded)
    dac.codes[0] = code
    return channel


def test_grounded_b_rises_from_zero_to_the_reference() -> None:
    """Grounding B makes code 0 the bottom and the top code the reference."""
    dac = VoltageDAC(reference=REFERENCE)
    assert divider(dac, "B", 0).output == 0.0
    assert divider(dac, "B", SEVEN_BIT_FULL_SCALE).output == pytest.approx(REFERENCE)
    assert divider(dac, "B", 64).output == pytest.approx(64 / 127 * REFERENCE)


def test_grounded_a_falls_from_the_reference_to_zero() -> None:
    """Grounding A mirrors the curve, the reference moving to code 0."""
    dac = VoltageDAC(reference=REFERENCE)
    assert divider(dac, "A", 0).output == pytest.approx(REFERENCE)
    assert divider(dac, "A", SEVEN_BIT_FULL_SCALE).output == 0.0
    assert divider(dac, "A", 64).output == pytest.approx(63 / 127 * REFERENCE)


def test_eight_bit_channels_use_their_own_full_scale() -> None:
    """The full scale follows the resolution, not the divider geometry."""
    dac = EightBitDAC(reference=5.0)
    channel = FixedVoltageChannel(dac, 0)
    dac.codes[0] = EIGHT_BIT_FULL_SCALE
    assert channel.output == 5.0
    dac.codes[0] = 128
    assert channel.output == pytest.approx(128 / 255 * 5.0)


def test_voltage_is_an_alias_of_output() -> None:
    """The unit-specific name reads and writes the canonical `output`."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedVoltageChannel(dac, 0)
    dac.codes[0] = 64
    assert channel.voltage == channel.output
    channel.voltage = 1.65
    assert dac.codes[0] == 64
    assert channel.voltage == channel.output == pytest.approx(64 / 127 * REFERENCE)


def test_unit_and_v_ref_aliases() -> None:
    """A voltage channel reports volts and maps `v_ref` onto the override."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedVoltageChannel(dac, 0)
    assert channel.unit == "V"
    assert channel.v_ref == channel.reference == REFERENCE
    channel.v_ref = 2.5
    assert channel.reference_override == 2.5


def test_output_rounds_to_the_nearest_code() -> None:
    """Half scale rounds to the middle code."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedDividerChannel(dac, 0, grounded="B")
    channel.output = 1.65
    assert dac.codes[0] == round(0.5 * SEVEN_BIT_FULL_SCALE) == 64


def test_output_below_zero_clamps_to_the_bottom_code() -> None:
    """An undershoot is clamped, not rejected."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedDividerChannel(dac, 0, grounded="B")
    channel.output = -1.0
    assert dac.codes[0] == 0


def test_output_above_the_reference_clamps_to_the_top_code() -> None:
    """An overshoot is clamped, not rejected."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedDividerChannel(dac, 0, grounded="B")
    channel.output = 10.0
    assert dac.codes[0] == SEVEN_BIT_FULL_SCALE


def test_grounded_a_clamping_is_mirrored() -> None:
    """The clamped endpoints follow the divider direction."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedDividerChannel(dac, 0, grounded="A")
    channel.output = -1.0
    assert dac.codes[0] == SEVEN_BIT_FULL_SCALE
    channel.output = 10.0
    assert dac.codes[0] == 0


def test_none_output_is_a_type_error() -> None:
    """None is a wrong type, not a value to clamp."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedVoltageChannel(dac, 0)
    with pytest.raises(TypeError):
        channel.output = None


@pytest.mark.parametrize("output", [float("nan"), float("inf")])
def test_non_finite_output_is_a_value_error(output: float) -> None:
    """NaN and infinity have no code."""
    dac = VoltageDAC(reference=REFERENCE)
    channel = FixedVoltageChannel(dac, 0)
    with pytest.raises(ValueError):
        channel.output = output
