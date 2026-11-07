"""Transport selection shared by the DAC device families."""

from scietex.hal.spi import (
    GPIOZERO_PIN_ARGS,
    SpiDevTransport,
    SpiTransport,
    build_default_transport,
)


def open_transport(  # noqa: PLR0913
    *,
    mode: int,
    transport: SpiTransport | None = None,
    spi: SpiTransport | None = None,
    port: int | None = None,
    device: int | None = None,
    clock_pin: int | None = None,
    mosi_pin: int | None = None,
    miso_pin: int | None = None,
    select_pin: int | None = None,
) -> SpiTransport:
    """
    Resolve the SPI transport a device family should drive its frames through.

    An explicit transport always wins, and `spi` is its legacy alias. With no
    transport the pin keywords select the gpiozero backend, which is fixed at
    SPI mode 0; without them the spidev backend is opened on `port` and
    `device` with the requested `mode`.

    :param mode: SPI mode (clock polarity and phase) for the spidev backend.
    :param transport: Existing transport to use as is (SpiTransport | None).
    :param spi: Legacy alias for `transport`, used when it is None
        (SpiTransport | None).
    :param port: spidev bus number, or the gpiozero SPI port.
    :param device: spidev chip-select line, or the gpiozero SPI device number.
    :param clock_pin: GPIO clock pin; any pin keyword selects the gpiozero
        backend.
    :param mosi_pin: GPIO MOSI pin; selects the gpiozero backend.
    :param miso_pin: GPIO MISO pin; selects the gpiozero backend.
    :param select_pin: GPIO chip-select pin; selects the gpiozero backend.
    :return: Transport selected by the arguments.
    :raises ValueError: If a pin keyword is combined with a nonzero `mode`.
    :raises ImportError: If the optional package for the selected backend is
        missing.
    """
    chosen = transport if transport is not None else spi
    if chosen is not None:
        return chosen
    pins = {
        "clock_pin": clock_pin,
        "mosi_pin": mosi_pin,
        "miso_pin": miso_pin,
        "select_pin": select_pin,
    }
    if any(pins[name] is not None for name in GPIOZERO_PIN_ARGS):
        if mode != 0:
            raise ValueError(
                "The gpiozero backend is fixed at SPI mode 0, got "
                f"mode={mode}; build "
                f"SpiDevTransport(bus={0 if port is None else port}, "
                f"device={0 if device is None else device}, mode={mode}) "
                "instead or leave the pin keywords unset"
            )
        return build_default_transport(
            port=port,
            device=device,
            clock_pin=clock_pin,
            mosi_pin=mosi_pin,
            miso_pin=miso_pin,
            select_pin=select_pin,
        )
    return SpiDevTransport(
        bus=0 if port is None else port,
        device=0 if device is None else device,
        mode=mode,
    )
