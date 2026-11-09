"""Output enable/disable through the MCP4xxx TCON register."""

import pytest
from conftest import TCON_CONNECTED, TCON_READ, TCON_WRITE, build, fake

from scietex.hal.dac import DACError, DACOutputDisabledError

DISCONNECTED = 0x00


def test_construction_connects_the_output() -> None:
    """A freshly built device asserts the connected TCON state."""
    transport = fake()
    transport.tcon = DISCONNECTED
    dac, _ = build(transport=transport)
    assert dac.output_enabled is True
    assert transport.tcon == TCON_CONNECTED
    assert transport.calls[-2:] == [[TCON_WRITE, TCON_CONNECTED], [TCON_READ, 0x00]]


def test_disable_output_disconnects_both_wipers() -> None:
    """Disabling writes the disconnected state and flips the flag."""
    dac, transport = build()
    dac.disable_output()
    assert dac.output_enabled is False
    assert transport.tcon == DISCONNECTED


def test_enable_output_reconnects_the_wipers() -> None:
    """Enabling after a disable restores the connected state."""
    dac, transport = build()
    dac.disable_output()
    dac.enable_output()
    assert dac.output_enabled is True
    assert transport.tcon == TCON_CONNECTED


def test_a_repeated_switch_is_a_no_op_without_force() -> None:
    """The TCON word is not re-sent when the state is already correct."""
    dac, transport = build()
    transport.calls.clear()
    dac.enable_output()
    dac.disable_output()
    dac.disable_output()
    assert transport.calls == [[TCON_WRITE, DISCONNECTED], [TCON_READ, 0x00]]


def test_force_resends_the_tcon_word() -> None:
    """`force=True` re-asserts a state the pot may have lost."""
    dac, transport = build()
    transport.calls.clear()
    dac.enable_output(force=True)
    assert transport.calls == [[TCON_WRITE, TCON_CONNECTED], [TCON_READ, 0x00]]


def test_force_recovers_an_output_zeroed_by_a_power_cycle() -> None:
    """A pot power cycle resets TCON; force re-connects it."""
    dac, transport = build()
    # Simulate the volatile register resetting behind the object's back.
    transport.tcon = DISCONNECTED
    dac.enable_output(force=True)
    assert transport.tcon == TCON_CONNECTED


def test_a_write_is_refused_while_the_output_is_disabled() -> None:
    """A disabled output rejects the write before any bus traffic."""
    dac, transport = build()
    dac.disable_output()
    transport.calls.clear()
    with pytest.raises(DACOutputDisabledError):
        dac.channel(0).value = 5
    assert transport.calls == []


def test_a_read_is_allowed_while_the_output_is_disabled() -> None:
    """The register stays readable while the wiper is disconnected."""
    dac, transport = build()
    dac.disable_output()
    transport.calls.clear()
    assert dac.channel(1).value == 0
    assert transport.calls == [[0x1C, 0x00]]


def test_a_failed_tcon_read_back_raises_and_closes_the_bus() -> None:
    """A pot that does not confirm TCON is rejected, not silently trusted."""
    transport = fake()
    transport.echo_tcon = False
    with pytest.raises(DACError):
        build(transport=transport)
    assert transport.closed is True


@pytest.mark.parametrize("force", [0, 1, "yes", None])
def test_a_non_bool_force_is_rejected(force: object) -> None:
    """`force` follows the library's bool-only keyword discipline."""
    dac, _ = build()
    with pytest.raises(TypeError):
        dac.enable_output(force=force)  # type: ignore[arg-type]
