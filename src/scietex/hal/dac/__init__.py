"""Digital-to-analog converters."""

from .channel import (
    CurrentChannel,
    DACChannel,
    DACUnit,
    DividerChannel,
    VoltageChannel,
)
from .dac import DAC
from .errors import DACCodeError, DACError, DACReferenceError
from .mcp4xxx import MCP4231, MCP4241, MCP4251, MCP4261
from .version import __version__

__all__ = [
    "__version__",
    "DAC",
    "DACChannel",
    "DACUnit",
    "VoltageChannel",
    "CurrentChannel",
    "DividerChannel",
    "DACError",
    "DACReferenceError",
    "DACCodeError",
    "MCP4231",
    "MCP4241",
    "MCP4251",
    "MCP4261",
]
