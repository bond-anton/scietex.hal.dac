# scietex.hal.dac

Digital-to-analog converters: a `DAC` device owns its output channels, and each
channel converts between a raw code and a scaled output. The package provides
transport-backed DAC device and channel objects over `scietex.hal.spi`.

The 0.1.0 release ships the Microchip MCP4xx1 dual digital potentiometers,
hardware-tested as grounded resistor dividers driven over a plain SPI
transport. The 0.2.0 release adds voltage-output SPI DACs implemented from the
manufacturer datasheets.

The abstraction is unit-neutral: the device reference is a full scale in volts
for a voltage device and in amperes for a current device, and a channel may
override it. Scaled outputs stay `None` while no reference is configured.

## Parts

### Digital potentiometers (0.1.0, hardware-tested)

| Part | Codes | Wiper storage |
| --- | --- | --- |
| MCP4231 | 7-bit, `0..127` | volatile |
| MCP4241 | 7-bit, `0..127` | non-volatile |
| MCP4251 | 8-bit, `0..255` | volatile |
| MCP4261 | 8-bit, `0..255` | non-volatile |

The non-volatile parts keep a wiper value across power cycles, but this package
has no commit path: only the volatile register is written, exactly as on the
volatile parts.

### Voltage-output DACs (0.2.0, datasheet-derived)

| Part | Channels | Resolution | Reference | SPI mode | Notes |
| --- | --- | --- | --- | --- | --- |
| MCP4802 | 2 | 8 | internal 2.048 V, GA 1x/2x | 0 | write-only |
| MCP4812 | 2 | 10 | same | 0 | |
| MCP4822 | 2 | 12 | same | 0 | |
| MCP4902 | 2 | 8 | external VREFA/VREFB per channel, GA | 0 | |
| MCP4912 | 2 | 10 | same | 0 | |
| MCP4922 | 2 | 12 | same | 0 | |
| DAC8531 | 1 | 16 | external VREF | 1 | |
| DAC8551 | 1 | 16 | external VREF | 1 | |
| DAC8552 | 2 | 16 | external VREF | 1 | has LDA/LDB load bits |
| DAC121S101 | 1 | 12 | VA (supply doubles as reference) | 1 | |
| AD5302 | 2 | 8 | external VREFA/VREFB | 1 | BUF bit |
| AD5312 | 2 | 10 | same | 1 | |
| AD5322 | 2 | 12 | same | 1 | |
| DAC8512 | 1 | 12 | internal 2.5 V x 1.6384 = fixed 4.095 V | 0 | needs LD strobe |
| AD7390 | 1 | 12 | external VREF | 0 | needs LD strobe, LD idles high |
| AD7391 | 1 | 10 | external VREF | 0 | same |

### Release notes

**0.2.0** adds 16 voltage-output SPI DACs, all datasheet-derived: write-only
caching, per-channel references, `gain`/`buffered`/`power_down` channel
attributes, and load-strobe support for the DAC8512 and AD739x. Current-output
parts (AD420, AD5410/AD5420) are planned for 0.3.0 and are **not** in this
release.

> **Honesty note: 0.2.0 is not silicon-validated.**
>
> The 0.2.0 parts are implemented from manufacturer datasheets and are **not**
> validated on silicon — no test hardware was available. Only the MCP4251
> potentiometer path is hardware-tested. A wrong bit layout would produce wrong
> output values rather than a clean error. Bug reports against real hardware
> are welcome.

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

On the potentiometers each wiper is a three-terminal divider: terminal A and
terminal B are the ends of the resistor, W is the wiper. One end is tied to
ground and the other to the reference, so the wiper voltage is a fraction of
that reference.

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
| `reference` | Full-scale voltage in volts, or omitted while unknown |
| `reference=sequence` | Per-channel references on the dual parts that have one VREF per channel |
| `channels` | Channels to expose, 1..2; omitted uses both |
| `gain` | Gain factor 1 or 2, applied to every channel (MCP48xx, MCP49xx) |
| `buffered` | Reference-input buffer, applied to every channel (MCP49xx, AD53xx) |
| `power_down` | Power-down mode, applied to every channel (see below) |
| `strobe` / `load_pin` | Load line for the strobed parts (see [Strobed parts](#strobed-parts)) |
| `transport` (alias `spi`) | Any object with `transfer(tx)` and `close()` |
| `port`, `device` | spidev bus and chip select |
| `clock_pin`, `mosi_pin`, `miso_pin`, `select_pin` | gpiozero pin wiring |
| `label`, `log_level` | Logger name and level |

On the potentiometers `r_ab` and `grounded` are additional keywords:

| Keyword | Meaning |
| --- | --- |
| `r_ab` | Total resistance in ohms; 5k, 10k, 50k, or 100k (default 10k) |
| `grounded` | Terminal tied to ground, `"B"` (default) or `"A"` |

`invert` and `max_value` are not part of the potentiometer constructor: the
wiper is always built uninverted, and the code range is fixed by the part.
Passing either keyword raises `TypeError`.

## Channel API

`channel.value` is the raw code. `channel.output` scales that code by the
reference, and `channel.unit` is the physical quantity, `"V"` for every part in
this package. `channel.voltage` is an alias of `output` on a voltage channel.

```
output = code / max_code * reference
```

The code range is `0..max_code`: `127` on a 7-bit part, `255` on an 8-bit part,
`4095` on a 12-bit part, and `65535` on a 16-bit part. This is the ideal full
scale; rounding to a code can make the reported output up to 1 LSB optimistic.

On the readable potentiometers `value` is a live read: every access is a new bus
transaction, nothing is cached. The 0.2.0 voltage DACs are all write-only and
are described next.

The setter clamps instead of rejecting: an output below zero becomes the bottom
of the scale (code 0 when grounded B) and an output above the reference becomes
the top code. Setting `output` while no reference is configured raises
`DACReferenceError`.

### Write-only semantics

Every 0.2.0 part is write-only. `channel.value` returns the code cached from the
last successful write, starting at `0` after construction to match the power-on
register; no bus read happens. `channel.readback()` raises `DACReadbackError`,
and `dac.readable` (as well as `channel.readable`) is `False`.

A write-only device cannot verify what the chip actually latched, so the cached
code is the library's record of the last frame it sent, not a measurement. A
single write is one bus transfer, and `write_all()` is one transfer per channel
— no read-back follows either call.

`device.channels` is a tuple in index order and `channel(n)` raises `IndexError`
outside the range. A part built with `channels=1` exposes channel 0 only.

### Grounding

On the potentiometers, `grounded="B"` makes the output rise with the code: code
0 is 0 V, the top code is the reference. `grounded="A"` mirrors the curve: code
0 is the reference and the top code is 0 V. The raw `value` is the same under
either wiring; only the scaled `output` changes direction.

## Reference and span

`device.reference` (alias `device.v_ref`) is the device's reference, unscaled.
`channel.reference_override` (alias `channel.v_ref` on a voltage channel) is the
per-channel reference that wins over the device default.

`channel.reference` is the **effective full scale after gain**, and `output`
always uses it. So on an MCP48xx channel at gain 2, `channel.reference` reads
`4.096`, and `channel.value = 4095` gives `output == 4.096`.

`gain` is 1 or 2. The power-on default is 2 on MCP48xx/MCP49xx — the GA bit reads
0 for 2x — and changing `gain` changes `channel.reference` but never the code.
At gain 1 the MCP48xx span is exactly 2.048 V; at gain 2 it is 4.096 V.

Per-channel references: MCP49xx, AD53xx, and DAC8552 accept
`reference=(vref_a, vref_b)`. A scalar sets the device-wide default. Per-channel
overrides beat the default.

`DAC8512` has a fixed internal full scale. It resolves its reference to `4.095`
whether you pass `None` or `4.095`; passing any other value raises `ValueError`
at construction.

An unset reference leaves `.output` at `None`; setting `.output` then raises
`DACReferenceError`. On `DAC121S101` pass `reference=<VA rail voltage>`, because
the supply rail is also the full scale.

## Configuration bits

`gain`, `buffered`, and `power_down` are mutable channel attributes. They are
applied on the next code write and never cause an immediate transfer, because
they travel inside the command frame. The constructor accepts the same names and
applies them to every channel.

`DAC8552` has **no** `buffered` attribute: its Buffer Select bit chooses the data
buffer (A or B), not the reference-input buffer.

Power-down field widths:

| Parts | Field |
| --- | --- |
| MCP48xx, MCP49xx | `0` normal, `1` shutdown (one SHDN bit) |
| DAC85xx, DAC121S101, AD53xx | `0..3` (two PD bits: normal, 1k to GND, 100k to GND, high impedance) |

The DAC8512 and AD739x have no power-down field in this package.

## Strobed parts

`DAC8512`, `AD7390`, and `AD7391` need the `LD` load line. It idles **high** and
is pulsed low then high for each write to latch the frame. The constructor takes
exactly one of:

- `strobe=` — a `LoadStrobe` with `pulse()` and `close()`;
- `load_pin=` — a gpiozero pin number; the constructor builds a `GpiozeroStrobe`.

Passing neither raises `DACStrobeError`; passing both raises `ValueError`. The
GPIO version is `GpiozeroStrobe(pin, pulse_width=1e-5)`, where the default low
time is 10 microseconds:

```python
from scietex.hal.dac import DAC8512

with DAC8512(load_pin=17) as dac:
    dac.channel(0).output = 2.0
```

## Wiring notes

- The `LDAC` input must be tied low on MCP48xx/MCP49xx/AD53xx unless the caller
  drives it; the package does not. A floating or high LDAC accepts the input
  word but does not latch the DAC register.
- The SPI mode is per the part table: mode 0 for MCP48xx, MCP49xx, DAC8512, and
  AD739x; mode 1 for DAC85xx, DAC121S101, and AD53xx.
- The gpiozero pin backend is SPI mode 0 only. A mode-1 part must be constructed
  with `transport=`/`spi=` built from `SpiDevTransport(..., mode=1)` instead of
  the pin keywords.

## Transport and lifecycle

Every device accepts `transport=`, or its legacy alias `spi=`, and uses that
object as is. Without one, `port=` and `device=` open the spidev backend, while
any pin keyword selects the gpiozero backend.

`device.transport` and `device.spi` expose the bus handle, `device.close()`
releases it, and `device.closed` reports whether it is closed. A device is a
context manager: leaving the `with` block closes the transport.

## Reading and writing

```python
codes = device.read_all()  # one code per channel
written = device.write_all((0, 128))
```

Both return tuples in index order. On a readable device every element is a
separate bus transaction — the calls read and write the device, they do not
replay a cached buffer. On a write-only device both calls use the cached codes:
`read_all()` issues no bus traffic, and `write_all()` issues one transfer per
channel.

A single write to a readable potentiometer is two transactions: the wiper
command followed by a register read-back, so the value a channel reports
afterwards is what the device returned, not what the caller submitted.
`write_all` validates the whole sequence before the first transaction, so a
rejected code cannot leave the device partially updated.

## Errors

```
DACError
├── DACReferenceError   (ValueError)  output requested or set with no reference
├── DACCodeError        (ValueError)  raw code outside 0..max_code
├── DACReadbackError    (RuntimeError)  readback requested from a write-only part
└── DACStrobeError      (RuntimeError)  strobed part used without a load strobe
```

`TransportError` and `TransportClosed` come from `scietex.hal.spi` and mean the
bus transaction failed or the transport was already closed. A malformed
potentiometer answer is rejected by the wrapped device with a `ValueError` naming
the frame.

## Testing

```bash
pytest                 # unit tests, no hardware needed
RUN_HARDWARE_TESTS=1 pytest tests/test_hardware.py
```

The current suite reports **612 passed, 1 skipped**. The unit tests drive a
scripted transport and never open a real bus. The skip is the hardware `MCP4251`
test gated by `RUN_HARDWARE_TESTS=1`, which also needs a device at
`/dev/spidev0.1`; CI never enables it. No 0.2.0 part has a hardware test.

Other checks:

```bash
tox -e format,lint,type
```

## License

This project is licensed under the **MIT License** - see the LICENSE file for
details.
