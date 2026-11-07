"""Channel objects for digital-to-analog converters."""

from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, cast

from .__helpers import (
    check_bool,
    check_choice,
    check_grounded,
    check_integer,
    check_number,
    check_reference,
    clamp,
)
from .errors import DACCodeError, DACReadbackError, DACReferenceError

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

    The channel keeps the code from the last successful write. On a readable
    device `value` still asks the device every time; on a write-only device it
    returns that cached code, since there is no register to read back. `output`
    maps the code onto the span from `lower_bound` to the reference and stays
    None while no reference is configured, because the library will not guess a
    full scale.

    A device may scale each channel differently, so `reference_override` wins
    over the device reference for this channel only. Both bound the top of the
    span; neither sets the floor.
    """

    UNIT: ClassVar[DACUnit] = DACUnit.VOLTAGE

    def __init__(self, dac: "DAC", index: int) -> None:
        self._dac = dac
        self.index = check_integer(index)
        self._reference_override: float | None = None
        self._lower_bound = float(getattr(dac, "_LOWER_BOUND", 0.0))
        self._reported_code: int | None = None
        # Every in-scope part powers up at zero scale, so "no write yet" and
        # "the register holds 0" are the same state.
        self._shadow_code: int = 0

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
        """Per-channel upper bound that wins over the device reference."""
        return self._reference_override

    @reference_override.setter
    def reference_override(self, reference: float | None) -> None:
        """
        Set a per-channel upper bound, or clear it with None.

        The override is the top of the span, not its width: the span still
        starts at `lower_bound`.

        :param reference: Positive upper bound, or None to fall back to the
            device reference (float | None).
        :raises TypeError: If `reference` is not a real number, or is a `bool`.
        :raises ValueError: If `reference` is zero, negative, infinite, or `NaN`.
        """
        self._reference_override = check_reference(reference)

    @property
    def reference(self) -> float | None:
        """Upper bound the top code maps to: the override, else the device's."""
        override = self.reference_override
        if override is not None:
            return override
        return self._dac.reference

    @property
    def lower_bound(self) -> float:
        """Output floor this channel maps code 0 to, in the channel unit."""
        return self._lower_bound

    @lower_bound.setter
    def lower_bound(self, lower_bound: float) -> None:
        """
        Set the output floor that code 0 maps to.

        The floor may be negative. Whether it stays below the reference is
        checked when an output is written, because the reference can change
        afterwards.

        :param lower_bound: Output floor in the channel unit (float).
        :raises TypeError: If `lower_bound` is not a real number, or is a
            `bool`.
        :raises ValueError: If `lower_bound` is infinite or `NaN`.
        """
        self._lower_bound = float(check_number(lower_bound))

    @property
    def readable(self) -> bool:
        """True when the device can report its own register contents."""
        return self._dac.readable

    @property
    def value(self) -> int:
        """
        Raw code of the output.

        A readable device is asked every time; a write-only device returns the
        code cached from the last successful write.

        :return: Code in `0..max_code` (int).
        """
        if not self._dac.readable:
            return self._shadow_code
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
        self._shadow_code = self._reported_code

    def readback(self) -> int:
        """Read the register over the bus; raises when the part is write-only."""
        if not self._dac.readable:
            raise DACReadbackError(
                f"Channel {self.index} belongs to a write-only device; "
                "use .value for the cached code"
            )
        return self._read_code()

    @property
    def output(self) -> float | None:
        """
        Canonical output over the span from the floor to the reference.

        Units follow the channel: volts for a voltage output, amperes for a
        current output. The value is `lower_bound` plus the code fraction times
        `reference - lower_bound`, so code 0 reaches the floor and the top code
        reaches the reference itself.

        :return: Scaled output, or None when the channel has no reference.
        """
        reference = self.reference
        if reference is None:
            return None
        lower = self.lower_bound
        level = lower + self._code_to_fraction(self.value) * (reference - lower)
        return min(max(level, lower), reference)

    @output.setter
    def output(self, output: float | None) -> None:
        """
        Set the output from a scaled value.

        The value is clamped into `lower_bound..reference` without an error, so
        a caller asking for slightly more than the reference gets the reference
        instead of a rejected write.

        :param output: Output in the channel unit (float).
        :raises TypeError: If `output` is not a real number, is a `bool`, or is
            None.
        :raises ValueError: If `output` is infinite or `NaN`.
        :raises DACReferenceError: If the channel has no reference, or its
            floor is not below the reference.
        """
        reference = self.reference
        if reference is None:
            raise DACReferenceError(
                f"Channel {self.index} has no reference configured; "
                "set the device reference or a channel override first"
            )
        lower = self.lower_bound
        span = reference - lower
        if span <= 0:
            raise DACReferenceError(
                f"Channel {self.index} has lower_bound {lower!r} "
                f"not below reference {reference!r}"
            )
        # None must reach check_number, which is what rejects it with TypeError.
        level = clamp(check_number(cast(float, output)), lower, reference)
        self.value = self._fraction_to_code((level - lower) / span)

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
        """Upper bound this channel maps the top code to."""
        return self.reference

    @v_ref.setter
    def v_ref(self, v_ref: float | None) -> None:
        """Set a per-channel upper bound, an alias of `reference_override`."""
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
        """Upper bound this channel maps the top code to, in amperes."""
        return self.reference

    @i_full_scale.setter
    def i_full_scale(self, i_full_scale: float | None) -> None:
        """Set a per-channel upper bound, an alias of `reference_override`."""
        self.reference_override = i_full_scale


class DividerChannel(VoltageChannel):
    """
    Voltage output of a resistor divider with one terminal grounded.

    Grounding B makes the output rise from the lower bound at code 0 to the
    reference at full code; grounding A mirrors that curve, so the output falls
    from the reference at code 0 to the lower bound at full code.
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


class GainChannel:
    """
    Voltage channel whose output span has a 1x/2x gain bit.

    A building block, not for direct instantiation: mix it in ahead of a
    channel class and it passes construction on through `super()`.
    `reference_override` (which `v_ref` writes) is the unscaled reference,
    while `reference` is the effective upper bound after gain, so changing gain
    moves `reference`, `output`, and the clamp bound but never the code.

    Gain scales the upper bound only, leaving `lower_bound` where it is, so
    combining a gain channel with a non-zero floor is not a supported span.
    """

    _GAINS: ClassVar[tuple[int, ...]] = (1, 2)
    """Gain factors the chip can select with its gain bit."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Pass construction on and start at the power-on gain."""
        super().__init__(*args, **kwargs)
        # The gain bit powers up at 0, which selects 2x.
        self._gain = 2

    @property
    def gain(self) -> int:
        """Selected gain factor."""
        return self._gain

    @gain.setter
    def gain(self, gain: int) -> None:
        """
        Select the gain factor without touching the bus.

        The bit only reaches the chip on the next code write, so the code and
        the cached shadow stay as they are.

        :param gain: Gain factor, one of `_GAINS` (int).
        :raises TypeError: If `gain` is not an integer number, or is a `bool`.
        :raises ValueError: If `gain` is not one of the supported factors.
        """
        self._gain = check_choice(gain, self._GAINS, "gain")

    @property
    def reference(self) -> float | None:
        """Effective upper bound: the unscaled reference times the gain."""
        # The next class in the bases is the channel this mixin augments.
        base = cast(DACChannel, super()).reference
        return None if base is None else base * self._gain


class BufferedChannel:
    """
    Voltage channel whose reference input can be buffered.

    A building block, not for direct instantiation: mix it in ahead of a
    channel class and it passes construction on through `super()`. It leaves
    the span rule alone: `reference_override` (and `v_ref`) stays the unscaled
    reference and `reference` the effective full scale after any gain.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Pass construction on and start with the buffer disabled."""
        super().__init__(*args, **kwargs)
        self._buffered = False

    @property
    def buffered(self) -> bool:
        """True when the chip buffers its reference input."""
        return self._buffered

    @buffered.setter
    def buffered(self, buffered: bool) -> None:
        """
        Switch the reference buffer, a chip-side bit the code ignores.

        :param buffered: Buffering state (bool).
        :raises TypeError: If `buffered` is not a bool.
        """
        self._buffered = check_bool(buffered)


class PowerDownChannel:
    """
    Voltage channel with a power-down field.

    A building block, not for direct instantiation: mix it in ahead of a
    channel class and it passes construction on through `super()`. It leaves
    the span rule alone: `reference_override` (and `v_ref`) stays the unscaled
    reference and `reference` the effective full scale after any gain.
    """

    _POWER_DOWN_CODES: ClassVar[frozenset[int]] = frozenset({0, 1, 2, 3})
    """Power-down modes the chip accepts; a single SHDN bit uses `{0, 1}`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Pass construction on and start in normal operation."""
        super().__init__(*args, **kwargs)
        self._power_down = 0

    @property
    def power_down(self) -> int:
        """Power-down mode, 0 meaning normal operation."""
        return self._power_down

    @power_down.setter
    def power_down(self, power_down: int) -> None:
        """
        Select the power-down mode without touching the bus.

        :param power_down: Mode, one of `_POWER_DOWN_CODES` (int).
        :raises TypeError: If `power_down` is not an integer number, or is a
            `bool`.
        :raises ValueError: If `power_down` is not one of the supported modes.
        """
        self._power_down = check_choice(
            power_down, self._POWER_DOWN_CODES, "power_down"
        )
