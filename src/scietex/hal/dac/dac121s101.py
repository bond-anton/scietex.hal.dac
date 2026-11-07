"""DAC121S101 12-bit converter whose supply rail is also its reference."""

from typing import Any, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import check_choice, check_integer, check_reference
from .__transport import open_transport
from .channel import PowerDownChannel, VoltageChannel
from .dac import DAC

_POWER_DOWN_MODES = (0, 1, 2, 3)
"""Two-bit PD field: normal, 1k to GND, 100k to GND, and high impedance."""


def encode_write(code: int, *, power_down: int) -> list[int]:
    """
    Encode one channel write of a DAC121S101 as an SPI frame.

    The 16-bit word is two don't-care bits, the two power-down bits, and the
    12-bit code.

    :param code: Raw code in the 12-bit data field (int).
    :param power_down: Two-bit power-down mode, 0..3 (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If an argument is not an integer number, or is a `bool`.
    :raises ValueError: If `power_down` is outside 0..3, or `code` does not fit
        in the 16-bit word.
    """
    code = check_integer(code)
    power_down = check_choice(power_down, _POWER_DOWN_MODES, "power_down")
    return pack((power_down << 12) | code, 2)


class DAC121S101Channel(PowerDownChannel, VoltageChannel):
    """One output of a DAC121S101 converter."""

    def _write_code(self, code: int) -> int:
        """Encode the code with the current power-down field and send one frame."""
        self._dac.transport.transfer(encode_write(code, power_down=self.power_down))
        return code


class DAC121S101(DAC):
    """
    Single 12-bit converter that runs from its own supply rail.

    There is no separate VREF pin: VA is both the supply and the full scale, so
    `reference` is the rail voltage and the output can never exceed it. While
    the rail voltage is unknown `reference` stays None and `output` is None.

    The part is write-only and clocks data in on the falling SCLK edge, so the
    bus runs at SPI mode 1. `power_down` is a two-bit field that only reaches
    the chip with the next code write.
    """

    _CHANNELS = 1
    _RESOLUTION = 12
    _READABLE = False
    _FIXED_REFERENCE = None
    _SPI_MODE = 1
    _CHANNEL_CLASS = DAC121S101Channel

    def __init__(  # noqa: PLR0913
        self,
        channels: int | None = None,
        *,
        reference: float | None = None,
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
        Build the device and expose its output as a voltage channel.

        :param channels: Channel count, only 1 is valid (int | None).
        :param reference: Supply-rail voltage in volts, which is also the full
            scale, or None while it is unknown (float | None).
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
        :raises TypeError: If `reference`, `power_down`, or `label` has the
            wrong type.
        :raises ValueError: If `reference` is not positive, `power_down` is not
            0..3, `label` is empty, or `channels` is outside 1..1.
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
        reference = check_reference(reference)
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
                channel_count=count,
                label=label,
                log_level=log_level,
            )
            if power_down is not None:
                for channel in cast("tuple[PowerDownChannel, ...]", self.channels):
                    channel.power_down = power_down
        except BaseException:
            # This constructor opened the transport; release it when the DAC
            # layer rejects a later keyword.
            transport.close()
            raise
