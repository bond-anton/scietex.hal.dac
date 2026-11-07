# scietex.hal.dac

Digital-to-analog converters: a `DAC` device owns its output channels, and each
channel converts between a raw code and a scaled output. The package ships the
Microchip MCP4xx1 dual digital potentiometers, exposed as grounded resistor
dividers driven over a plain SPI transport.

The abstraction is unit-neutral: the device reference is a full scale in volts
for a voltage device and in amperes for a current device, and a channel may
override it. Scaled outputs stay `None` while no reference is configured.

## Parts

| Part | Codes | Wiper storage |
| --- | --- | --- |
| MCP4231 | 7-bit, `0..127` | volatile |
| MCP4241 | 7-bit, `0..127` | non-volatile |
| MCP4251 | 8-bit, `0..255` | volatile |
| MCP4261 | 8-bit, `0..255` | non-volatile |

The non-volatile parts keep a wiper value across power cycles, but this package
has no commit path: only the volatile register is written, exactly as on the
volatile parts.

## Install

```bash
pip install scietex.hal.dac[spi]        # Linux spidev backend
pip install scietex.hal.dac[gpiozero]   # gpiozero backend
```

The base package installs without either backend. A device built from the
default keywords needs `spidev`; pin keywords (`clock_pin`, `mosi_pin`,
`miso_pin`, `select_pin`) need `gpiozero`. A missing backend raises
`ImportError` naming the extra to install.

## Wiring

| Signal | Connection |
| --- | --- |
| SCLK | SPI clock |
| SDI | SPI MOSI |
| SDO | SPI MISO |
| CS | SPI chip select |
| V_DD | Supply, 2.7 V to 5.5 V |
| V_SS | Ground |

Each wiper is a three-terminal divider: terminal A and terminal B are the ends
of the resistor, W is the wiper. One end is tied to ground and the other to the
reference, so the wiper voltage is a fraction of that reference.

## Usage

```python
from scietex.hal.dac import MCP4251

device = MCP4251(port=0, device=1, reference=3.3)  # /dev/spidev0.1
try:
    code = device.channel(0).value  # raw 8-bit code, 0..255
    voltage = device.channel(0).voltage
    print(code, voltage)
finally:
    device.close()
```

`MCP4251(port=0, device=1, reference=3.3)` is also a context manager; leaving the
`with` block closes the transport:

```python
with MCP4251(port=0, device=1, reference=3.3) as device:
    print(device.read_all())
```

Constructor keywords:

| Keyword | Meaning |
| --- | --- |
| `r_ab` | Total resistance in ohms; 5k, 10k, 50k, or 100k (default 10k) |
| `channels` | Channels to expose, 1..2; omitted uses both |
| `reference` | Full-scale voltage in volts, or omitted while unknown |
| `grounded` | Terminal tied to ground, `"B"` (default) or `"A"` |
| `transport` (alias `spi`) | Any object with `transfer(tx)` and `close()` |
| `port`, `device` | spidev bus and chip select |
| `clock_pin`, `mosi_pin`, `miso_pin`, `select_pin` | gpiozero pin wiring |
| `label`, `log_level` | Logger name and level |

`invert` and `max_value` are not part of the constructor: the wiper is always
built uninverted, and the code range is fixed by the part. Passing either
keyword raises `TypeError`.

## Codes and outputs

`channel.value` is the raw code the wiper register holds. It is a live read:
every access is a new bus transaction, nothing is cached. The range is
`0..max_code`, which is `127` on a 7-bit part and `255` on an 8-bit part.

`channel.output` scales that code by the reference (grounded B shown here; see
[Grounding](#grounding)):

```
output = code / max_code * reference
```

With no reference configured, `output` is `None` — the library will not guess a
reference. Setting `device.reference = 3.3` later starts scaling new readings;
the codes themselves never change. `device.v_ref` and `channel.v_ref` are
aliases.

The setter clamps instead of rejecting: an output below zero becomes the bottom
of the scale (code 0 when grounded B) and an output above the reference becomes
the top code. Setting `output` while no reference is configured raises
`DACReferenceError`.

## Grounding

`grounded="B"` makes the output rise with the code: code 0 is 0 V, the top code
is the reference. `grounded="A"` mirrors the curve: code 0 is the reference and
the top code is 0 V. The raw `value` is the same under either wiring; only the
scaled `output` changes direction.

## Geometry

| Part | Channels | Resolution | Top code |
| --- | --- | --- | --- |
| MCP4231 | 2 | 7 | 127 |
| MCP4241 | 2 | 7 | 127 |
| MCP4251 | 2 | 8 | 255 |
| MCP4261 | 2 | 8 | 255 |

`device.channels` is a tuple in index order and `channel(n)` raises `IndexError`
outside the range. A part built with `channels=1` exposes channel 0 only.

## Reading and writing

```python
codes = device.read_all()  # one code per channel
written = device.write_all((0, 128))
```

Both return tuples in index order. Every element is a separate bus transaction —
the calls read and write the device, they do not replay a cached buffer.

A single write is two transactions: the wiper command followed by a register
read-back, so the value a channel reports afterwards is what the device
returned, not what the caller submitted. `write_all` validates the whole
sequence before the first transaction, so a rejected code cannot leave the
device partially updated.

## Errors

- `TransportError` and `TransportClosed` (from `scietex.hal.spi`) mean the bus
  transaction failed or the transport was already closed.
- `DACCodeError` (a `ValueError`) means a raw code is outside `0..max_code`.
- `DACReferenceError` (a `ValueError`) means an output was requested while no
  reference is configured.
- A malformed device answer is rejected by the wrapped potentiometer with a
  `ValueError` naming the frame.

## Testing

```bash
pytest                 # unit tests, no hardware needed
RUN_HARDWARE_TESTS=1 pytest tests/test_hardware.py
```

The unit tests drive a scripted transport and never open a real bus. The
hardware test needs an MCP4251 on `/dev/spidev0.1` and is skipped unless
`RUN_HARDWARE_TESTS=1` is set; CI never enables it.

Other checks:

```bash
tox -e format,lint,type
```

## License

This project is licensed under the **MIT License** - see the LICENSE file for
details.
