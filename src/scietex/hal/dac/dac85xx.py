"""DAC85xx converters with an external reference and a two-bit power-down field."""

from collections.abc import Sequence
from typing import Any, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import check_choice, check_integer, check_positive, check_reference
from .__transport import open_transport
from .channel import PowerDownChannel, VoltageChannel
from .dac import DAC

_LDA_BIT = 0x10
"""DB20 load DAC A: set when the frame targets channel 0."""

_LDB_BIT = 0x20
"""DB21 load DAC B: set when the frame targets channel 1."""

_DATA_BUFFER_BIT = 0x04
"""DB18 buffer select: 0 loads data buffer A, 1 loads data buffer B.

It selects which data buffer accepts the code, not the reference input, so it
follows the channel bit and never becomes a `buffered` property.
"""

_POWER_DOWN_MODES = (0, 1, 2, 3)
"""Two-bit PD field: normal, 1k to GND, 100k to GND, and high impedance."""


def encode_write(code: int, *, power_down: int) -> list[int]:
    """
    Encode one channel write of a single-channel DAC85xx part as an SPI frame.

    The 24-bit frame is six don't-care bits, the two power-down bits, and the
    16-bit code, most significant bit first.

    :param code: Raw code in the 16-bit data field (int).
    :param power_down: Two-bit power-down mode, 0..3 (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If an argument is not an integer number, or is a `bool`.
    :raises ValueError: If `power_down` is outside 0..3, or `code` does not fit
        in the 24-bit frame.
    """
    code = check_integer(code)
    power_down = check_choice(power_down, _POWER_DOWN_MODES, "power_down")
    return pack((power_down << 16) | code, 3)


def encode_write_8552(index: int, code: int, *, power_down: int) -> list[int]:
    """
    Encode one channel write of a DAC8552 as an SPI frame.

    The 24-bit frame is the two load bits, a don't-care bit, the buffer-select
    bit, the two power-down bits, and the 16-bit code. The load and buffer bits
    together select the channel, so channel 0 starts with `0x10` and channel 1
    with `0x24`; the power-down field is DB17..DB16, directly above the code.

    :param index: Channel index, 0 or 1 (int).
    :param code: Raw code in the 16-bit data field (int).
    :param power_down: Two-bit power-down mode, 0..3 (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If an argument is not an integer number, or is a `bool`.
    :raises ValueError: If `index` is not 0 or 1, `power_down` is outside 0..3,
        or `code` does not fit in the 24-bit frame.
    """
    index = check_choice(index, (0, 1), "channel index")
    code = check_integer(code)
    power_down = check_choice(power_down, _POWER_DOWN_MODES, "power_down")
    load = _LDA_BIT if index == 0 else _LDB_BIT | _DATA_BUFFER_BIT
    # PD1 and PD0 sit at DB17 and DB16, directly above the data field.
    control = load | power_down
    return pack((control << 16) | code, 3)


def _resolve_reference(
    reference: float | Sequence[float] | None,
    channel_count: int,
    *,
    per_channel: bool,
) -> tuple[float | None, tuple[float, ...] | None]:
    """
    Split a constructor `reference` into a device value and channel overrides.

    A scalar is the full scale of the whole device. On a dual part a sequence
    holds one value per channel: it becomes a `reference_override` on each
    channel and leaves the device itself without a reference, so a channel
    keeps its own VREF. The single-channel parts have no per-channel VREF to
    distinguish, so they reject a sequence instead of silently unwrapping it.

    :param reference: Scalar reference, per-channel sequence, or None.
    :param channel_count: Number of channels the device will expose (int).
    :param per_channel: True when the part has one reference input per channel
        (bool).
    :return: Device reference and the per-channel overrides, or None for each
        when that form was not given (tuple).
    :raises TypeError: If `reference` is neither a real number nor a sequence of
        real numbers, an element is not a positive real number, or a sequence
        is given for a single-channel part.
    :raises ValueError: If `reference` is not positive, or the sequence length
        differs from `channel_count`.
    """
    if reference is None:
        return None, None
    if isinstance(reference, Sequence) and not isinstance(reference, (str, bytes)):
        if not per_channel:
            raise TypeError(
                "A single-channel part takes one reference, not a per-channel "
                f"sequence; got {reference!r}"
            )
        values = tuple(float(check_positive(value)) for value in reference)
        if len(values) != channel_count:
            raise ValueError(f"Expected {channel_count} references, got {len(values)}")
        return None, values
    return check_reference(cast("float | None", reference)), None


class DAC85xxChannel(PowerDownChannel, VoltageChannel):
    """One output of a single-channel DAC85xx converter."""

    def _write_code(self, code: int) -> int:
        """Encode the code with the current power-down field and send one frame."""
        self._dac.transport.transfer(encode_write(code, power_down=self.power_down))
        return code


class DAC8552Channel(PowerDownChannel, VoltageChannel):
    """One output of a dual DAC8552 converter."""

    def _write_code(self, code: int) -> int:
        """Encode the code with its channel and power-down field, then send it."""
        self._dac.transport.transfer(
            encode_write_8552(self.index, code, power_down=self.power_down)
        )
        return code


class DAC85xx(DAC):
    """
    Base class for the external-reference DAC85xx converters.

    The parts are write-only and clock data in on the falling SCLK edge, so the
    bus runs at SPI mode 1. They have no reference of their own: a scalar
    `reference` is the VREF of the whole device, and on the dual part a
    per-channel sequence becomes a `reference_override` instead.

    `power_down` is a two-bit field applied to every channel and only reaches
    the chip with the next code write, because it lives in the command frame.

    The dual part's DB18 bit selects the data buffer (A or B) rather than the
    reference input, so this family has no `buffered` property.
    """

    _READABLE = False
    _FIXED_REFERENCE = None
    _SPI_MODE = 1
    _CHANNEL_CLASS = DAC85xxChannel

    def __init__(  # noqa: PLR0913
        self,
        channels: int | None = None,
        *,
        reference: float | Sequence[float] | None = None,
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
            value per channel, or None while unknown. Only a dual part accepts
            the sequence form (float | Sequence of float | None).
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
            positive real number, a sequence is given to a single-channel part,
            or `power_down` or `label` has the wrong type.
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
        device_reference, overrides = _resolve_reference(
            reference, count, per_channel=self._CHANNELS > 1
        )
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
            if power_down is not None:
                for channel in cast("tuple[PowerDownChannel, ...]", self.channels):
                    channel.power_down = power_down
        except BaseException:
            # This constructor opened the transport; release it when the DAC
            # layer rejects a later keyword.
            transport.close()
            raise


class DAC8531(DAC85xx):
    """Single 16-bit converter with an external reference."""

    _CHANNELS = 1
    _RESOLUTION = 16


class DAC8551(DAC85xx):
    """Single 16-bit converter with an external reference.

    The command frame is identical to the DAC8531; only the datasheet differs.
    """

    _CHANNELS = 1
    _RESOLUTION = 16


class DAC8552(DAC85xx):
    """Dual 16-bit converter with an external reference."""

    _CHANNELS = 2
    _RESOLUTION = 16
    _CHANNEL_CLASS = DAC8552Channel
