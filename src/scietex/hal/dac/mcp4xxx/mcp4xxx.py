"""MCP4xxx digital potentiometers exposed as DAC divider channels."""

from typing import Any, cast

from scietex.hal.spi import SpiTransport

from ..__helpers import check_bool, check_grounded, check_reference
from ..channel import DACChannel, DividerChannel
from ..dac import DAC
from ..errors import DACError, DACOutputDisabledError

#: TCON state that connects A, W, and B and leaves shutdown deasserted.
#: A channel only drives its wiper in this state; TCON is volatile and powers
#: up with every terminal disconnected, so it is re-asserted on each open.
_OUTPUT_CONNECTED = {"shdn": False, "A": True, "W": True, "B": True}
#: TCON state that disconnects every terminal and asserts shutdown.
_OUTPUT_DISCONNECTED = {"shdn": True, "A": False, "W": False, "B": False}


class MCP4xxxChannel(DividerChannel):
    """One wiper of an MCP4xxx potentiometer, wired as a grounded divider."""

    def _read_code(self) -> int:
        """Read the wiper register; the wrapped device owns the frame format."""
        return cast("MCP4xxx", self._dac).device.get_value(self.index)

    def _write_code(self, code: int) -> int:
        """Write the wiper register and return the code read back.

        A disconnected output is refused before any bus traffic, so a write
        never silently updates a register whose wiper cannot drive anything.

        :param code: Raw code already validated by the channel.
        :return: Code the device reports after the write.
        :raises DACOutputDisabledError: If the device output is disabled.
        """
        device = cast("MCP4xxx", self._dac)
        if not device.output_enabled:
            raise DACOutputDisabledError(
                f"Channel {self.index} output is disabled; "
                "call enable_output() before writing a code"
            )
        return device.device.set_value(self.index, code)


class MCP4xxx(DAC):
    """
    Base class for the dual-channel MCP4xxx digital potentiometers.

    The device composes a `BDPotentiometer` part instead of subclassing it:
    the wrapped object is built first, because it opens the bus and reads every
    wiper register during construction, and is then handed to the DAC layer as
    the backend. `reference` and `grounded` are validated before the wrapped
    part is built, so a rejected keyword never touches the bus.

    The chip classes narrow the raw code to `2**bits - 1`: the pot model counts
    `2**bits` steps, but code `2**bits` is never written, so the top code is
    127 on a 7-bit part and 255 on an 8-bit part.

    The part gates each wiper with the terminal-connect (TCON) register: with
    A, W, and B disconnected the wiper is high-impedance and the register value
    no longer reaches the output. TCON is volatile and powers up disconnected,
    so construction asserts the connected state and `output_enabled` reports
    it. `disable_output()` disconnects both wipers and `enable_output()`
    reconnects them; a code write while the output is disabled raises
    `DACOutputDisabledError` instead of pretending it took effect, mirroring
    the current-output parts.
    """

    _RESOLUTION: int
    _POT_CLASS: type[Any]
    _CHANNEL_CLASS = MCP4xxxChannel

    def __init__(  # noqa: PLR0913
        self,
        r_ab: float = 10e3,
        channels: int | None = None,
        *,
        reference: float | None = None,
        grounded: str = "B",
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
        Build the potentiometer and expose its wipers as divider channels.

        :param r_ab: Total resistance in ohms; the wrapped part accepts 5k,
            10k, 50k, and 100k (float).
        :param channels: Channel count, 1..2; None uses every channel the part
            provides (int | None).
        :param reference: Full-scale voltage in volts, or None while unknown
            (float | None).
        :param grounded: Terminal tied to ground, `"A"` or `"B"`; grounding B
            makes the output rise with the code (str).
        :param transport: Canonical SPI transport, forwarded to the part
            (SpiTransport | None).
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
        :raises TypeError: If `grounded` or `reference` has the wrong type, or
            if `invert`/`max_value` is passed.
        :raises ValueError: If `grounded` is not `"A"` or `"B"`, `reference`
            is not positive, `r_ab` is unsupported, or `label` is empty.
        :raises ImportError: If the optional package for the selected backend
            is missing.
        :raises DACError: If the TCON write that enables the output does not
            verify against the read-back.
        """
        self._grounded = check_grounded(grounded)
        reference = check_reference(reference)
        self._output_enabled = False
        self._pot = self._POT_CLASS(
            r_ab=r_ab,
            channels=channels,
            transport=transport,
            spi=spi,
            port=port,
            device=device,
            clock_pin=clock_pin,
            mosi_pin=mosi_pin,
            miso_pin=miso_pin,
            select_pin=select_pin,
            invert=False,
        )
        try:
            super().__init__(
                backend=self._pot,
                reference=reference,
                channel_count=len(self._pot.channels),
                label=label,
                log_level=log_level,
            )
            # TCON is volatile and powers up with every terminal disconnected,
            # so the output is re-asserted on every open; a power cycle after
            # this point is invisible until `enable_output(force=True)`.
            self.enable_output()
        except BaseException:
            # The wrapped part owns the bus this constructor opened; release it
            # when the DAC layer rejects a later keyword or TCON fails.
            self._pot.close()
            raise

    @property
    def grounded(self) -> str:
        """Terminal tied to ground: `"B"` rises with the code, `"A"` falls."""
        return self._grounded

    @property
    def device(self) -> Any:
        """The wrapped `BDPotentiometer` device, for escape-hatch access."""
        return self._pot

    @property
    def output_enabled(self) -> bool:
        """True when both wipers are connected and out of shutdown."""
        return self._output_enabled

    def enable_output(self, *, force: bool = False) -> None:
        """
        Connect every wiper terminal so the register value reaches the output.

        Construction calls this, so a freshly built device is always connected;
        a call on an enabled output is a no-op unless `force` is set. Use
        `force=True` to re-assert the state after a pot power cycle, which is
        invisible to this object because TCON is volatile.

        :param force: True to send the TCON word even when it is unchanged (bool).
        :raises TypeError: If `force` is not a bool.
        :raises DACError: If the TCON read-back does not match the write.
        """
        force = check_bool(force)
        if self._output_enabled and not force:
            return
        self._write_tcon(_OUTPUT_CONNECTED)
        self._output_enabled = True

    def disable_output(self, *, force: bool = False) -> None:
        """
        Disconnect every wiper terminal and assert shutdown.

        Calling it on a disabled output is a no-op unless `force` is set.
        Writing a code while the output is disabled raises
        `DACOutputDisabledError`.

        :param force: True to send the TCON word even when it is unchanged (bool).
        :raises TypeError: If `force` is not a bool.
        :raises DACError: If the TCON read-back does not match the write.
        """
        force = check_bool(force)
        if not self._output_enabled and not force:
            return
        self._write_tcon(_OUTPUT_DISCONNECTED)
        self._output_enabled = False

    def _write_tcon(self, state: dict[str, bool]) -> None:
        """
        Write one TCON state to both channels and require the read-back.

        A mismatched read-back means the analog path cannot be trusted, so it
        is reported instead of leaving a silently disconnected output.

        :param state: TCON state for both channels (dict).
        :raises DACError: If the wrapped part reports the write did not verify.
        """
        if not self._pot.write_tcon(ch0=dict(state), ch1=dict(state)):
            raise DACError("TCON read-back did not match the requested terminal state")

    def _make_channel(self, index: int) -> DACChannel:
        """Build a divider channel wired the same way as the device."""
        return MCP4xxxChannel(self, index, grounded=self._grounded)
