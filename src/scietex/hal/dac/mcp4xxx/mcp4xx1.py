"""Dual-channel MCP4xx1 digital potentiometers."""

from BDPotentiometer.mcp4xxx.mcp4xx1 import (
    MCP4231 as _BDMCP4231,
)
from BDPotentiometer.mcp4xxx.mcp4xx1 import (
    MCP4241 as _BDMCP4241,
)
from BDPotentiometer.mcp4xxx.mcp4xx1 import (
    MCP4251 as _BDMCP4251,
)
from BDPotentiometer.mcp4xxx.mcp4xx1 import (
    MCP4261 as _BDMCP4261,
)

from .mcp4xxx import MCP4xxx


class MCP4xx1(MCP4xxx):
    """Base for the dual-channel members of the MCP4xx1 family."""

    _CHANNELS = 2


class MCP4231(MCP4xx1):
    """MCP4231: two 7-bit volatile channels, codes `0..127`."""

    _RESOLUTION = 7
    _POT_CLASS = _BDMCP4231


class MCP4241(MCP4xx1):
    """MCP4241: two 7-bit channels, codes `0..127`.

    The part keeps a non-volatile wiper value, but this package has no commit
    path, so only the volatile register is written.
    """

    _RESOLUTION = 7
    _POT_CLASS = _BDMCP4241


class MCP4251(MCP4xx1):
    """MCP4251: two 8-bit volatile channels, codes `0..255`."""

    _RESOLUTION = 8
    _POT_CLASS = _BDMCP4251


class MCP4261(MCP4xx1):
    """MCP4261: two 8-bit channels, codes `0..255`.

    The part keeps a non-volatile wiper value, but this package has no commit
    path, so only the volatile register is written.
    """

    _RESOLUTION = 8
    _POT_CLASS = _BDMCP4261
