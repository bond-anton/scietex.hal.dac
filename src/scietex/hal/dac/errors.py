"""Errors raised by the DAC package."""


class DACError(Exception):
    """Base class for errors raised by this package."""


class DACReferenceError(DACError, ValueError):
    """Raised when output is requested or set with no reference configured."""


class DACCodeError(DACError, ValueError):
    """Raised when a raw code falls outside `0..max_code`."""


class DACReadbackError(DACError, RuntimeError):
    """Raised when a register read is requested from a write-only device."""


class DACStrobeError(DACError, RuntimeError):
    """Raised when a strobed device is used without a load strobe."""


class DACOutputDisabledError(DACError, RuntimeError):
    """Raised when a code write targets a channel whose output is disabled."""
