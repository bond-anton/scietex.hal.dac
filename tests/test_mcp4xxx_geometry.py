"""Geometry of the MCP4xxx DAC wrappers."""

import BDPotentiometer.mcp4xxx as bd_mcp4xxx
import pytest
from conftest import build

from scietex.hal.dac import (
    MCP4231,
    MCP4241,
    MCP4251,
    MCP4261,
    DividerChannel,
)

PARTS = [
    (MCP4231, bd_mcp4xxx.MCP4231, 7, 127),
    (MCP4241, bd_mcp4xxx.MCP4241, 7, 127),
    (MCP4251, bd_mcp4xxx.MCP4251, 8, 255),
    (MCP4261, bd_mcp4xxx.MCP4261, 8, 255),
]


@pytest.mark.parametrize(("part", "pot_class", "bits", "top_code"), PARTS)
def test_geometry(part: type, pot_class: type, bits: int, top_code: int) -> None:
    """Two divider channels at the resolution the part provides."""
    dac, _ = build(part)
    assert len(dac.channels) == 2
    assert dac.resolution == bits
    assert dac.max_code == top_code
    assert [channel.index for channel in dac.channels] == [0, 1]
    assert all(isinstance(channel, DividerChannel) for channel in dac.channels)
    assert isinstance(dac.device, pot_class)


@pytest.mark.parametrize(("part", "pot_class", "bits", "top_code"), PARTS)
def test_channels_are_distinct_objects(
    part: type, pot_class: type, bits: int, top_code: int
) -> None:
    """Every channel is its own object, never a shared prototype."""
    dac, _ = build(part)
    assert len({id(channel) for channel in dac.channels}) == 2


@pytest.mark.parametrize(("part", "pot_class", "bits", "top_code"), PARTS)
def test_channels_are_an_immutable_tuple(
    part: type, pot_class: type, bits: int, top_code: int
) -> None:
    """The channel collection cannot be rebound to another object."""
    dac, _ = build(part)
    assert isinstance(dac.channels, tuple)
    with pytest.raises(TypeError):
        dac.channels[0] = dac.channels[1]  # type: ignore[index]


@pytest.mark.parametrize(("part", "pot_class", "bits", "top_code"), PARTS)
def test_channel_index_outside_the_geometry_raises(
    part: type, pot_class: type, bits: int, top_code: int
) -> None:
    """Only channels 0 and 1 exist."""
    dac, _ = build(part)
    for index in (-1, 2):
        with pytest.raises(IndexError):
            dac.channel(index)


@pytest.mark.parametrize(("part", "pot_class", "bits", "top_code"), PARTS)
def test_construction_reads_every_wiper(
    part: type, pot_class: type, bits: int, top_code: int
) -> None:
    """The wrapped part reads both wipers, then enables the output."""
    _, transport = build(part)
    assert transport.calls == [
        [0x0C, 0x00],
        [0x0C, 0x00],
        [0x0C, 0x00],
        [0x1C, 0x00],
        [0x1C, 0x00],
        [0x41, 0xFF],
        [0x4C, 0x00],
    ]


@pytest.mark.parametrize(("part", "pot_class", "bits", "top_code"), PARTS)
def test_grounding_defaults_to_b(
    part: type, pot_class: type, bits: int, top_code: int
) -> None:
    """The default wiring grounds B, so the output rises with the code."""
    dac, _ = build(part)
    assert dac.grounded == "B"
    assert all(channel.grounded == "B" for channel in dac.channels)
