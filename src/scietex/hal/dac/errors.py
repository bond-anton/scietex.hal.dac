"""Errors raised by the DAC package."""


class DACError(Exception):
    """Base class for errors raised by this package."""


class DACReferenceError(DACError, ValueError):
    """Raised when output is requested or set with no reference configured."""


class DACCodeError(DACError, ValueError):
    """Raised when a raw code falls outside `0..max_code`."""
