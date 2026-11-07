"""Base class for digital-to-analog converters."""

from collections.abc import Sequence
from types import TracebackType
from typing import Any

from .__helpers import check_integer, check_label, check_reference
from .__logger import get_logger
from .channel import DACChannel


class DAC:
    """
    Container for the channels of a digital-to-analog converter.

    The device is transport-agnostic: it wraps a backend object that owns the
    bus, and its channels are built once from the class-level geometry.
    `channels` holds them in index order and never changes.

    `reference` is unit-neutral: it is the full scale the outputs map to, in
    volts for a voltage device and in amperes for a current device. While it is
    None the scaled `output` of every channel is None, because the library will
    not guess a full scale.

    A device that cannot report its registers back sets `_READABLE` to False;
    its channels then serve the code cached from the last write instead of
    asking the bus. A device with an internal full scale sets
    `_FIXED_REFERENCE` to it, and then `reference` can only be that value or
    None.

    The object can be used as a context manager; leaving the block closes the
    backend.
    """

    _CHANNELS: int = 0
    _RESOLUTION: int = 8
    _CHANNEL_CLASS: type[DACChannel] = DACChannel
    _READABLE: bool = True
    """False on a device that cannot report its own register contents."""

    _FIXED_REFERENCE: float | None = None
    """Full scale fixed by the device, in its own unit, or None."""

    def __init__(
        self,
        *,
        backend: object,
        reference: float | None = None,
        channel_count: int | None = None,
        label: str | None = None,
        log_level: int | str | None = None,
    ) -> None:
        """
        Build the device around a backend that owns the bus.

        :param backend: Object the device delegates bus access and lifecycle to;
            it needs `close()` and may expose `transport`, `spi`, and `closed`.
        :param reference: Full-scale value the channels scale by, or None while
            it is unknown (float | None).
        :param channel_count: Number of channels to expose, defaults to the
            device geometry (int | None).
        :param label: Logger name, defaults to the class name (str).
        :param log_level: Logging level such as `logging.DEBUG`; defaults to
            `logging.ERROR`.
        :raises TypeError: If `reference` or `label` has the wrong type.
        :raises ValueError: If `reference` is not positive, conflicts with a
            fixed full scale, `label` is empty, or `channel_count` is outside
            `1..channels`.
        """
        # Duck-typed on purpose: the base class only probes attributes such as
        # `transport` and calls `close()`, and a device family supplies the
        # concrete backend.
        self._backend: Any = backend
        self._closed = False
        self._reference = self._check_fixed_reference(check_reference(reference))
        self.label = None if label is None else check_label(label)
        self.logger = get_logger(self.label or type(self).__name__, log_level)
        count = (
            self._CHANNELS if channel_count is None else check_integer(channel_count)
        )
        if not 1 <= count <= self._CHANNELS:
            raise ValueError(
                f"Expected a channel count within 1..{self._CHANNELS}, got {count}"
            )
        self.channels: tuple[DACChannel, ...] = tuple(
            self._make_channel(index) for index in range(count)
        )

    @property
    def reference(self) -> float | None:
        """Full scale the channels map to, or None when it is unknown."""
        return self._reference

    @reference.setter
    def reference(self, reference: float | None) -> None:
        """
        Set the full scale used by the channel `output` properties.

        :param reference: Positive full scale, or None (float | None).
        :raises TypeError: If `reference` is not a real number, or is a `bool`.
        :raises ValueError: If `reference` is zero, negative, infinite, or
            `NaN`, or conflicts with a fixed full scale.
        """
        self._reference = self._check_fixed_reference(check_reference(reference))

    @property
    def readable(self) -> bool:
        """True when the device can report its own register contents."""
        return self._READABLE

    @property
    def v_ref(self) -> float | None:
        """Alias of `reference`, the conventional name on a voltage device."""
        return self.reference

    @v_ref.setter
    def v_ref(self, v_ref: float | None) -> None:
        """Set the full scale, an alias of `reference`."""
        self.reference = v_ref

    @property
    def resolution(self) -> int:
        """Number of bits in a raw code."""
        return self._RESOLUTION

    @property
    def max_code(self) -> int:
        """Largest raw code the device accepts, `(1 << resolution) - 1`."""
        return (1 << self.resolution) - 1

    def channel(self, index: int) -> DACChannel:
        """
        Return the channel at `index`.

        :param index: Channel index, 0-based (int).
        :return: `DACChannel` for that output.
        :raises IndexError: If `index` is outside `0..channels - 1`.
        """
        if not 0 <= index < len(self.channels):
            raise IndexError(f"Channel {index} does not exist")
        return self.channels[index]

    def read_all(self) -> tuple[int, ...]:
        """
        Read every channel.

        A readable channel is read live: each element is a separate bus
        transaction and nothing is cached. On a write-only device every element
        is the cached code, so no bus traffic is issued.

        :return: Raw codes in channel index order (tuple of int).
        """
        return tuple(channel.value for channel in self.channels)

    def write_all(self, values: Sequence[int]) -> tuple[int, ...]:
        """
        Write one raw code per channel.

        The whole sequence is validated before the first bus transaction, so a
        rejected element cannot leave the device partially updated. A write-only
        device performs one transfer per channel and reads nothing back.

        :param values: One code per channel (Sequence of int).
        :return: Codes that were written, in channel index order.
        :raises TypeError: If `values` is not a sequence, or an element is not
            a real number, or is a `bool`.
        :raises ValueError: If the length differs from the channel count, or an
            element is fractional, infinite, or `NaN`.
        :raises DACCodeError: If an element is outside `0..max_code`.
        """
        if len(values) != len(self.channels):
            raise ValueError(f"Expected {len(self.channels)} codes, got {len(values)}")
        codes = tuple(
            channel._check_code(value)
            for channel, value in zip(self.channels, values, strict=True)
        )
        for channel, code in zip(self.channels, codes, strict=True):
            channel.value = code
        return codes

    def _make_channel(self, index: int) -> DACChannel:
        """
        Build the channel object for `index`.

        :param index: Channel index, 0-based (int).
        :return: Channel of the device's channel class.
        """
        return self._CHANNEL_CLASS(self, index)

    def _read_code(self, index: int) -> int:
        """
        Read one channel as a raw code.

        The base class has no frame format; a device family implements it.

        :param index: Channel index, 0-based (int).
        :return: Raw code of that channel.
        :raises NotImplementedError: Always, the base class has no codec.
        """
        raise NotImplementedError

    def _write_code(self, index: int, code: int) -> int:
        """
        Write one channel as a raw code.

        The base class has no frame format; a device family implements it.

        :param index: Channel index, 0-based (int).
        :param code: Raw code already validated by the channel.
        :return: Code the device reports after the write.
        :raises NotImplementedError: Always, the base class has no codec.
        """
        raise NotImplementedError

    def _check_fixed_reference(self, reference: float | None) -> float | None:
        """
        Resolve a reference against a full scale fixed by the device.

        :param reference: Validated reference, or None (float | None).
        :return: The reference itself, or the fixed full scale when the device
            has one.
        :raises ValueError: If a reference is given that is not the fixed
            full scale.
        """
        fixed = self._FIXED_REFERENCE
        if fixed is None:
            return reference
        if reference is not None and reference != fixed:
            raise ValueError(
                f"{type(self).__name__} has a fixed full scale of {fixed}; "
                f"got reference={reference!r}"
            )
        return fixed

    @property
    def transport(self) -> Any:
        """Bus transport of the backend, or the backend when it exposes none."""
        return getattr(self._backend, "transport", None) or self._backend

    @property
    def spi(self) -> Any:
        """Backend's SPI handle: its `spi`, then its `raw`, then the backend."""
        spi = getattr(self._backend, "spi", None)
        if spi is not None:
            return spi
        raw = getattr(self._backend, "raw", None)
        return self._backend if raw is None else raw

    @property
    def closed(self) -> bool:
        """
        True when `close()` has run or the backend reports itself closed.

        A callable `closed` attribute is called first and its result is coerced
        with `bool`. A backend whose `closed` probe raises counts as not closed;
        the device's own flag still applies.
        """
        try:
            reported = getattr(self._backend, "closed", False)
            if callable(reported):
                reported = reported()
            reported = bool(reported)
        except Exception:  # noqa: BLE001 - a broken probe must not leak
            reported = False
        return self._closed or reported

    def close(self) -> None:
        """
        Close the backend and mark the device closed.

        The device is marked closed even when the backend's `close()` raises;
        the exception is still propagated.
        """
        try:
            self._backend.close()
        finally:
            self._closed = True

    def __enter__(self) -> "DAC":
        """Return the device itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the backend when leaving the context."""
        self.close()
