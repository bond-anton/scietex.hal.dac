"""AD54x0 frame encoding: exact bytes, bit layout, and readback decoding."""

import pytest

from scietex.hal.dac import DACReadbackError
from scietex.hal.dac.ad54x0 import (
    decode_24,
    encode_control,
    encode_data,
    encode_nop,
    encode_read_request,
    encode_reset,
)


@pytest.mark.parametrize(
    ("code", "resolution", "frame"),
    [
        pytest.param(0x1234, 16, [0x01, 0x12, 0x34], id="16-bit-0x1234"),
        pytest.param(0xFFFF, 16, [0x01, 0xFF, 0xFF], id="16-bit-full"),
        pytest.param(0x0ABC, 12, [0x01, 0xAB, 0xC0], id="12-bit-0x0abc"),
        pytest.param(0x0FFF, 12, [0x01, 0xFF, 0xF0], id="12-bit-full"),
    ],
)
def test_encode_data_left_aligns_the_code(
    code: int, resolution: int, frame: list[int]
) -> None:
    """The address leads and a narrower code keeps its MSB at bit 15."""
    assert encode_data(code, resolution) == frame


def test_encode_data_masks_a_code_wider_than_the_part() -> None:
    """Only the low `resolution` bits reach the register."""
    assert encode_data(0xFFFF, 12) == [0x01, 0xFF, 0xF0]


@pytest.mark.parametrize(
    ("kwargs", "frame"),
    [
        pytest.param(
            {"outen": True, "range_code": 0b101}, [0x55, 0x10, 0x05], id="4-20"
        ),
        pytest.param(
            {"outen": True, "range_code": 0b110}, [0x55, 0x10, 0x06], id="0-20"
        ),
        pytest.param(
            {"outen": True, "range_code": 0b111}, [0x55, 0x10, 0x07], id="0-24"
        ),
        pytest.param(
            {"outen": False, "range_code": 0b101},
            [0x55, 0x00, 0x05],
            id="4-20-disabled",
        ),
        pytest.param(
            {"outen": True, "range_code": 0b101, "sr_enabled": True},
            [0x55, 0x10, 0x15],
            id="slew-enabled",
        ),
        pytest.param(
            {"outen": True, "range_code": 0b101, "rext": True},
            [0x55, 0x30, 0x05],
            id="external-resistor",
        ),
        pytest.param(
            {"outen": True, "range_code": 0b101, "dcen": True},
            [0x55, 0x10, 0x0D],
            id="daisy-chain",
        ),
        pytest.param(
            {"outen": True, "range_code": 0b101, "sr_clock": 0xF},
            [0x55, 0x1F, 0x05],
            id="slew-clock-max",
        ),
        pytest.param(
            {"outen": True, "range_code": 0b101, "sr_step": 0x7},
            [0x55, 0x10, 0xE5],
            id="slew-step-max",
        ),
    ],
)
def test_encode_control_matches_the_datasheet_frame(
    kwargs: dict[str, int | bool], frame: list[int]
) -> None:
    """Every documented control row encodes to its exact three bytes."""
    assert encode_control(**kwargs) == frame


@pytest.mark.parametrize(
    ("kwargs", "bit"),
    [
        pytest.param({"rext": True}, 0x2000, id="rext-bit-13"),
        pytest.param({"outen": True}, 0x1000, id="outen-bit-12"),
        pytest.param({"sr_enabled": True}, 0x0010, id="sren-bit-4"),
        pytest.param({"dcen": True}, 0x0008, id="dcen-bit-3"),
    ],
)
def test_the_control_flags_own_their_bit(kwargs: dict[str, bool], bit: int) -> None:
    """Each flag flips one bit of the control field and nothing else."""
    fields: dict[str, object] = {"outen": False, "range_code": 0b101}
    fields.update(kwargs)
    frame = encode_control(**fields)
    word = (frame[0] << 16) | (frame[1] << 8) | frame[2]
    assert word == 0x550005 | bit


def test_the_slew_clock_sits_in_bits_eleven_to_eight() -> None:
    """A 15 in the 4-bit clock field lands in DB11..DB8."""
    frame = encode_control(outen=True, range_code=0b101, sr_clock=0xF)
    assert (frame[1] << 8) & 0x0F00 == 0x0F00


def test_the_slew_step_sits_in_bits_seven_to_five() -> None:
    """A 7 in the 3-bit step field lands in DB7..DB5."""
    frame = encode_control(outen=True, range_code=0b101, sr_step=0x7)
    assert frame[2] & 0xE0 == 0xE0


@pytest.mark.parametrize(
    ("address", "frame"),
    [
        pytest.param(0b01, [0x02, 0x00, 0x01], id="data"),
        pytest.param(0b00, [0x02, 0x00, 0x00], id="status"),
        pytest.param(0b10, [0x02, 0x00, 0x02], id="control"),
    ],
)
def test_encode_read_request_addresses_the_register(
    address: int, frame: list[int]
) -> None:
    """The readback request carries the two-bit register address."""
    assert encode_read_request(address) == frame


def test_encode_nop_is_three_zero_bytes() -> None:
    """The NOP frame clocks a pending answer out without a new command."""
    assert encode_nop() == [0x00, 0x00, 0x00]


def test_encode_reset_is_the_documented_word() -> None:
    """The reset frame is 0x56 0x00 0x01."""
    assert encode_reset() == [0x56, 0x00, 0x01]


def test_decode_24_joins_three_bytes_big_endian() -> None:
    """The first byte is the most significant one."""
    assert decode_24([0x00, 0xAB, 0xC0]) == 0xABC0


def test_decode_24_reverses_three_bytes_when_swapped() -> None:
    """A swapped board layout reads the same bytes the other way round."""
    assert decode_24([0x00, 0xAB, 0xC0], swap=True) == 0xC0AB00


def test_decode_24_accepts_a_single_coalesced_word() -> None:
    """A transport that hands the whole word over needs no reassembly."""
    assert decode_24([0x123456]) == 0x123456


def test_decode_24_masks_a_single_word_to_24_bits() -> None:
    """Only the low three bytes of a coalesced answer are part of the word."""
    assert decode_24([0xFF123456]) == 0x123456


def test_decode_24_rejects_a_two_byte_answer() -> None:
    """A short frame is neither a word nor a byte triple."""
    with pytest.raises(DACReadbackError) as excinfo:
        decode_24([0x00, 0xAB])
    message = str(excinfo.value)
    assert "2" in message
    assert "3" in message


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        pytest.param({"sr_clock": 16}, ValueError, id="clock-above-15"),
        pytest.param({"sr_step": 8}, ValueError, id="step-above-7"),
        pytest.param({"range_code": 8}, ValueError, id="range-code-above-7"),
        pytest.param({"sr_clock": "1"}, TypeError, id="clock-not-an-int"),
        pytest.param({"sr_step": "1"}, TypeError, id="step-not-an-int"),
        pytest.param({"range_code": "1"}, TypeError, id="range-not-an-int"),
        pytest.param({"outen": 1}, TypeError, id="outen-not-a-bool"),
        pytest.param({"rext": "yes"}, TypeError, id="rext-not-a-bool"),
    ],
)
def test_a_control_field_outside_its_width_is_rejected(
    kwargs: dict[str, object], error: type[Exception]
) -> None:
    """A field is checked against the bits it occupies before packing."""
    fields: dict[str, object] = {"outen": True, "range_code": 0b101}
    fields.update(kwargs)
    with pytest.raises(error):
        encode_control(**fields)


@pytest.mark.parametrize("resolution", [0, 17])
def test_a_resolution_outside_the_data_field_is_rejected(resolution: int) -> None:
    """The code cannot be left-aligned in a field it does not fit."""
    with pytest.raises(ValueError):
        encode_data(0, resolution)
