"""Byte packing for the command frames of a device family."""

from .__helpers import check_integer


def pack(word: int, length: int) -> list[int]:
    """
    Split an MSB-first word into `length` big-endian bytes.

    :param word: Value to split (int).
    :param length: Number of bytes to emit (int).
    :return: Bytes from most to least significant (list of int).
    :raises TypeError: If `word` or `length` is not an integer number, or is a
        `bool`.
    :raises ValueError: If `length` is not positive, or `word` does not fit in
        `length` bytes.
    """
    length = check_integer(length)
    if length <= 0:
        raise ValueError(f"Expected a positive byte length, got {length}")
    word = check_integer(word)
    limit = 1 << (8 * length)
    if not 0 <= word < limit:
        raise ValueError(f"Expected a word within 0..{limit - 1}, got {word}")
    return [(word >> (8 * shift)) & 0xFF for shift in reversed(range(length))]
