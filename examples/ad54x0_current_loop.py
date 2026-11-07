#!/usr/bin/env python3
"""Drive an AD5420 on /dev/spidev0.0 through a 4-20 mA sweep."""

from scietex.hal.dac import AD5420

LEVELS = (0.004, 0.012, 0.020)


def main() -> None:
    """Configure a 4-20 mA range, sweep three currents, and report status."""
    # The AD5420 is readable over SDO, but the byte order of the answer has
    # never been validated on hardware; check it on a bench before trusting
    # readback values.
    with AD5420(port=0, device=0) as dac:
        try:
            dac.configure(range="4-20mA")
            dac.enable_output()
            channel = dac.channel(0)
            print(f"reference: {channel.reference:.3f} A")
            print(f"lower_bound: {channel.lower_bound:.3f} A")

            for current in LEVELS:
                channel.current = current
                print(f"code={channel.value:5d} output={channel.output:.3f} A")

            status = dac.read_status()
            print(
                f"status: iout_fault={status.iout_fault} "
                f"slew_active={status.slew_active} overtemp={status.overtemp}"
            )
        finally:
            dac.reset()


if __name__ == "__main__":
    main()
