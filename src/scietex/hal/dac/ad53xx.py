"""AD53xx dual converters with per-channel external references."""

from collections.abc import Sequence
from typing import Any, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import (
    check_bool,
    check_choice,
    check_integer,
    check_positive,
    check_reference,
)
from .__transport import open_transport
from .channel import BufferedChannel, PowerDownChannel, VoltageChannel
from .dac import DAC

_CHANNEL_BIT = 0x8000
"""A/B bit: set targets channel B, clear targets channel A."""

_BUFFER_BIT = 0x4000
"""BUF bit: set buffers the reference input of the addressed channel."""

_DATA_BITS = 12
"""Width of the data field; an 8- or 10-bit code is left-aligned in it."""

_POWER_DOWN_SHIFT = 12
"""PD1..PD0 occupy bits 13..12, directly above the data field."""

_POWER_DOWN_MODES = (0, 1, 2, 3)
"""Two-bit PD field: normal, 1k to GND, 100k to GND, and high impedance."""


def encode_write(
    bits: int, index: int, code: int, *, buffered: bool, power_down: int
) -> list[int]:
    """
    Encode one channel write of an AD53xx part as an SPI frame.

    The 16-bit word is the channel bit, the buffer bit, the two power-down bits,
    and the code left-aligned in the 12-bit data field, so an 8- or 10-bit part
    wastes its low bits instead of its high ones.

    :param bits: Resolution of the part: 8, 10, or 12 (int).
    :param index: Channel index, 0 or 1 (int).
    :param code: Raw code; only its low `bits` bits are used (int).
    :param buffered: True to buffer the reference input (bool).
    :param power_down: Two-bit power-down mode, 0..3 (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If an argument is not an integer number, a `bool` where a
        number is expected, or not a `bool` for `buffered`.
    :raises ValueError: If `bits` is outside `1..12`, or a field value is not
        one the part supports.
    """
    bits = check_integer(bits)
    if not 1 <= bits <= _DATA_BITS:
        raise ValueError(f"Expected a resolution within 1..{_DATA_BITS}, got {bits}")
    index = check_choice(index, (0, 1), "channel index")
    code = check_integer(code)
    buffered = check_bool(buffered)
    power_down = check_choice(power_down, _POWER_DOWN_MODES, "power_down")
    word = (
        (_CHANNEL_BIT if index else 0)
        | (_BUFFER_BIT if buffered else 0)
        | (power_down << _POWER_DOWN_SHIFT)
        | ((code & ((1 << bits) - 1)) << (_DATA_BITS - bits))
    )
    return pack(word, 2)


def _resolve_reference(
    reference: float | Sequence[float] | None, channel_count: int
) -> tuple[float | None, tuple[float, ...] | None]:
    """
    Split a constructor `reference` into a device value and channel overrides.

    A scalar is the full scale of the whole device. A sequence holds one value
    per channel: it becomes a `reference_override` on each channel and leaves
    the device itself without a reference, so a channel keeps its own VREF.

    :param reference: Scalar reference, per-channel sequence, or None.
    :param channel_count: Number of channels the device will expose (int).
    :return: Device reference and the per-channel overrides, or None for each
        when that form was not given (tuple).
    :raises TypeError: If `reference` is neither a real number nor a sequence of
        real numbers, or an element is not a positive real number.
    :raises ValueError: If `reference` is not positive, or the sequence length
        differs from `channel_count`.
    """
    if reference is None:
        return None, None
    if isinstance(reference, Sequence) and not isinstance(reference, (str, bytes)):
        values = tuple(float(check_positive(value)) for value in reference)
        if len(values) != channel_count:
            raise ValueError(f"Expected {channel_count} references, got {len(values)}")
        return None, values
    return check_reference(cast("float | None", reference)), None


class AD53xxChannel(BufferedChannel, PowerDownChannel, VoltageChannel):
    """One output of an AD53xx converter."""

    def _write_code(self, code: int) -> int:
        """Encode the code with the current channel fields and send one frame."""
        dac = cast("AD53xx", self._dac)
        self._dac.transport.transfer(
            encode_write(
                dac.resolution,
                self.index,
                code,
                buffered=self.buffered,
                power_down=self.power_down,
            )
        )
        return code


class AD53xx(DAC):
    """
    Base class for the dual-channel AD53xx converters.

    The parts have no reference of their own: AD5302, AD5312, and AD5322 take
    external VREFA and VREFB rails, so `reference` is either a scalar for the
    whole device or a per-channel sequence that becomes a `reference_override`.
    Either form is validated before the bus opens, so a rejected keyword never
    touches `/dev/spidev*`.

    `buffered` switches the BUF bit that buffers the addressed channel's
    reference input, and `power_down` selects one of the four two-bit PD modes.
    Both are applied to every channel and only reach the chip with the next code
    write, because they live in the command word.

    The device is write-only and clocks data in on the falling SCLK edge, so the
    bus runs at SPI mode 1. A write reaches the output only while LDAC is low:
    the package does not drive that pin, so with LDAC floating or held high the
    input register accepts the code but the DAC register, and therefore the
    output, latches it only on a subsequent LDAC pulse.
    """

    _CHANNELS = 2
    _RESOLUTION: int
    _READABLE = False
    _FIXED_REFERENCE = None
    _SPI_MODE = 1
    _CHANNEL_CLASS = AD53xxChannel

    def __init__(  # noqa: PLR0913
        self,
        channels: int | None = None,
        *,
        reference: float | Sequence[float] | None = None,
        buffered: bool | None = None,
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
        :param reference: Full-scale voltage in volts for the whole device, one
            value per channel, or None while unknown
            (float | Sequence of float | None).
        :param buffered: True to buffer the reference input on every channel;
            None keeps the unbuffered power-on state (bool | None).
        :param power_down: Two-bit power-down mode, 0..3; None keeps the normal
            power-on state (int | None).
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
        :raises TypeError: If `reference` holds an element that is not a
            positive real number, or `buffered`, `power_down`, or `label` has
            the wrong type.
        :raises ValueError: If `reference` is not positive, the sequence length
            differs from the channel count, `power_down` is not 0..3, `label` is
            empty, or `channels` is outside `1..2`.
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
        device_reference, overrides = _resolve_reference(reference, count)
        buffered = None if buffered is None else check_bool(buffered)
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
                reference=device_reference,
                channel_count=count,
                label=label,
                log_level=log_level,
            )
            if overrides is not None:
                for channel, value in zip(self.channels, overrides, strict=True):
                    channel.reference_override = value
            for channel in cast("tuple[AD53xxChannel, ...]", self.channels):
                if buffered is not None:
                    channel.buffered = buffered
                if power_down is not None:
                    channel.power_down = power_down
        except BaseException:
            # This constructor opened the transport; release it when the DAC
            # layer rejects a later keyword.
            transport.close()
            raise


class AD5302(AD53xx):
    """Dual 8-bit converter with an external reference."""

    _RESOLUTION = 8


class AD5312(AD53xx):
    """Dual 10-bit converter with an external reference."""

    _RESOLUTION = 10


class AD5322(AD53xx):
    """Dual 12-bit converter with an external reference."""

    _RESOLUTION = 12
