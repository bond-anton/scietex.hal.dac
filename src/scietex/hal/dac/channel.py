"""Channel objects for digital-to-analog converters."""

from enum import Enum
from typing import TYPE_CHECKING, ClassVar, cast

from .__helpers import (
    check_grounded,
    check_integer,
    check_number,
    check_reference,
    clamp,
)
from .errors import DACCodeError, DACReferenceError

if TYPE_CHECKING:
    from .dac import DAC


class DACUnit(str, Enum):
    """Physical quantity a channel drives."""

    VOLTAGE = "V"
    CURRENT = "A"

    def __str__(self) -> str:
        """Return the unit symbol, so the enum prints like the bare suffix."""
        return self.value


class DACChannel:
    """
    One output of a `DAC` device.

    The channel keeps no register state: reading `value` asks the device every
    time, and the setter writes the code through to it. `output` scales that
    code by the reference and stays None while no reference is configured,
    because the library will not guess a full scale.

    A device may scale each channel differently, so `reference_override` wins
    over the device reference for this channel only.
    """

    UNIT: ClassVar[DACUnit] = DACUnit.VOLTAGE

    def __init__(self, dac: "DAC", index: int) -> None:
        self._dac = dac
        self.index = check_integer(index)
        self._reference_override: float | None = None
        self._reported_code: int | None = None

    @property
    def max_code(self) -> int:
        """Largest raw code the device accepts for this channel."""
        return self._dac.max_code

    @property
    def unit(self) -> DACUnit:
        """Physical quantity this channel drives."""
        return self.UNIT

    @property
    def reference_override(self) -> float | None:
        """Per-channel reference that wins over the device reference."""
        return self._reference_override

    @reference_override.setter
    def reference_override(self, reference: float | None) -> None:
        """
        Set a per-channel reference, or clear it with None.

        :param reference: Positive reference, or None to fall back to the
            device reference (float | None).
        :raises TypeError: If `reference` is not a real number, or is a `bool`.
        :raises ValueError: If `reference` is zero, negative, infinite, or `NaN`.
        """
        self._reference_override = check_reference(reference)

    @property
    def reference(self) -> float | None:
        """Reference this channel scales by: the override, else the device's."""
        override = self.reference_override
        if override is not None:
            return override
        return self._dac.reference

    @property
    def value(self) -> int:
        """
        Raw code of the output, read from the device.

        :return: Code in `0..max_code` (int).
        """
        return self._read_code()

    @value.setter
    def value(self, code: int) -> None:
        """
        Write a raw code to the device.

        :param code: Code in `0..max_code` (int).
        :raises TypeError: If `code` is not a real number, or is a `bool`.
        :raises ValueError: If `code` is fractional, infinite, or `NaN`.
        :raises DACCodeError: If `code` is outside `0..max_code`.
        """
        self._reported_code = self._write_code(self._check_code(code))

    @property
    def output(self) -> float | None:
        """
        Canonical output scaled by the channel reference.

        Units follow the channel: volts for a voltage output, amperes for a
        current output. The value is the code fraction times the reference, so
        the top code reaches the reference itself.

        :return: Scaled output, or None when the channel has no reference.
        """
        reference = self.reference
        if reference is None:
            return None
        return self._code_to_fraction(self.value) * reference

    @output.setter
    def output(self, output: float | None) -> None:
        """
        Set the output from a scaled value.

        The value is clamped into `0..reference` without an error, so a caller
        asking for slightly more than full scale gets full scale instead of a
        rejected write.

        :param output: Output in the channel unit (float).
        :raises TypeError: If `output` is not a real number, is a `bool`, or is
            None.
        :raises ValueError: If `output` is infinite or `NaN`.
        :raises DACReferenceError: If the channel has no reference.
        """
        reference = self.reference
        if reference is None:
            raise DACReferenceError(
                f"Channel {self.index} has no reference configured; "
                "set the device reference or a channel override first"
            )
        # None must reach check_number, which is what rejects it with TypeError.
        value = clamp(check_number(cast(float, output)), 0.0, reference)
        self.value = self._fraction_to_code(value / reference)

    def _check_code(self, code: int) -> int:
        """
        Validate a raw code before it reaches the device.

        :param code: Candidate code (int).
        :return: Code as int, unchanged.
        :raises TypeError: If `code` is not a real number, or is a `bool`.
        :raises ValueError: If `code` is fractional, infinite, or `NaN`.
        :raises DACCodeError: If `code` is outside `0..max_code`.
        """
        code = check_integer(code)
        if not 0 <= code <= self.max_code:
            raise DACCodeError(f"Expected a code within 0..{self.max_code}, got {code}")
        return code

    def _read_code(self) -> int:
        """
        Read the raw code from the device.

        :return: Code in `0..max_code`.
        :raises NotImplementedError: Always, the base class has no codec.
        """
        raise NotImplementedError

    def _write_code(self, code: int) -> int:
        """
        Write a validated raw code and return the code the device reports.

        :param code: Code already validated by `_check_code`.
        :return: Code the device reports after the write.
        :raises NotImplementedError: Always, the base class has no codec.
        """
        raise NotImplementedError

    def _code_to_fraction(self, code: int) -> float:
        """
        Map a raw code to the fraction of full scale it selects.

        :param code: Code in `0..max_code`.
        :return: Fraction in `0..1`.
        """
        return code / self.max_code

    def _fraction_to_code(self, fraction: float) -> int:
        """
        Map a fraction of full scale to the nearest raw code.

        :param fraction: Fraction in `0..1`.
        :return: Code in `0..max_code`.
        """
        return int(round(fraction * self.max_code))

    def __repr__(self) -> str:
        """Official string representation (used in debugging)."""
        return (
            f"{type(self).__name__}(index={self.index}, code={self._reported_code!r})"
        )


class VoltageChannel(DACChannel):
    """Channel that drives a voltage output."""

    UNIT: ClassVar[DACUnit] = DACUnit.VOLTAGE

    @property
    def voltage(self) -> float | None:
        """Output voltage in volts, an alias of `output`."""
        return self.output

    @voltage.setter
    def voltage(self, voltage: float | None) -> None:
        """Set the output voltage in volts, an alias of `output`."""
        self.output = voltage

    @property
    def v_ref(self) -> float | None:
        """Reference voltage this channel scales by."""
        return self.reference

    @v_ref.setter
    def v_ref(self, v_ref: float | None) -> None:
        """Set a per-channel reference voltage, an alias of `reference_override`."""
        self.reference_override = v_ref


class CurrentChannel(DACChannel):
    """Channel that drives a current output."""

    UNIT: ClassVar[DACUnit] = DACUnit.CURRENT

    @property
    def current(self) -> float | None:
        """Output current in amperes, an alias of `output`."""
        return self.output

    @current.setter
    def current(self, current: float | None) -> None:
        """Set the output current in amperes, an alias of `output`."""
        self.output = current

    @property
    def i_full_scale(self) -> float | None:
        """Full-scale current in amperes this channel scales by."""
        return self.reference

    @i_full_scale.setter
    def i_full_scale(self, i_full_scale: float | None) -> None:
        """Set a per-channel full-scale current, an alias of `reference_override`."""
        self.reference_override = i_full_scale


class DividerChannel(VoltageChannel):
    """
    Voltage output of a resistor divider with one terminal grounded.

    Grounding B makes the output rise from 0 V at code 0 to the reference at
    full code; grounding A mirrors that curve, so the output falls from the
    reference at code 0 to 0 V at full code.
    """

    def __init__(self, dac: "DAC", index: int, *, grounded: str) -> None:
        """
        Build a divider channel.

        :param dac: Device the channel belongs to (DAC).
        :param index: Channel index, 0-based (int).
        :param grounded: Terminal tied to ground, `"A"` or `"B"` (str).
        :raises TypeError: If `grounded` is not a str.
        :raises ValueError: If `grounded` is neither `"A"` nor `"B"`.
        """
        super().__init__(dac, index)
        self._grounded = check_grounded(grounded)

    @property
    def grounded(self) -> str:
        """Terminal tied to ground: `"B"` rises with the code, `"A"` falls."""
        return self._grounded

    def _code_to_fraction(self, code: int) -> float:
        """Map a code to the output fraction of the reference."""
        if self._grounded == "B":
            return code / self.max_code
        return (self.max_code - code) / self.max_code

    def _fraction_to_code(self, fraction: float) -> int:
        """Map an output fraction of the reference to the nearest code."""
        if self._grounded == "B":
            return int(round(fraction * self.max_code))
        return int(round((1 - fraction) * self.max_code))
