"""Shared helpers for the DAC tests."""

import time
from collections.abc import Sequence
from typing import Any

from scietex.hal.spi import FakeSpiTransport

from scietex.hal.dac import MCP4251


def wiper_frame(code: int) -> list[int]:
    """Two-word response an MCP4xxx returns for a wiper read of `code`."""
    return [0xFE | ((code >> 8) & 1), code & 0xFF]


def fake(*codes: int, default: int = 0) -> FakeSpiTransport:
    """Transport queuing one read frame per code, then a default frame."""
    return FakeSpiTransport(
        responses=[wiper_frame(code) for code in codes],
        default=wiper_frame(default),
    )


def build(part: type = MCP4251, **kwargs: Any) -> tuple[Any, FakeSpiTransport]:
    """Build `part` on a fake bus and return the device with its transport."""
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = fake()
    return part(transport=transport, **kwargs), transport


class RecordingTransport:
    """Transport stand-in that records every request and answers in order."""

    def __init__(
        self,
        responses: Sequence[Sequence[int]] | None = None,
        default: Sequence[int] = (),
        *,
        log: list[str] | None = None,
    ) -> None:
        self.responses = [list(response) for response in responses or []]
        self.default = list(default)
        self.requests: list[list[int]] = []
        self.close_calls = 0
        self.closed = False
        self.log: list[str] = [] if log is None else log

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Record `data` and return the next scripted response, else the default."""
        self.log.append("transfer")
        self.requests.append(list(data))
        if self.responses:
            return self.responses.pop(0)
        return list(self.default)

    def close(self) -> None:
        """Count the call and mark the transport closed."""
        self.log.append("transport-close")
        self.close_calls += 1
        self.closed = True

    def __repr__(self) -> str:
        """Official string representation (used in debugging)."""
        return (
            f"{type(self).__name__}(requests={len(self.requests)}, "
            f"closed={self.closed})"
        )


class FakeStrobe:
    """Load-strobe stand-in that records pulses in a shared ordering log."""

    def __init__(self, *, log: list[str] | None = None) -> None:
        self.pulse_calls: list[float] = []
        self.closed = False
        self.close_calls = 0
        self.log: list[str] = [] if log is None else log
        self.raise_on_close = False

    def pulse(self) -> None:
        """Record one pulse at its monotonic timestamp."""
        self.pulse_calls.append(time.monotonic())
        self.log.append("pulse")

    def close(self) -> None:
        """Count the call and mark the strobe closed unless it is set to fail."""
        self.close_calls += 1
        self.log.append("strobe-close")
        if self.raise_on_close:
            raise RuntimeError("strobe close failed")
        self.closed = True


class FakeRisingStrobe(FakeStrobe):
    """Rising-edge load-strobe stand-in; records exactly like `FakeStrobe`."""


class MemoryBackend:
    """Transport-shaped stand-in: records requests and tracks its closed state."""

    def __init__(self) -> None:
        self.requests: list[list[int]] = []
        self.close_calls = 0
        self.closed = False

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Record `data` and echo it back."""
        self.requests.append(list(data))
        return list(data)

    def close(self) -> None:
        """Count the call and mark the backend closed."""
        self.close_calls += 1
        self.closed = True
