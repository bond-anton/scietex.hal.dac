"""AD7390 and AD7391 converters with an external reference and a load strobe."""

from typing import Any, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import check_integer, check_reference
from .__strobe import GpiozeroStrobe, LoadStrobe, StrobedBackend
from .__transport import open_transport
from .channel import VoltageChannel
from .dac import DAC
from .errors import DACStrobeError


def encode_write(bits: int, code: int) -> list[int]:
    """
    Encode one channel write of an AD739x part as an SPI frame.

    The part clocks a two-byte frame in MSB first and ignores the leading bits,
    so only the last `bits` bits of the code reach the register. The frame is
    byte aligned regardless of the resolution.

    :param bits: Resolution of the part: 10 or 12 (int).
    :param code: Raw code; only its low `bits` bits are used (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If `code` is not an integer number, or is a `bool`.
    :raises ValueError: If `code` does not fit in the 16-bit frame after
        masking.
    """
    return pack(code & ((1 << bits) - 1), 2)


class AD739xChannel(VoltageChannel):
    """The single output of an AD739x converter."""

    def _write_code(self, code: int) -> int:
        """Send the code, then pulse the load line to latch it."""
        dac = cast("AD739x", self._dac)
        backend = cast("StrobedBackend", dac._backend)
        backend.transfer(encode_write(dac.resolution, code))
        backend.strobe.pulse()
        return code


class AD739x(DAC):
    """
    Base class for the single-channel AD739x converters.

    Both parts are write-only and clock data in on the rising CLK edge, so the
    bus runs at SPI mode 0. The CLK pin is enabled only while LD is high: the
    load line must idle HIGH, stay high while the frame is clocked, and then be
    pulsed low and high to latch it. Clocking with LD low does nothing.

    The frame is MSB first and the part ignores leading bits, so the last 12
    bits (AD7390) or 10 bits (AD7391) clocked in select the code. A byte-aligned
    two-byte frame is enough, and `encode_write` masks the code to the part
    width.

    The parts have no reference of their own: `reference` is the external VREF
    as a plain scalar, and stays None while it is unknown.
    """

    _CHANNELS = 1
    _RESOLUTION: int
    _READABLE = False
    _FIXED_REFERENCE = None
    _SPI_MODE = 0
    _CHANNEL_CLASS = AD739xChannel

    def __init__(  # noqa: PLR0913
        self,
        channels: int | None = None,
        *,
        reference: float | None = None,
        strobe: LoadStrobe | None = None,
        load_pin: int | None = None,
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

        The constructor takes ownership of `strobe`, or builds a
        `GpiozeroStrobe` from `load_pin`, and releases it with the transport
        when construction fails or the device is closed.

        :param channels: Channel count, only 1 is valid (int | None).
        :param reference: External VREF in volts, or None while unknown
            (float | None).
        :param strobe: Load strobe that latches each frame (LoadStrobe | None).
        :param load_pin: GPIO pin of the load line; builds a `GpiozeroStrobe`
            when `strobe` is None (int | None).
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
        :raises DACStrobeError: If neither `strobe` nor `load_pin` is given.
        :raises ValueError: If both are given, `reference` is not positive,
            `label` is empty, or `channels` is outside 1..1.
        :raises TypeError: If `reference`, `label`, or `pulse_width` has the
            wrong type.
        :raises ImportError: If the optional package for the selected backend
            or the strobe is missing.
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
        if strobe is not None and load_pin is not None:
            raise ValueError("Pass either strobe or load_pin, not both")
        if strobe is None:
            if load_pin is None:
                raise DACStrobeError(
                    f"{type(self).__name__} needs a load strobe; "
                    "pass strobe=... or load_pin=..."
                )
            strobe = GpiozeroStrobe(load_pin)
        try:
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
        except BaseException:
            # The strobe already drives a pin; release it when the bus cannot
            # be opened.
            strobe.close()
            raise
        backend = StrobedBackend(transport, strobe)
        try:
            super().__init__(
                backend=backend,
                reference=reference,
                channel_count=count,
                label=label,
                log_level=log_level,
            )
        except BaseException:
            # This constructor opened both; release them when the DAC layer
            # rejects a later keyword.
            backend.close()
            raise


class AD7390(AD739x):
    """Single 12-bit converter with an external reference."""

    _RESOLUTION = 12


class AD7391(AD739x):
    """Single 10-bit converter with an external reference."""

    _RESOLUTION = 10
