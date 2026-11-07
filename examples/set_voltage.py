"""Drive both wipers of an MCP4251 wired to /dev/spidev0.1."""

from scietex.hal.dac import MCP4251

REFERENCE = 3.3


def main() -> None:
    """Set and report a voltage on each wiper."""
    with MCP4251(port=0, device=1, reference=REFERENCE) as dac:
        dac.channel(0).voltage = REFERENCE / 2
        dac.channel(1).output = REFERENCE / 4

        for channel in dac.channels:
            voltage = channel.voltage
            if voltage is None:
                raise RuntimeError("reference is not configured")
            print(f"channel {channel.index}: code={channel.value:3d} {voltage:.3f} V")


if __name__ == "__main__":
    main()
