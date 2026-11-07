"""Shared helpers for the DAC tests."""

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
    ) -> None:
        self.responses = [list(response) for response in responses or []]
        self.default = list(default)
        self.requests: list[list[int]] = []
        self.close_calls = 0
        self.closed = False

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Record `data` and return the next scripted response, else the default."""
        self.requests.append(list(data))
        if self.responses:
            return self.responses.pop(0)
        return list(self.default)

    def close(self) -> None:
        """Count the call and mark the transport closed."""
        self.close_calls += 1
        self.closed = True

    def __repr__(self) -> str:
        """Official string representation (used in debugging)."""
        return (
            f"{type(self).__name__}(requests={len(self.requests)}, "
            f"closed={self.closed})"
        )


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
