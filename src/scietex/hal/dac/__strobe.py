"""Load-strobe abstraction for devices that latch a clocked frame."""

import time
from collections.abc import Sequence
from typing import Any, Protocol

from .__helpers import check_positive


class LoadStrobe(Protocol):
    """
    A load line that latches a clocked frame into a DAC register.

    The line idles high. `pulse` drives it low for a short time and returns it
    high, so the chip latches on the rising return edge. This is the polarity
    for parts whose load input is active low; a part that latches on the rising
    edge itself needs `RisingLoadStrobe` instead. Using the wrong one drops
    frames silently: the chip latches only on its documented edge, so a
    reversed strobe leaves the register holding the previous code while every
    transfer still succeeds.
    """

    def pulse(self) -> None:
        """Drive the line low, then high, to latch one frame."""
        ...

    def close(self) -> None:
        """Release the line and its pin."""
        ...


class GpiozeroStrobe:
    """
    Load strobe on a gpiozero digital output.

    The pin is driven high as soon as the object exists, because every part
    this strobe serves requires the load line to idle high and to stay high
    while serial data is clocked in. `pulse` drives it low for `pulse_width`
    seconds and then high again, latching the frame that was just clocked.

    gpiozero is imported lazily so the core package needs no GPIO dependency.
    """

    def __init__(self, pin: int, *, pulse_width: float = 1e-5) -> None:
        """
        Bind the load line and drive it high.

        :param pin: GPIO pin number connected to the load input (int).
        :param pulse_width: Low time of one latch pulse in seconds (float);
            defaults to 10 microseconds.
        :raises ImportError: If the optional `gpiozero` package is missing.
        :raises TypeError: If `pulse_width` is not a positive real number, or is
            a `bool`.
        :raises ValueError: If `pulse_width` is zero, negative, infinite, or
            `NaN`.
        """
        try:
            from gpiozero import DigitalOutputDevice  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "GpiozeroStrobe requires the optional 'gpiozero' package. "
                "Install it with: pip install 'scietex.hal.dac[gpiozero]'"
            ) from exc
        self._pulse_width = float(check_positive(pulse_width))
        self._pin = DigitalOutputDevice(pin, initial_value=True)
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once `close()` has released the pin."""
        return self._closed

    def pulse(self) -> None:
        """Drive the line low for `pulse_width`, then high to latch the frame."""
        self._pin.off()
        time.sleep(self._pulse_width)
        self._pin.on()

    def close(self) -> None:
        """Release the pin; a second call has no effect."""
        if self._closed:
            return
        self._pin.close()
        self._closed = True


class RisingLoadStrobe(Protocol):
    """
    A load line that idles low and latches on its rising edge.

    `pulse` drives the line high for a short time and returns it low. This is
    the opposite polarity of `LoadStrobe`: the parts it serves read the
    low-to-high transition as the latch, so a falling edge does nothing. Using
    the wrong strobe drops frames silently, because the chip latches only on
    its documented edge and the bus transaction still succeeds.
    """

    def pulse(self) -> None:
        """Drive the line high, then low, to latch one frame."""
        ...

    def close(self) -> None:
        """Release the line and its pin."""
        ...


class GpiozeroRisingStrobe:
    """
    Rising-edge load strobe on a gpiozero digital output.

    The pin is driven low as soon as the object exists, because every part this
    strobe serves requires the latch line to idle low. `pulse` drives it high
    for `pulse_width` seconds and then low again; the rising edge latches the
    frame that was just clocked.

    gpiozero is imported lazily so the core package needs no GPIO dependency.
    """

    def __init__(self, pin: int, *, pulse_width: float = 1e-5) -> None:
        """
        Bind the latch line and drive it low.

        :param pin: GPIO pin number connected to the latch input (int).
        :param pulse_width: High time of one latch pulse in seconds (float);
            defaults to 10 microseconds.
        :raises ImportError: If the optional `gpiozero` package is missing.
        :raises TypeError: If `pulse_width` is not a positive real number, or is
            a `bool`.
        :raises ValueError: If `pulse_width` is zero, negative, infinite, or
            `NaN`.
        """
        try:
            from gpiozero import DigitalOutputDevice  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "GpiozeroRisingStrobe requires the optional 'gpiozero' package. "
                "Install it with: pip install 'scietex.hal.dac[gpiozero]'"
            ) from exc
        self._pulse_width = float(check_positive(pulse_width))
        self._pin = DigitalOutputDevice(pin, initial_value=False)
        self._closed = False

    @property
    def closed(self) -> bool:
        """True once `close()` has released the pin."""
        return self._closed

    def pulse(self) -> None:
        """Drive the line high for `pulse_width`, then low to end the edge."""
        self._pin.on()
        time.sleep(self._pulse_width)
        self._pin.off()

    def close(self) -> None:
        """Release the pin; a second call has no effect."""
        if self._closed:
            return
        self._pin.close()
        self._closed = True


class StrobedBackend:
    """
    Backend that pairs a bus transport with a load strobe.

    `transfer` delegates to the transport and never pulses: a device family
    sends its frame first and then calls `strobe.pulse()`, so a failed transfer
    leaves the load line untouched. Either strobe polarity is accepted, because
    the backend only forwards transfers and leaves the edge to the strobe. The
    backend owns both objects and `close` releases them together, even when the
    strobe fails first.
    """

    def __init__(self, transport: Any, strobe: LoadStrobe | RisingLoadStrobe) -> None:
        """
        Pair a transport with the strobe that latches its frames.

        :param transport: Object with `transfer()` and `close()`.
        :param strobe: Load strobe with `pulse()` and `close()`, of either
            polarity.
        """
        self._transport = transport
        self._strobe = strobe
        self._closed = False

    @property
    def transport(self) -> Any:
        """Bus transport the frames travel over."""
        return self._transport

    @property
    def strobe(self) -> LoadStrobe | RisingLoadStrobe:
        """Load strobe that latches each frame."""
        return self._strobe

    @property
    def spi(self) -> Any:
        """Transport SPI handle: its `spi`, then its `raw`, then the transport."""
        spi = getattr(self._transport, "spi", None)
        if spi is not None:
            return spi
        raw = getattr(self._transport, "raw", None)
        return self._transport if raw is None else raw

    @property
    def raw(self) -> Any:
        """Raw handle of the transport, or None when it exposes none."""
        return getattr(self._transport, "raw", None)

    @property
    def closed(self) -> bool:
        """True once `close()` has released the transport and the strobe."""
        return self._closed

    def transfer(self, data: Sequence[int]) -> list[int]:
        """
        Send one frame over the transport.

        :param data: Frame to send (Sequence of int).
        :return: Received words (list of int).
        """
        return self._transport.transfer(data)

    def close(self) -> None:
        """
        Release the strobe and the transport, even when the first one fails.

        Repeated calls after a close has run have no effect. An exception from
        either `close()` is propagated after both objects were released.
        """
        if self._closed:
            return
        try:
            self._strobe.close()
        finally:
            try:
                self._transport.close()
            finally:
                self._closed = True
