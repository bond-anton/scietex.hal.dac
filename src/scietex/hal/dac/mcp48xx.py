"""MCP48xx digital-to-analog converters with an internal reference."""

from typing import Any, ClassVar, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import check_choice, check_integer, check_reference
from .__transport import open_transport
from .channel import GainChannel, PowerDownChannel, VoltageChannel
from .dac import DAC

_CHANNEL_BIT = 0x8000
"""A/B bit: set selects the second channel."""

_GAIN_BIT = 0x2000
"""GA bit: set selects 1x, clear selects the 2x power-on state."""

_ACTIVE_BIT = 0x1000
"""SHDN bit: set keeps the channel active, clear powers it down."""

_DATA_BITS = 12
"""Width of the data field; an 8- or 10-bit code is left-aligned in it."""

_GAIN_FACTORS = (1, 2)
_POWER_DOWN_MODES = (0, 1)


def encode_write(
    bits: int, index: int, code: int, *, gain: int, power_down: int
) -> list[int]:
    """
    Encode one channel write of an MCP48xx part as an SPI frame.

    The frame carries the channel, gain, and shutdown bits ahead of the code,
    which sits left-aligned in the 12-bit data field so an 8- or 10-bit part
    wastes its low bits instead of its high ones.

    :param bits: Resolution of the part: 8, 10, or 12 (int).
    :param index: Channel index, 0 or 1 (int).
    :param code: Raw code; only its low `bits` bits are used (int).
    :param gain: Gain factor, 1 or 2 (int).
    :param power_down: 0 for normal operation, 1 for shutdown (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If an argument is not an integer number, or is a `bool`.
    :raises ValueError: If `bits` is outside `1..12`, or a field value is not
        one the part supports.
    """
    bits = check_integer(bits)
    if not 1 <= bits <= _DATA_BITS:
        raise ValueError(f"Expected a resolution within 1..{_DATA_BITS}, got {bits}")
    index = check_choice(index, (0, 1), "channel index")
    code = check_integer(code)
    gain = check_choice(gain, _GAIN_FACTORS, "gain")
    power_down = check_choice(power_down, _POWER_DOWN_MODES, "power_down")
    word = (
        (index << 15)
        | (_GAIN_BIT if gain == 1 else 0)
        | (_ACTIVE_BIT if power_down == 0 else 0)
        | ((code & ((1 << bits) - 1)) << (_DATA_BITS - bits))
    )
    return pack(word, 2)


class MCP48xxChannel(GainChannel, PowerDownChannel, VoltageChannel):
    """One output of an MCP48xx converter."""

    _POWER_DOWN_CODES: ClassVar[frozenset[int]] = frozenset(_POWER_DOWN_MODES)
    """A single SHDN bit, so only normal operation and shutdown are selectable."""

    def _write_code(self, code: int) -> int:
        """Encode the code with the current channel fields and send one frame."""
        dac = cast("MCP48xx", self._dac)
        self._dac.transport.transfer(
            encode_write(
                dac.resolution,
                self.index,
                code,
                gain=self.gain,
                power_down=self.power_down,
            )
        )
        return code


class MCP48xx(DAC):
    """
    Base class for the dual-channel MCP48xx converters.

    The parts run from an internal 2.048 V reference and have no VREF pin, so
    the full scale is fixed and a conflicting `reference` is rejected before
    the bus opens. The registers power up at zero, which is why the shadow code
    of a freshly built channel is already correct.

    `gain` and `power_down` are applied to every channel and only reach the chip
    with the next code write, because both live in the command frame.
    """

    _CHANNELS = 2
    _RESOLUTION: int
    _READABLE = False
    _FIXED_REFERENCE = 2.048
    _SPI_MODE = 0
    _CHANNEL_CLASS = MCP48xxChannel

    def __init__(  # noqa: PLR0913
        self,
        channels: int | None = None,
        *,
        reference: float | None = None,
        gain: int | None = None,
        power_down: int | None = None,
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
        Build the device and expose its outputs as voltage channels.

        :param channels: Channel count, 1..2; None uses every channel the part
            provides (int | None).
        :param reference: Full-scale voltage in volts; only 2.048 or None is
            accepted (float | None).
        :param gain: Gain factor applied to every channel, 1 or 2; None keeps
            the 2x power-on state (int | None).
        :param power_down: 0 for normal operation, 1 for shutdown; None keeps
            the active power-on state (int | None).
        :param transport: SPI transport to use as is (SpiTransport | None).
        :param spi: Legacy alias for `transport`, used when `transport` is
            None (SpiTransport | None).
        :param port: spidev bus number, used when no transport is supplied.
        :param device: spidev chip-select line, used when no transport is
            supplied.
        :param clock_pin: GPIO clock pin; any pin keyword selects the gpiozero
            backend.
        :param mosi_pin: GPIO MOSI pin; selects the gpiozero backend.
        :param miso_pin: GPIO MISO pin; selects the gpiozero backend.
        :param select_pin: GPIO chip-select pin; selects the gpiozero backend.
        :param label: Logger name, defaults to the class name (str).
        :param log_level: Logging level such as `logging.DEBUG`; defaults to
            `logging.ERROR`.
        :raises TypeError: If `reference`, `gain`, `power_down`, or `label` has
            the wrong type.
        :raises ValueError: If `reference` conflicts with the internal full
            scale, `gain` or `power_down` is not a supported value, `label` is
            empty, or `channels` is outside `1..2`.
        :raises ImportError: If the optional package for the selected backend
            is missing.
        """
        # The part has no VREF pin: reject a conflicting full scale before the
        # bus opens, so a rejected keyword never touches /dev/spidev*.
        self._check_fixed_reference(check_reference(reference))
        gain = None if gain is None else check_choice(gain, _GAIN_FACTORS, "gain")
        power_down = (
            None
            if power_down is None
            else check_choice(power_down, _POWER_DOWN_MODES, "power_down")
        )
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
                reference=reference,
                channel_count=channels,
                label=label,
                log_level=log_level,
            )
            for channel in cast("tuple[MCP48xxChannel, ...]", self.channels):
                if gain is not None:
                    channel.gain = gain
                if power_down is not None:
                    channel.power_down = power_down
        except BaseException:
            # This constructor opened the transport; release it when the DAC
            # layer rejects a later keyword.
            transport.close()
            raise


class MCP4802(MCP48xx):
    """Dual 8-bit converter with an internal 2.048 V reference."""

    _RESOLUTION = 8


class MCP4812(MCP48xx):
    """Dual 10-bit converter with an internal 2.048 V reference."""

    _RESOLUTION = 10


class MCP4822(MCP48xx):
    """Dual 12-bit converter with an internal 2.048 V reference."""

    _RESOLUTION = 12
