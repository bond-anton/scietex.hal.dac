"""Drive one channel of an MCP4822 on /dev/spidev0.0."""

from scietex.hal.dac import MCP4822

TARGET_VOLTAGE = 1.0


def main() -> None:
    """Select 1x gain, set a 1.0 V output, and report the cached code."""
    with MCP4822(port=0, device=0, gain=1) as dac:
        channel = dac.channel(0)
        print(f"reference: {channel.reference:.3f} V")
        channel.output = TARGET_VOLTAGE
        # The part is write-only, so .value is the code cached from the write.
        print(f"code: {channel.value} output: {channel.output:.3f} V")


if __name__ == "__main__":
    main()
