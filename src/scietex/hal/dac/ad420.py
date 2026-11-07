"""AD420 single-channel 16-bit converter with a latched serial word."""

from typing import Any, cast

from scietex.hal.spi import SpiTransport

from .__frames import pack
from .__helpers import check_integer
from .__strobe import (
    GpiozeroRisingStrobe,
    LoadStrobe,
    RisingLoadStrobe,
    StrobedBackend,
)
from .__transport import open_transport
from .channel import CurrentChannel, DACChannel, VoltageChannel
from .dac import DAC
from .errors import DACStrobeError


def encode_write(code: int) -> list[int]:
    """
    Encode one data write of an AD420 as an SPI frame.

    The part has no control bits: the 16-bit code is the whole frame, most
    significant bit first, and the LATCH pin latches it afterwards.

    :param code: Raw code in the 16-bit data field (int).
    :return: Frame bytes, most significant first (list of int).
    :raises TypeError: If `code` is not an integer number, or is a `bool`.
    :raises ValueError: If `code` is infinite, `NaN`, or fractional.
    """
    return pack(check_integer(code) & 0xFFFF, 2)


class AD420Channel:
    """Mixin that delegates a code write to the AD420 frame encoder."""

    _dac: DAC
    index: int

    def _write_code(self, code: int) -> int:
        """Hand the code to the device, which owns the frame and the latch."""
        return cast("AD420", self._dac)._write_code(self.index, code)


class AD420VoltageChannel(AD420Channel, VoltageChannel):
    """Voltage output of an AD420 in its only native voltage range, 0-5 V."""


class AD420CurrentChannel(AD420Channel, CurrentChannel):
    """Current output of an AD420 in one of its three current ranges."""


_RANGES: dict[str, tuple[type[DACChannel], float, float, int]] = {
    "0-5V": (AD420VoltageChannel, 5.0, 0.0, 0b00),
    "4-20mA": (AD420CurrentChannel, 0.020, 0.004, 0b01),
    "0-20mA": (AD420CurrentChannel, 0.020, 0.0, 0b10),
    "0-24mA": (AD420CurrentChannel, 0.024, 0.0, 0b11),
}
"""Range name mapped to channel class, upper bound, lower bound, and strap code.

The strap code is the RANGE SELECT bit pattern the board must be wired for. It
is documentation only: the package can neither drive nor read those pins.
"""


class AD420(DAC):
    """
    Single 16-bit converter with a fixed 5 V reference and a software-declared
    output range.

    The part takes a plain 16-bit data word, MSB first, with no control bits,
    and latches it when the LATCH pin sees a rising edge. It is write-only:
    DATA OUT only repeats the frame to the next device in a daisy chain, so
    `readback()` raises and `.value` returns the code cached from the last
    successful write.

    `range` does not configure the chip. RANGE SELECT is a hardware strap the
    library can neither drive nor read, so `range=` only declares how the board
    is wired, and a wrong declaration silently mislabels every output. A 0-20
    mA strap declared as 4-20 mA, for example, reports a floor 4 mA above the
    real one and a span 4 mA narrower: the code and the current the part
    actually sources stay the same, so nothing alarms and only the scaling
    lies.

    LATCH idles LOW and latches on its rising edge, the opposite polarity of
    the parts served by `LoadStrobe`. Wire it to a GPIO and pass `latch_pin=`,
    or pass a `RisingLoadStrobe` as `strobe`; without one the constructor
    raises `DACStrobeError` before the bus opens.

    CLEAR and FAULT are hardware pins the library does not touch. CLEAR is
    active high and pulls the output to the bottom of its range without
    changing the register; FAULT is an active-low open-drain flag the board
    must wire up and read itself.

    The internal 5 V reference is always on and has no enable bit, and the
    output span comes entirely from RANGE SELECT. Any voltage range other than
    0-5 V, including the bipolar and 0-10 V spans, needs an external buffer
    amplifier, so those ranges are not modelled here.
    """

    _CHANNELS = 1
    _RESOLUTION = 16
    _READABLE = False
    _SPI_MODE = 0
    _FIXED_REFERENCE: float | None = None

    def __init__(  # noqa: PLR0913
        self,
        range: str = "4-20mA",
        *,
        strobe: LoadStrobe | RisingLoadStrobe | None = None,
        latch_pin: int | None = None,
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
        Build the device and expose its output as the channel of `range`.

        The constructor takes ownership of `strobe`, or builds a
        `GpiozeroRisingStrobe` from `latch_pin`, and releases it with the
        transport when construction fails or the device is closed.

        :param range: Declared wiring of RANGE SELECT, one of `"0-5V"`,
            `"4-20mA"`, `"0-20mA"`, `"0-24mA"` (str).
        :param strobe: Latch strobe that latches each frame; either polarity is
            accepted by the type, but this part needs a rising edge
            (LoadStrobe | RisingLoadStrobe | None).
        :param latch_pin: GPIO pin of the latch line; builds a
            `GpiozeroRisingStrobe` when `strobe` is None (int | None).
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
        :raises DACStrobeError: If neither `strobe` nor `latch_pin` is given.
        :raises ValueError: If both are given, `range` is not a supported name,
            or `label` is empty.
        :raises TypeError: If `range` or `label` has the wrong type.
        :raises ImportError: If the optional package for the selected backend
            or the strobe is missing.
        """
        # Validate everything the caller can get wrong before the bus opens, so
        # a rejected keyword never touches /dev/spidev*.
        if not isinstance(range, str):
            raise TypeError(
                f"Expected a range name, got {range!r} of type {type(range)}"
            )
        if range not in _RANGES:
            allowed = ", ".join(_RANGES)
            raise ValueError(f"Expected range to be one of {allowed}, got {range!r}")
        channel_class, upper, lower, _ = _RANGES[range]
        if strobe is not None and latch_pin is not None:
            raise ValueError("Pass either strobe or latch_pin, not both")
        if strobe is None:
            if latch_pin is None:
                raise DACStrobeError(
                    "AD420 needs a latch strobe; pass strobe=... or latch_pin=..."
                )
            strobe = GpiozeroRisingStrobe(check_integer(latch_pin))
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
        # The base class reads the geometry and the span from `self`, so the
        # per-range values have to be instance attributes before it runs.
        self._CHANNEL_CLASS = channel_class
        self._FIXED_REFERENCE = upper
        self._LOWER_BOUND = lower
        try:
            super().__init__(
                backend=backend,
                reference=upper,
                label=label,
                log_level=log_level,
            )
        except BaseException:
            # This constructor opened both; release them when the DAC layer
            # rejects a later keyword.
            backend.close()
            raise

    def _write_code(self, index: int, code: int) -> int:
        """
        Send one code, then latch it with one rising edge.

        The pulse follows the transfer, so a failed transfer leaves the latch
        alone and the register keeps its previous code.

        :param index: Channel index, 0 (int).
        :param code: Raw code already validated by the channel.
        :return: Code that was written.
        """
        self._backend.transfer(encode_write(code))
        self._backend.strobe.pulse()
        return code
