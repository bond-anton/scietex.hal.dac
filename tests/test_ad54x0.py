"""AD54x0 current source: control word, gated writes, and readback."""

from collections.abc import Callable
from typing import Any

import pytest
from conftest import RecordingTransport

from scietex.hal.dac import (
    AD5410,
    AD5420,
    AD54x0Control,
    AD54x0Status,
    DACCodeError,
    DACOutputDisabledError,
)

FOUR_TWENTY_ENABLED = [0x55, 0x10, 0x05]


def built(part: Any = AD5420, **kwargs: Any) -> tuple[Any, RecordingTransport]:
    """Build `part` on a recording bus and return the device with its bus."""
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = RecordingTransport(default=[0, 0, 0])
    return part(transport=transport, **kwargs), transport


@pytest.mark.parametrize(
    ("part", "max_code"),
    [(AD5410, 4095), (AD5420, 65535)],
    ids=["ad5410-12-bit", "ad5420-16-bit"],
)
def test_construction_issues_no_transfers(part: Any, max_code: int) -> None:
    """Building the device leaves the bus silent and the span unknown."""
    dac, transport = built(part)
    assert transport.requests == []
    assert dac.reference is None
    assert dac.channel(0).reference is None
    assert dac.channel(0).output is None
    assert transport.requests == []
    assert dac.readable is True
    assert dac.channel(0).readable is True
    assert dac.channel(0).unit == "A"
    assert dac.max_code == max_code


@pytest.mark.parametrize(
    ("enabled", "frame"),
    [
        pytest.param(False, [0x55, 0x00, 0x05], id="disabled"),
        pytest.param(True, FOUR_TWENTY_ENABLED, id="enabled"),
    ],
)
def test_configure_keeps_the_output_enable_state(
    enabled: bool, frame: list[int]
) -> None:
    """A range change never enables or disables the output as a side effect."""
    dac, transport = built()
    if enabled:
        dac.enable_output()
    dac.configure(range="4-20mA")
    assert transport.requests == [frame]


def test_a_repeated_configure_issues_no_transfer() -> None:
    """The cached word makes an unchanged configuration free."""
    dac, transport = built()
    dac.configure(range="0-24mA")
    assert transport.requests == [[0x55, 0x00, 0x07]]
    dac.configure(range="0-24mA")
    assert transport.requests == [[0x55, 0x00, 0x07]]


def test_force_resends_an_unchanged_control_word() -> None:
    """A stale shadow, for instance after a pin reset, is refreshed by force."""
    dac, transport = built()
    dac.configure(range="0-24mA")
    dac.configure(range="0-24mA", force=True)
    assert transport.requests == [[0x55, 0x00, 0x07]] * 2


@pytest.mark.parametrize(
    ("range_name", "upper", "lower"),
    [
        pytest.param("4-20mA", 0.020, 0.004, id="4-20"),
        pytest.param("0-20mA", 0.020, 0.0, id="0-20"),
        pytest.param("0-24mA", 0.024, 0.0, id="0-24"),
    ],
)
def test_configure_applies_the_affine_span(
    range_name: str, upper: float, lower: float
) -> None:
    """The range moves the device reference and the channel floor."""
    dac, _ = built()
    dac.configure(range=range_name)
    channel = dac.channel(0)
    assert dac.reference == pytest.approx(upper)
    assert channel.reference == pytest.approx(upper)
    assert channel.lower_bound == pytest.approx(lower)
    assert channel.output == pytest.approx(lower)


@pytest.mark.parametrize(
    ("part", "code"),
    [(AD5410, 0xFFF), (AD5420, 0xFFFF)],
    ids=["ad5410", "ad5420"],
)
def test_the_top_code_reaches_the_reference(part: Any, code: int) -> None:
    """Full register scale maps exactly onto the range's upper bound."""
    transport = RecordingTransport(default=[0xFF, 0xFF, 0xFF])
    dac, _ = built(part, transport=transport)
    dac.configure(range="0-24mA")
    assert dac.channel(0).value == code
    assert dac.channel(0).output == pytest.approx(0.024)


def test_a_range_change_never_writes_the_data_register() -> None:
    """Only control frames leave the device while the range changes."""
    dac, transport = built()
    dac.configure(range="4-20mA")
    dac.configure(range="0-24mA")
    assert [frame[0] for frame in transport.requests] == [0x55, 0x55]


WRITE_ENTRY_POINTS = [
    pytest.param(lambda dac: setattr(dac.channel(0), "value", 1), id="value"),
    pytest.param(lambda dac: setattr(dac.channel(0), "output", 0.01), id="output"),
    pytest.param(lambda dac: dac.write_all([1]), id="write-all"),
]


@pytest.mark.parametrize("write", WRITE_ENTRY_POINTS)
def test_writing_while_disabled_raises_without_a_transfer(
    write: Callable[[Any], None],
) -> None:
    """The guard sits ahead of the transfer on every write path."""
    dac, transport = built()
    dac.configure(range="4-20mA")
    issued = len(transport.requests)
    with pytest.raises(DACOutputDisabledError):
        write(dac)
    assert len(transport.requests) == issued


def test_enable_output_before_configure_uses_the_default_range() -> None:
    """An early enable sends a valid 4-20 mA word and sets the span."""
    dac, transport = built()
    dac.enable_output()
    assert transport.requests == [FOUR_TWENTY_ENABLED]
    assert dac.reference == pytest.approx(0.020)
    assert dac.channel(0).lower_bound == pytest.approx(0.004)
    dac.enable_output()
    assert transport.requests == [FOUR_TWENTY_ENABLED]


def test_disable_output_clears_outen_and_blocks_writes() -> None:
    """A disabled output keeps its range but refuses further code writes."""
    dac, transport = built()
    dac.configure(range="0-24mA")
    dac.enable_output()
    dac.disable_output()
    assert transport.requests[-1] == [0x55, 0x00, 0x07]
    issued = len(transport.requests)
    with pytest.raises(DACOutputDisabledError):
        dac.channel(0).value = 1
    assert len(transport.requests) == issued


@pytest.mark.parametrize(
    ("part", "code", "frame"),
    [
        pytest.param(AD5410, 0x0ABC, [0x01, 0xAB, 0xC0], id="ad5410"),
        pytest.param(AD5420, 0x1234, [0x01, 0x12, 0x34], id="ad5420"),
    ],
)
def test_a_code_write_sends_the_datasheet_frame(
    part: Any, code: int, frame: list[int]
) -> None:
    """The enabled write follows the control frame with the data frame."""
    dac, transport = built(part)
    dac.enable_output()
    dac.channel(0).value = code
    assert transport.requests == [FOUR_TWENTY_ENABLED, frame]


@pytest.mark.parametrize(
    ("part", "rx", "code"),
    [
        pytest.param(AD5410, [0x00, 0xAB, 0xC0], 0x0ABC, id="ad5410"),
        pytest.param(AD5420, [0x00, 0xAB, 0xCD], 0xABCD, id="ad5420"),
    ],
)
def test_a_value_read_uses_two_transactions(
    part: Any, rx: list[int], code: int
) -> None:
    """A read request is followed by a NOP that clocks the answer out."""
    transport = RecordingTransport(responses=[[0, 0, 0], rx])
    dac, _ = built(part, transport=transport)
    assert dac.channel(0).value == code
    assert transport.requests == [[0x02, 0x00, 0x01], [0x00, 0x00, 0x00]]


def test_a_value_read_works_while_the_output_is_disabled() -> None:
    """Readback has no OUTEN guard: the register is readable either way."""
    transport = RecordingTransport(default=[0x00, 0xAB, 0xCD])
    dac, _ = built(transport=transport)
    assert dac.channel(0).value == 0xABCD
    assert len(transport.requests) == 2


def test_read_status_decodes_the_fault_flags() -> None:
    """DB2, DB1, and DB0 are the output fault, slew, and over-temperature."""
    transport = RecordingTransport(responses=[[0, 0, 0], [0x00, 0x00, 0x05]])
    dac, _ = built(transport=transport)
    status = dac.read_status()
    assert isinstance(status, AD54x0Status)
    assert status == AD54x0Status(iout_fault=True, slew_active=False, overtemp=True)
    assert transport.requests == [[0x02, 0x00, 0x00], [0x00, 0x00, 0x00]]


def test_read_control_decodes_the_control_word() -> None:
    """Every control field is unpacked from its bit position."""
    transport = RecordingTransport(responses=[[0, 0, 0], [0x00, 0x10, 0x05]])
    dac, _ = built(transport=transport)
    control = dac.read_control()
    assert isinstance(control, AD54x0Control)
    assert control.range_code == 5
    assert control.rext is False
    assert control.outen is True
    assert control.sr_clock == 0
    assert control.sr_step == 0
    assert control.sr_enabled is False
    assert control.dcen is False
    assert control.raw == 0x1005
    assert transport.requests == [[0x02, 0x00, 0x02], [0x00, 0x00, 0x00]]


def test_reset_clears_the_shadow_and_blocks_writes() -> None:
    """Reset forgets the range, disables the output, and drops the span."""
    dac, transport = built()
    dac.configure(range="0-24mA")
    dac.enable_output()
    dac.reset()
    assert transport.requests[-1] == [0x56, 0x00, 0x01]
    assert dac.reference is None
    assert dac.channel(0).lower_bound == 0.0
    assert dac.channel(0).output is None
    with pytest.raises(DACOutputDisabledError):
        dac.channel(0).value = 0


@pytest.mark.parametrize(
    ("part", "code"),
    [(AD5410, 0x1000), (AD5420, 0x10000)],
    ids=["ad5410-above-12-bit", "ad5420-above-16-bit"],
)
def test_a_code_wider_than_the_part_is_rejected_without_a_transfer(
    part: Any, code: int
) -> None:
    """Channel validation runs before the disabled-output guard and the bus."""
    dac, transport = built(part)
    with pytest.raises(DACCodeError):
        dac.channel(0).value = code
    assert transport.requests == []


def test_an_unknown_range_is_rejected_without_a_transfer() -> None:
    """A typo cannot silently select a different range."""
    dac, transport = built()
    with pytest.raises(ValueError):
        dac.configure(range="bogus")
    with pytest.raises(TypeError):
        dac.configure(range=5)
    assert transport.requests == []


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        pytest.param({"sr_clock": 16}, ValueError, id="clock-above-15"),
        pytest.param({"sr_step": 8}, ValueError, id="step-above-7"),
        pytest.param({"slew": 1}, TypeError, id="slew-not-a-bool"),
        pytest.param({"rext": "yes"}, TypeError, id="rext-not-a-bool"),
        pytest.param({"dcen": 1}, TypeError, id="dcen-not-a-bool"),
    ],
)
def test_an_invalid_control_field_is_rejected_without_a_transfer(
    kwargs: dict[str, object], error: type[Exception]
) -> None:
    """Every field is validated before the control frame is built."""
    dac, transport = built()
    with pytest.raises(error):
        dac.configure(**kwargs)
    assert transport.requests == []


@pytest.mark.parametrize("count", [0, 2])
def test_a_channel_count_outside_the_geometry_is_rejected(count: int) -> None:
    """The single-channel part never builds a second channel."""
    transport = RecordingTransport()
    with pytest.raises(ValueError):
        AD5420(transport=transport, channels=count)
    assert transport.requests == []


def test_the_current_aliases_follow_the_device() -> None:
    """`current` aliases `output` and `i_full_scale` the upper bound."""
    transport = RecordingTransport(default=[0x00, 0x08, 0x00])
    dac, _ = built(transport=transport)
    dac.configure(range="4-20mA")
    channel = dac.channel(0)
    assert channel.i_full_scale == pytest.approx(0.020)
    assert channel.current == channel.output
    assert channel.current is not None
    assert channel.current > 0.004
