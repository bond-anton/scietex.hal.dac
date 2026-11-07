"""Raw code access of a channel."""

import pytest
from conftest import MemoryBackend

from scietex.hal.dac import DAC, DACChannel, DACCodeError, DividerChannel


class CountedCodes:
    """Keep codes on the device and count every codec call."""

    def _read_code(self) -> int:
        self._dac.reads += 1
        return self._dac.codes[self.index]

    def _write_code(self, code: int) -> int:
        self._dac.writes += 1
        self._dac.codes[self.index] = code
        return code


class CountedChannel(CountedCodes, DACChannel):
    """Plain channel that counts codec calls."""


class CountedDividerChannel(CountedCodes, DividerChannel):
    """Divider channel that counts codec calls."""


class CountingDAC(DAC):
    """Two 7-bit channels backed by memory."""

    _CHANNELS = 2
    _RESOLUTION = 7
    _CHANNEL_CLASS = CountedChannel

    def __init__(self) -> None:
        self.codes = [0] * self._CHANNELS
        self.reads = 0
        self.writes = 0
        super().__init__(backend=MemoryBackend())


def test_value_is_the_raw_code_under_either_grounding() -> None:
    """Grounding changes the scaled output, never the reported code."""
    dac = CountingDAC()
    dac.codes = [5, 100]
    assert CountedDividerChannel(dac, 0, grounded="B").value == 5
    assert CountedDividerChannel(dac, 1, grounded="A").value == 100


def test_value_is_an_int() -> None:
    """A raw code is an integer, not a scaled float."""
    dac = CountingDAC()
    dac.codes = [7, 0]
    assert isinstance(CountedChannel(dac, 0).value, int)


def test_two_reads_are_two_codec_calls() -> None:
    """Nothing is cached: every read asks the device again."""
    dac = CountingDAC()
    dac.codes = [1, 2]
    channel = CountedChannel(dac, 0)
    assert channel.value == 1
    assert channel.value == 1
    assert dac.reads == 2


def test_max_code_is_the_full_scale_of_the_device() -> None:
    """The channel borrows the device resolution and accepts its top code."""
    dac = CountingDAC()
    channel = CountedChannel(dac, 0)
    assert channel.max_code == 127
    channel.value = 127
    assert dac.codes[0] == 127
    assert channel.value == 127


@pytest.mark.parametrize("code", [-1, 128])
def test_codes_outside_the_full_scale_are_rejected(code: int) -> None:
    """An out-of-range code is a DACCodeError, which is a ValueError."""
    dac = CountingDAC()
    channel = CountedChannel(dac, 0)
    with pytest.raises(DACCodeError) as excinfo:
        channel.value = code
    assert isinstance(excinfo.value, ValueError)


def test_a_fractional_code_is_a_value_error() -> None:
    """Codes are whole steps; the fraction is rejected as a value error."""
    dac = CountingDAC()
    channel = CountedChannel(dac, 0)
    with pytest.raises(ValueError) as excinfo:
        channel.value = 1.5
    assert not isinstance(excinfo.value, DACCodeError)


@pytest.mark.parametrize("code", [True, "1"])
def test_non_numeric_codes_are_type_errors(code: object) -> None:
    """Bool and string are caller mistakes, not codes."""
    dac = CountingDAC()
    channel = CountedChannel(dac, 0)
    with pytest.raises(TypeError):
        channel.value = code


def test_a_rejected_code_performs_no_write() -> None:
    """Validation runs before the device is touched."""
    dac = CountingDAC()
    dac.codes = [3, 4]
    channel = CountedChannel(dac, 0)
    for code in (-1, 128, 1.5):
        with pytest.raises(ValueError):
            channel.value = code
    assert dac.writes == 0
    assert dac.codes == [3, 4]
