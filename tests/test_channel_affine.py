"""Affine output span: codes map onto the floor..reference range."""

import pytest
from conftest import MemoryBackend

from scietex.hal.dac import (
    DAC,
    CurrentChannel,
    DACReferenceError,
    DividerChannel,
    VoltageChannel,
)
from scietex.hal.dac.channel import GainChannel

REFERENCE = 3.3
FOUR_MA = 0.004
TWENTY_MA = 0.020


class MemoryCodes:
    """Read and write the code the device keeps in memory."""

    def _read_code(self) -> int:
        return self._dac.codes[self.index]

    def _write_code(self, code: int) -> int:
        self._dac.codes[self.index] = code
        return code


class MemoryVoltageChannel(MemoryCodes, VoltageChannel):
    """Voltage channel with a code held in memory."""


class MemoryCurrentChannel(MemoryCodes, CurrentChannel):
    """Current channel with a code held in memory."""


class MemoryDividerChannel(MemoryCodes, DividerChannel):
    """Divider channel with a code held in memory."""


class MemoryGainChannel(MemoryCodes, GainChannel, VoltageChannel):
    """Gain channel with a code held in memory."""


class ZeroFloorDAC(DAC):
    """Seven-bit voltage device with the default zero floor."""

    _CHANNELS = 1
    _RESOLUTION = 7
    _CHANNEL_CLASS = MemoryVoltageChannel

    def __init__(self, reference: float | None = None) -> None:
        self.codes = [0]
        super().__init__(backend=MemoryBackend(), reference=reference)


class FourTwentyDAC(DAC):
    """Twelve-bit current device spanning 4..20 mA."""

    _CHANNELS = 1
    _RESOLUTION = 12
    _CHANNEL_CLASS = MemoryCurrentChannel
    _LOWER_BOUND = FOUR_MA

    def __init__(self, reference: float | None = TWENTY_MA) -> None:
        self.codes = [0]
        super().__init__(backend=MemoryBackend(), reference=reference)


class LegacyDouble:
    """Device double written before the floor constant existed."""

    def __init__(self) -> None:
        self.reference = REFERENCE
        self.max_code = 127
        self.readable = True
        self.codes = [0]


def test_a_default_channel_has_a_zero_floor() -> None:
    """Code 0 maps to zero and the top code to the reference exactly."""
    dac = ZeroFloorDAC(reference=REFERENCE)
    channel = dac.channel(0)
    assert channel.lower_bound == 0.0
    dac.codes[0] = 0
    assert channel.output == 0.0
    dac.codes[0] = dac.max_code // 2
    assert channel.output == pytest.approx(REFERENCE / 2, abs=REFERENCE / dac.max_code)
    dac.codes[0] = dac.max_code
    assert channel.output == REFERENCE


def test_a_non_zero_floor_maps_the_span_onto_the_codes() -> None:
    """A 4..20 mA span reaches the floor at code 0 and the reference at the top."""
    dac = FourTwentyDAC()
    channel = dac.channel(0)
    assert channel.lower_bound == FOUR_MA
    dac.codes[0] = 0
    assert channel.output == FOUR_MA
    dac.codes[0] = dac.max_code
    assert channel.output == TWENTY_MA
    dac.codes[0] = round(dac.max_code / 2)
    assert channel.output == pytest.approx(
        0.012, abs=(TWENTY_MA - FOUR_MA) / dac.max_code
    )


def test_an_output_below_the_floor_clamps_to_code_zero() -> None:
    """An undershoot lands on the floor's code."""
    dac = FourTwentyDAC()
    channel = dac.channel(0)
    channel.output = 0.0
    assert channel.value == 0
    channel.output = 0.002
    assert channel.value == 0


def test_an_output_above_the_reference_clamps_to_the_top_code() -> None:
    """An overshoot lands on the reference's code."""
    dac = FourTwentyDAC()
    channel = dac.channel(0)
    channel.output = 0.030
    assert channel.value == dac.max_code


def test_an_in_range_output_inverts_to_its_code() -> None:
    """A level inside the span inverts to the code that produces it."""
    dac = FourTwentyDAC()
    channel = dac.channel(0)
    channel.output = 0.010
    expected = round((0.010 - FOUR_MA) / (TWENTY_MA - FOUR_MA) * dac.max_code)
    assert channel.value == expected
    assert channel.output == pytest.approx(
        0.010, abs=(TWENTY_MA - FOUR_MA) / dac.max_code
    )


@pytest.mark.parametrize("value", [True, "4"])
def test_a_non_numeric_floor_is_a_type_error(value: object) -> None:
    """A flag or a string is a caller mistake, not a floor."""
    channel = ZeroFloorDAC(reference=REFERENCE).channel(0)
    with pytest.raises(TypeError):
        channel.lower_bound = value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_floor_is_a_value_error(value: float) -> None:
    """A floor has to be a real level."""
    channel = ZeroFloorDAC(reference=REFERENCE).channel(0)
    with pytest.raises(ValueError):
        channel.lower_bound = value


def test_a_negative_floor_is_accepted() -> None:
    """A bipolar span needs a floor below zero."""
    channel = ZeroFloorDAC(reference=REFERENCE).channel(0)
    channel.lower_bound = -10.0
    assert channel.lower_bound == -10.0


def test_the_device_reference_moves_only_the_upper_bound() -> None:
    """Setting the device reference leaves the inherited floor untouched."""
    dac = FourTwentyDAC()
    channel = dac.channel(0)
    dac.reference = 0.024
    assert channel.reference == 0.024
    assert channel.lower_bound == FOUR_MA
    dac.reference = None
    assert channel.reference is None
    assert channel.lower_bound == FOUR_MA


def test_reference_override_moves_only_the_upper_bound() -> None:
    """The override aliases the upper bound, never the span width."""
    dac = FourTwentyDAC()
    channel = dac.channel(0)
    channel.reference_override = 0.024
    assert channel.reference == 0.024
    assert channel.lower_bound == FOUR_MA
    channel.i_full_scale = 0.030
    assert channel.reference == 0.030
    assert channel.reference_override == 0.030
    assert channel.lower_bound == FOUR_MA


def test_v_ref_aliases_the_upper_bound_without_moving_the_floor() -> None:
    """`v_ref` writes the override, so the floor stays where it was."""
    dac = ZeroFloorDAC(reference=REFERENCE)
    channel = dac.channel(0)
    channel.lower_bound = 1.0
    channel.v_ref = 2.5
    assert channel.reference == 2.5
    assert channel.reference_override == 2.5
    assert channel.lower_bound == 1.0


def test_no_reference_leaves_the_output_unset() -> None:
    """Without an upper bound the channel refuses to guess, floor or not."""
    channel = ZeroFloorDAC().channel(0)
    assert channel.output is None
    with pytest.raises(DACReferenceError):
        channel.output = 1.0


@pytest.mark.parametrize("floor", [REFERENCE, REFERENCE + 1.0])
def test_a_floor_at_or_above_the_reference_is_rejected(floor: float) -> None:
    """A span with no width has no code to write."""
    dac = ZeroFloorDAC(reference=REFERENCE)
    channel = dac.channel(0)
    channel.lower_bound = floor
    with pytest.raises(DACReferenceError):
        channel.output = 1.0


def test_a_divider_is_unchanged_by_the_affine_form() -> None:
    """A grounded-A divider still falls from the reference to zero."""
    dac = ZeroFloorDAC(reference=REFERENCE)
    channel = MemoryDividerChannel(dac, 0, grounded="A")
    assert channel.lower_bound == 0.0
    dac.codes[0] = 0
    assert channel.output == REFERENCE
    dac.codes[0] = 64
    assert channel.output == pytest.approx(63 / 127 * REFERENCE)
    dac.codes[0] = dac.max_code
    assert channel.output == 0.0


def test_a_gain_channel_is_unchanged_by_the_affine_form() -> None:
    """Gain still scales the upper bound and the top code reaches it."""
    dac = ZeroFloorDAC(reference=REFERENCE)
    channel = MemoryGainChannel(dac, 0)
    assert channel.lower_bound == 0.0
    channel.reference_override = 1.0
    assert channel.reference == 2.0
    dac.codes[0] = dac.max_code
    assert channel.output == 2.0
    dac.codes[0] = 0
    assert channel.output == 0.0


def test_a_device_double_without_the_constant_gets_a_zero_floor() -> None:
    """A hand-written double that defines no floor still scales normally."""
    dac = LegacyDouble()
    channel = MemoryVoltageChannel(dac, 0)
    assert channel.lower_bound == 0.0
    dac.codes[0] = dac.max_code
    assert channel.output == REFERENCE
