"""AD54x0 single-channel current-output converters."""

from collections.abc import Sequence
from typing import Any, NamedTuple, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import check_bool, check_choice, check_integer
from .__transport import open_transport
from .channel import CurrentChannel
from .dac import DAC
from .errors import DACOutputDisabledError, DACReadbackError

_ADDRESS_DATA = 0x01
"""Register address of the data word, in DB23..DB16 of the frame."""

_ADDRESS_READBACK = 0x02
"""Register address of a readback request."""

_ADDRESS_CONTROL = 0x55
"""Register address of the control word."""

_RESET_WORD = 0x560001
"""Frame that restores the power-on state."""

_READ_STATUS = 0b00
"""Readback address of the status register."""

_READ_DATA = 0b01
"""Readback address of the data register."""

_READ_CONTROL = 0b10
"""Readback address of the control register."""

_RANGES: dict[str, tuple[float, float, int]] = {
    "4-20mA": (0.020, 0.004, 0b101),
    "0-20mA": (0.020, 0.0, 0b110),
    "0-24mA": (0.024, 0.0, 0b111),
}
"""Range name mapped to upper full scale in A, lower bound in A, and code."""

_DEFAULT_RANGE = "4-20mA"
"""Range selected when an output is enabled before any `configure()`."""

_DATA_FIELD_BITS = 16
"""Width of the data field the code is left-aligned in."""

_REXT_BIT = 0x2000
"""DB13: the part uses an external 15 kOhm current-setting resistor."""

_OUTEN_BIT = 0x1000
"""DB12: the current output is enabled."""

_SR_ENABLED_BIT = 0x0010
"""DB4: the slew-rate controller is enabled."""

_DCEN_BIT = 0x0008
"""DB3: the daisy-chain output is enabled."""

_SLEW_CLOCKS = tuple(range(16))
"""Clock divider values the 4-bit slew clock field can express."""

_SLEW_STEPS = tuple(range(8))
"""Step sizes the 3-bit slew step field can express."""

_RANGE_CODES = tuple(range(8))
"""Values the 3-bit range field can express."""


class AD54x0Status(NamedTuple):
    """Fault flags decoded from the status register."""

    iout_fault: bool
    """True when the current output is in a fault condition."""

    slew_active: bool
    """True while a slew-limited step is still in progress."""

    overtemp: bool
    """True when the die temperature exceeds the limit."""


class AD54x0Control(NamedTuple):
    """Control register decoded field by field."""

    range_code: int
    """Range code in `0..7`; 5, 6, and 7 are the supported ranges."""

    rext: bool
    """True when an external current-setting resistor is selected."""

    outen: bool
    """True when the current output is enabled."""

    sr_clock: int
    """Slew-rate clock divider in `0..15`."""

    sr_step: int
    """Slew-rate step size in `0..7`."""

    sr_enabled: bool
    """True when the slew-rate controller is enabled."""

    dcen: bool
    """True when the daisy-chain output is enabled."""

    raw: int
    """Whole 24-bit word the fields were decoded from."""


def _control_field(  # noqa: PLR0913
    *,
    outen: bool,
    range_code: int,
    rext: bool = False,
    dcen: bool = False,
    sr_enabled: bool = False,
    sr_clock: int = 0,
    sr_step: int = 0,
) -> int:
    """
    Build the 16-bit control field of the control frame.

    The caller validates every argument; this function only lays the bits out.

    :param outen: True to set DB12 and enable the output (bool).
    :param range_code: Range code in `0..7` (int).
    :param rext: True to set DB13 and select an external resistor (bool).
    :param dcen: True to set DB3 and enable the daisy-chain output (bool).
    :param sr_enabled: True to set DB4 and enable slew control (bool).
    :param sr_clock: Slew clock divider in `0..15`, in DB11..DB8 (int).
    :param sr_step: Slew step size in `0..7`, in DB7..DB5 (int).
    :return: Control field, without the register address (int).
    """
    return (
        (_REXT_BIT if rext else 0)
        | (_OUTEN_BIT if outen else 0)
        | ((sr_clock & 0xF) << 8)
        | ((sr_step & 0x7) << 5)
        | (_SR_ENABLED_BIT if sr_enabled else 0)
        | (_DCEN_BIT if dcen else 0)
        | (range_code & 0x7)
    )


def encode_data(code: int, resolution: int) -> list[int]:
    """
    Encode one data write of an AD54x0 part as an SPI frame.

    The code is left-aligned in the 16-bit data field, so a 12-bit part wastes
    its low four bits instead of its high ones.

    :param code: Raw code; only its low `resolution` bits are used (int).
    :param resolution: Width of the code the part accepts, 1..16 (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If an argument is not an integer number, or is a `bool`.
    :raises ValueError: If `resolution` is outside `1..16`.
    """
    code = check_integer(code)
    resolution = check_integer(resolution)
    if not 1 <= resolution <= _DATA_FIELD_BITS:
        raise ValueError(
            f"Expected a resolution within 1..{_DATA_FIELD_BITS}, got {resolution}"
        )
    data = (code & ((1 << resolution) - 1)) << (_DATA_FIELD_BITS - resolution)
    return pack((_ADDRESS_DATA << 16) | data, 3)


def encode_control(  # noqa: PLR0913
    *,
    outen: bool,
    range_code: int,
    rext: bool = False,
    dcen: bool = False,
    sr_enabled: bool = False,
    sr_clock: int = 0,
    sr_step: int = 0,
) -> list[int]:
    """
    Encode one control write of an AD54x0 part as an SPI frame.

    The 24-bit word is the `0x55` register address followed by the 16-bit
    control field.

    :param outen: True to enable the current output (bool).
    :param range_code: Range code in `0..7` (int).
    :param rext: True to select an external current-setting resistor (bool).
    :param dcen: True to enable the daisy-chain output (bool).
    :param sr_enabled: True to enable the slew-rate controller (bool).
    :param sr_clock: Slew clock divider in `0..15` (int).
    :param sr_step: Slew step size in `0..7` (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If a flag is not a bool, or a field is not an integer
        number, or is a `bool`.
    :raises ValueError: If a field is outside the width it occupies.
    """
    outen = check_bool(outen)
    rext = check_bool(rext)
    dcen = check_bool(dcen)
    sr_enabled = check_bool(sr_enabled)
    sr_clock = check_choice(sr_clock, _SLEW_CLOCKS, "sr_clock")
    sr_step = check_choice(sr_step, _SLEW_STEPS, "sr_step")
    range_code = check_choice(range_code, _RANGE_CODES, "range_code")
    field = _control_field(
        outen=outen,
        range_code=range_code,
        rext=rext,
        dcen=dcen,
        sr_enabled=sr_enabled,
        sr_clock=sr_clock,
        sr_step=sr_step,
    )
    return pack((_ADDRESS_CONTROL << 16) | field, 3)


def encode_read_request(address: int) -> list[int]:
    """
    Encode a readback request for one register.

    :param address: Register to read: 0 status, 1 data, 2 control (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If `address` is not an integer number, or is a `bool`.
    :raises ValueError: If `address` is infinite, `NaN`, or fractional.
    """
    return pack(_ADDRESS_READBACK << 16 | (check_integer(address) & 0b11), 3)


def encode_nop() -> list[int]:
    """
    Encode the frame that clocks a pending readback answer out.

    :return: Three zero bytes (list of int).
    """
    return pack(0, 3)


def encode_reset() -> list[int]:
    """
    Encode the reset frame that restores the power-on state.

    :return: Frame bytes, most significant first (list of int).
    """
    return pack(_RESET_WORD, 3)


def decode_24(rx: Sequence[int], *, swap: bool = False) -> int:
    """
    Join a readback answer into one 24-bit word.

    A real transport answers a three-byte frame; a transport that coalesces the
    answer may hand over the whole word as a single element instead.

    :param rx: Received words, either three bytes or one word (Sequence of int).
    :param swap: True to treat the three bytes as little-endian (bool).
    :return: Received word in `0..2**24 - 1` (int).
    :raises TypeError: If `swap` is not a bool, or a word is not an integer.
    :raises DACReadbackError: If `rx` holds neither one nor three words.
    """
    swap = check_bool(swap)
    length = len(rx)
    if length == 1:
        return check_integer(rx[0]) & 0xFFFFFF
    if length != 3:
        raise DACReadbackError(
            f"Expected a 3-byte or 1-word readback, got {length} bytes"
        )
    words = [check_integer(word) for word in rx]
    if swap:
        words.reverse()
    return (words[0] << 16) | (words[1] << 8) | words[2]


class AD54x0Channel(CurrentChannel):
    """The single output of an AD54x0 converter."""

    def _write_code(self, code: int) -> int:
        """Delegate the write to the device, which owns the frame format."""
        return cast("AD54x0", self._dac)._write_code(self.index, code)

    def _read_code(self) -> int:
        """Delegate the readback to the device, which owns the frame format."""
        return cast("AD54x0", self._dac)._read_code(self.index)


class AD54x0(DAC):
    """
    Base class for the single-channel AD54x0 current-output converters.

    A part sources one current selected by the control word's range field:
    4-20 mA, 0-20 mA, or 0-24 mA. Construction opens the bus but sends nothing,
    so the part keeps its power-on state and `reference` stays None until
    `configure()` selects a range. `reference` is the upper full scale in
    amperes and the channel floor is the range's lower bound, so the affine
    `output` spans 4-20 mA or 0-20/0-24 mA depending on the range.

    The part also gates the output with OUTEN: while that bit is clear a code
    write changes the register but not the loop, so this class refuses the
    write with `DACOutputDisabledError` instead of pretending it took effect.
    `output` therefore reflects register intent only and is not evidence of the
    current on the loop while OUTEN is 0.

    Data is clocked in on the rising edge and changes on the falling edge, so
    the bus runs at SPI mode 0. A code readback costs two transactions: a read
    request followed by a NOP that clocks the register out.

    The control and status registers are readable as well; `read_control()`
    and `read_status()` decode them. The readback answer is shifted by
    `_READ_SHIFT`, because some board layouts position the data differently
    from the datasheet, and byte-swapped when `_READ_SWAP` is set.
    """

    _CHANNELS = 1
    _RESOLUTION: int
    _READABLE = True
    _SPI_MODE = 0
    _FIXED_REFERENCE = None
    _CHANNEL_CLASS = AD54x0Channel
    _DATA_SHIFT: int
    """Shift of the code inside the data field: 16 minus the resolution."""
    _READ_SHIFT = 0
    """Extra right shift applied to a data readback, for board calibration."""
    _READ_SWAP = False
    """True when the transport answers a readback in little-endian order."""

    def __init__(  # noqa: PLR0913
        self,
        channels: int | None = None,
        *,
        transport: SpiTransport | None = None,
        spi: SpiTransport | None = None,
        port: Any = None,
        device: Any = None,
        clock_pin: Any = None,
        mosi_pin: Any = None,
        miso_pin: Any = None,
        select_pin: Any = None,
        label: str | None = None,
        log_level: int | str | None = None,
    ) -> None:
        """
        Build the device and expose its output as a current channel.

        Nothing is transferred: the full scale is unknown until `configure()`
        picks a range, so no reference is accepted here.

        :param channels: Channel count, only 1 is valid (int | None).
        :param transport: SPI transport to use as is (SpiTransport | None).
        :param spi: Legacy alias for `transport`, used when `transport` is
            None (SpiTransport | None).
        :param port: spidev bus number, or the gpiozero SPI port.
        :param device: spidev chip-select line, or the gpiozero SPI device
            number.
        :param clock_pin: GPIO clock pin; any pin keyword selects the gpiozero
            backend.
        :param mosi_pin: GPIO MOSI pin; selects the gpiozero backend.
        :param miso_pin: GPIO MISO pin; selects the gpiozero backend.
        :param select_pin: GPIO chip-select pin; selects the gpiozero backend.
        :param label: Logger name, defaults to the class name (str).
        :param log_level: Logging level such as `logging.DEBUG`; defaults to
            `logging.ERROR`.
        :raises TypeError: If `label` has the wrong type.
        :raises ValueError: If `label` is empty, or `channels` is outside 1..1.
        :raises ImportError: If the optional package for the selected backend
            is missing.
        """
        # Validate everything the caller can get wrong before the bus opens, so
        # a rejected keyword never touches /dev/spidev*. The channel-count rule
        # mirrors `DAC.__init__`, which runs only after the transport exists.
        count = self._CHANNELS if channels is None else check_integer(channels)
        if not 1 <= count <= self._CHANNELS:
            raise ValueError(
                f"Expected a channel count within 1..{self._CHANNELS}, got {count}"
            )
        self._control_word = 0
        self._output_enabled = False
        transport = open_transport(
            mode=self._SPI_MODE,
            transport=transport,
            spi=spi,
            port=port,
            device=device,
            clock_pin=clock_pin,
            mosi_pin=mosi_pin,
            miso_pin=miso_pin,
            select_pin=select_pin,
        )
        try:
            super().__init__(
                backend=transport,
                reference=None,
                channel_count=count,
                label=label,
                log_level=log_level,
            )
        except BaseException:
            # This constructor opened the transport; release it when the DAC
            # layer rejects a later keyword.
            transport.close()
            raise

    def configure(  # noqa: PLR0913
        self,
        *,
        range: str = "4-20mA",
        slew: bool = False,
        sr_clock: int = 0,
        sr_step: int = 0,
        rext: bool = False,
        dcen: bool = False,
        force: bool = False,
    ) -> None:
        """
        Select the current range and the remaining control-word fields.

        The current output-enable state is kept, so a range change never
        disables the output. The word is compared with the cached one: an
        unchanged configuration issues no transfer unless `force` is set.

        :param range: Output range, `"4-20mA"`, `"0-20mA"`, or `"0-24mA"`
            (str).
        :param slew: True to enable the slew-rate controller (bool).
        :param sr_clock: Slew clock divider in `0..15` (int).
        :param sr_step: Slew step size in `0..7` (int).
        :param rext: True to select an external current-setting resistor (bool).
        :param dcen: True to enable the daisy-chain output (bool).
        :param force: True to send the word even when it is unchanged (bool).
        :raises TypeError: If a flag is not a bool, or a field is not an
            integer number.
        :raises ValueError: If `range` is not a supported name, or a field is
            outside its width.
        """
        if not isinstance(range, str):
            raise TypeError(
                f"Expected a range name, got {range!r} of type {type(range)}"
            )
        if range not in _RANGES:
            allowed = ", ".join(_RANGES)
            raise ValueError(f"Expected range to be one of {allowed}, got {range!r}")
        slew = check_bool(slew)
        rext = check_bool(rext)
        dcen = check_bool(dcen)
        force = check_bool(force)
        sr_clock = check_choice(sr_clock, _SLEW_CLOCKS, "sr_clock")
        sr_step = check_choice(sr_step, _SLEW_STEPS, "sr_step")
        upper, lower, range_code = _RANGES[range]
        field = _control_field(
            outen=self._output_enabled,
            range_code=range_code,
            rext=rext,
            dcen=dcen,
            sr_enabled=slew,
            sr_clock=sr_clock,
            sr_step=sr_step,
        )
        if field != self._control_word or force:
            self._write_control(field)
        self._apply_span(upper, lower)

    def enable_output(self, *, force: bool = False) -> None:
        """
        Set OUTEN so the next code write reaches the loop.

        Calling it on an enabled output is a no-op unless `force` is set. With
        no configured range, the default 4-20 mA range is selected so the frame
        stays valid and `output` is never None while the output is enabled.

        :param force: True to send the word even when it is unchanged (bool).
        :raises TypeError: If `force` is not a bool.
        """
        force = check_bool(force)
        if self._output_enabled and not force:
            return
        if self._control_word == 0:
            upper, lower, range_code = _RANGES[_DEFAULT_RANGE]
            self._apply_span(upper, lower)
            self._write_control(_control_field(outen=True, range_code=range_code))
        else:
            self._write_control(self._control_word | _OUTEN_BIT)
        self._output_enabled = True

    def disable_output(self, *, force: bool = False) -> None:
        """
        Clear OUTEN without losing the configured range.

        Calling it on a disabled output is a no-op unless `force` is set.

        :param force: True to send the word even when it is unchanged (bool).
        :raises TypeError: If `force` is not a bool.
        """
        force = check_bool(force)
        if not self._output_enabled and not force:
            return
        if self._control_word == 0:
            # Force-disabling a device that never selected a range still has to
            # send a word with a valid range code.
            _, _, range_code = _RANGES[_DEFAULT_RANGE]
            field = _control_field(outen=False, range_code=range_code)
        else:
            field = self._control_word
        self._write_control(field & ~_OUTEN_BIT)
        self._output_enabled = False

    def reset(self) -> None:
        """
        Reset the device and forget every shadow field.

        The hardware RESET pin has the same effect, and a reset it causes is
        invisible to this object: `_control_word` and `_output_enabled` then
        describe a state the device no longer holds, so `configure()` and
        `enable_output()` accept `force=True` to re-send their word.
        """
        self.transport.transfer(encode_reset())
        self._control_word = 0
        self._output_enabled = False
        self.reference = None
        self._LOWER_BOUND = 0.0
        for channel in self.channels:
            channel.lower_bound = 0.0

    def read_status(self) -> AD54x0Status:
        """
        Read and decode the status register.

        :return: Fault flags of the part (AD54x0Status).
        """
        raw = self._read_register(_READ_STATUS)
        return AD54x0Status(
            iout_fault=bool(raw & 0b100),
            slew_active=bool(raw & 0b010),
            overtemp=bool(raw & 0b001),
        )

    def read_control(self) -> AD54x0Control:
        """
        Read and decode the control register.

        :return: Control fields and the raw word (AD54x0Control).
        """
        raw = self._read_register(_READ_CONTROL)
        return AD54x0Control(
            range_code=raw & 0b111,
            rext=bool(raw & _REXT_BIT),
            outen=bool(raw & _OUTEN_BIT),
            sr_clock=(raw >> 8) & 0xF,
            sr_step=(raw >> 5) & 0x7,
            sr_enabled=bool(raw & _SR_ENABLED_BIT),
            dcen=bool(raw & _DCEN_BIT),
            raw=raw,
        )

    def _write_code(self, index: int, code: int) -> int:
        """
        Send one code, refusing while the output is disabled.

        The guard runs before the transfer, so a disabled output issues no bus
        traffic at all.

        :param index: Channel index, 0 (int).
        :param code: Raw code already validated by the channel.
        :return: Code that was written.
        :raises DACOutputDisabledError: If OUTEN is clear.
        """
        if not self._output_enabled:
            raise DACOutputDisabledError(
                f"Channel {index} output is disabled; "
                "call enable_output() before writing a code"
            )
        self.transport.transfer(encode_data(code, self.resolution))
        return code

    def _read_code(self, index: int) -> int:
        """
        Read the data register and shift its code field into range.

        A readback is allowed while the output is disabled.

        :param index: Channel index, 0 (int).
        :return: Code in `0..max_code`.
        """
        raw = self._read_register(_READ_DATA)
        return (raw >> (self._READ_SHIFT + self._DATA_SHIFT)) & self.max_code

    def _read_register(self, address: int) -> int:
        """
        Request one register, clock the answer out, and decode the word.

        :param address: Register to read: 0 status, 1 data, 2 control (int).
        :return: Received 24-bit word.
        """
        self.transport.transfer(encode_read_request(address))
        return decode_24(self.transport.transfer(encode_nop()), swap=self._READ_SWAP)

    def _write_control(self, field: int) -> None:
        """
        Send a control field and remember it as the shadow.

        :param field: Validated 16-bit control field (int).
        """
        self.transport.transfer(pack((_ADDRESS_CONTROL << 16) | field, 3))
        self._control_word = field

    def _apply_span(self, upper: float, lower: float) -> None:
        """
        Point the affine model at a new range.

        :param upper: Upper full scale in amperes (float).
        :param lower: Floor code 0 maps to in amperes (float).
        """
        self.reference = upper
        self._LOWER_BOUND = lower
        for channel in self.channels:
            channel.lower_bound = lower


class AD5410(AD54x0):
    """Single 12-bit 4-20/0-20/0-24 mA current source."""

    _RESOLUTION = 12
    _DATA_SHIFT = 4


class AD5420(AD54x0):
    """Single 16-bit 4-20/0-20/0-24 mA current source."""

    _RESOLUTION = 16
    _DATA_SHIFT = 0
