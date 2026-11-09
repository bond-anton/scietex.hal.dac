# scietex.hal.dac

Digital-to-analog converters: a `DAC` device owns its output channels, and each
channel converts between a raw code and a scaled output. The package provides
transport-backed DAC device and channel objects over `scietex.hal.spi`.

The 0.1.0 release ships the Microchip MCP4xx1 dual digital potentiometers,
hardware-tested as grounded resistor dividers driven over a plain SPI
transport. The 0.2.0 release adds voltage-output SPI DACs implemented from the
manufacturer datasheets. The 0.3.0 release adds current-output parts (AD420,
AD5410, AD5420) and an affine output model that can start at a non-zero floor.
The 0.4.0 release re-asserts the MCP4xxx terminal connections on every open and
exposes `enable_output()` / `disable_output()` on those parts.

The abstraction is unit-neutral: the device reference is the **upper** bound an
output maps to, in volts for a voltage device and in amperes for a current
device, and a channel may override it. A device whose span does not start at
zero declares a floor instead; the reference is never the span width. Scaled
outputs stay `None` while no reference is configured.

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

The terminal-connect (TCON) register is volatile on every part and powers up
with A, W, and B disconnected, so the wiper register alone does not drive an
output. Construction asserts the connected state and `output_enabled` reports
it; `disable_output()` disconnects both wipers (and asserts shutdown), while
`enable_output(force=True)` re-asserts the state after a pot power cycle. A code
write while the output is disabled raises `DACOutputDisabledError`.

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

### Current-output DACs (0.3.0, datasheet-derived)

| Part | Channels | Resolution | Ranges | SPI mode | Notes |
| --- | --- | --- | --- | --- | --- |
| AD420 | 1 | 16 | 0–5 V, 4–20 mA, 0–20 mA, 0–24 mA (RANGE SELECT pins) | 0 | write-only, needs LATCH strobe; other voltage ranges need an external buffer and are not modelled |
| AD5410 | 1 | 12 | 4–20, 0–20, 0–24 mA (control register) | 0 | readable over SDO, output disabled at power-on |
| AD5420 | 1 | 16 | same | 0 | same |

### Release notes

**0.4.0** makes the MCP4xxx potentiometers assert their terminal-connect (TCON)
state on every open, because the register is volatile and powers up
disconnected — a power cycle previously left the wiper high-impedance while the
wiper register still read back the written code. It also adds
`output_enabled`, `enable_output()`, and `disable_output()` to those parts, with
a `DACOutputDisabledError` guard on code writes. Everything else is unchanged.

**0.3.0** adds the current-output parts AD420, AD5410, and AD5420; the affine
`lower_bound` output model (backward compatible — the floor defaults to `0.0`);
`configure`/`enable_output`/`disable_output`/`reset` and SDO readback with
status and control decoding on the AD54x0 parts; and `GpiozeroRisingStrobe` for
the AD420 LATCH line. The 0.2.0 parts are unchanged.

**0.2.0** adds 16 voltage-output SPI DACs, all datasheet-derived: write-only
caching, per-channel references, `gain`/`buffered`/`power_down` channel
attributes, and load-strobe support for the DAC8512 and AD739x.

> **Honesty note: 0.2.0 and 0.3.0 are not silicon-validated.**
>
> The 0.2.0 and 0.3.0 parts are implemented from manufacturer datasheets and are
> **not** validated on silicon — no test hardware was available. Only the
> MCP4251 potentiometer path is hardware-tested. A wrong bit layout would produce
> wrong output values rather than a clean error. Bug reports against real
> hardware are welcome.
>
> The current-output parts are not silicon-validated in a stricter sense. The
> AD420 has **no readback at all**: it can only be checked with an external
> ammeter on the loop. The AD5410/AD5420 do have SDO readback, but the byte
> order of the answer has never been verified on hardware; the readback path is
> the first thing to check on a bench, because a wrong byte order silently
> returns plausible but wrong codes.

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
| `reference` | Upper bound in volts or amperes, or omitted while unknown |
| `reference=sequence` | Per-channel references on the dual parts that have one VREF per channel |
| `channels` | Channels to expose, 1..2 on dual parts; omitted uses the geometry (AD54x0 accepts only 1; AD420 has no such keyword) |
| `range` | AD420 only: declared range/wiring, `"0-5V"`, `"4-20mA"`, `"0-20mA"`, `"0-24mA"` |
| `gain` | Gain factor 1 or 2, applied to every channel (MCP48xx, MCP49xx) |
| `buffered` | Reference-input buffer, applied to every channel (MCP49xx, AD53xx) |
| `power_down` | Power-down mode, applied to every channel (see below) |
| `strobe` / `load_pin` / `latch_pin` | Load line for the strobed parts (see [Strobed parts](#strobed-parts)) |
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

`channel.value` is the raw code. `channel.output` maps that code onto the span
from `lower_bound` to `reference`, and `channel.unit` is the physical quantity:
`"V"` for a voltage channel and `"A"` for a current channel. `channel.voltage`
aliases `output` on a voltage channel; `channel.current` aliases it on a current
channel.

The code range is `0..max_code`: `127` on a 7-bit part, `255` on an 8-bit part,
`4095` on a 12-bit part, and `65535` on a 16-bit part. The scaling itself is
affine and described in [Affine output scaling](#affine-output-scaling).

On the readable parts `value` is a live read: every access is a new bus
transaction, nothing is cached. The write-only parts are all of the 0.2.0
voltage DACs and the AD420; they are described next.

The output setter clamps instead of rejecting: a value below the floor becomes
the floor and a value above the reference becomes the reference. Setting
`output` while no reference is configured raises `DACReferenceError`.

### Write-only semantics

The 0.2.0 voltage parts and the AD420 are write-only. `channel.value` returns the
code cached from the last successful write, starting at `0` after construction
to match the power-on register; no bus read happens. `channel.readback()` raises
`DACReadbackError`, and `dac.readable` (as well as `channel.readable`) is
`False`.

A write-only device cannot verify what the chip actually latched, so the cached
code is the library's record of the last frame it sent, not a measurement. A
single write is one bus transfer, and `write_all()` is one transfer per channel
— no read-back follows either call.

The AD5410/AD5420 are readable over SDO; their two-transaction readback is
covered in [AD5410 and AD5420](#ad5410-and-ad5420).

`device.channels` is a tuple in index order and `channel(n)` raises `IndexError`
outside the range. A part built with `channels=1` exposes channel 0 only.

### Grounding

On the potentiometers, `grounded="B"` makes the output rise with the code: code
0 is 0 V, the top code is the reference. `grounded="A"` mirrors the curve: code
0 is the reference and the top code is 0 V. The raw `value` is the same under
either wiring; only the scaled `output` changes direction.

## Affine output scaling

Every channel maps a raw code onto the span between a floor and an upper bound:

```
output = lower_bound + (code / max_code) * (reference - lower_bound)
```

`lower_bound` defaults to `0.0`, which reduces exactly to the 0.2.0 formula
`code / max_code * reference`. `reference` is the **upper** bound the top code
maps to; `lower_bound` is the **floor** code 0 maps to. `reference_override`,
`v_ref`, and `i_full_scale` all alias that upper bound, never the span width.

For a 4–20 mA range, `reference == 0.020` and `lower_bound == 0.004`, so code 0
maps to 4 mA and code `max_code` maps to 20 mA. The span is 16 mA wide while
`i_full_scale` still reads `0.020`, because it names the top of the range, not
its width.

The setter clamps the requested value into `[lower_bound, reference]` instead of
rejecting it. A channel whose floor is not below its reference cannot map a value
and raises `DACReferenceError`. This is the ideal full scale; rounding to a code
can make the reported output up to 1 LSB optimistic.

## Reference and span

`device.reference` (alias `device.v_ref`) is the device's upper bound, unscaled —
never the span width, even when the span starts at a non-zero floor.
`channel.reference_override` (alias `channel.v_ref` on a voltage channel and
`channel.i_full_scale` on a current channel) is the per-channel upper bound that
wins over the device default.

The floor is separate: `channel.lower_bound` is the output code 0 maps to. It is
`0.0` unless the device or the selected range sets it, as the 4–20 mA ranges do
(`0.004`). See [Affine output scaling](#affine-output-scaling).

`channel.reference` is the **effective upper bound after gain**, and `output`
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

These are the 0.2.0 voltage parts' in-frame configuration. The AD5410/AD5420 use
a **separate** control register written by `configure()` instead of bits in the
data word, so `gain`, `buffered`, and `power_down` do not apply to them. The AD420
has no software-configurable bits at all: its range, CLEAR, and FAULT are pins.

## AD420

The AD420 is a single 16-bit converter with a fixed internal 5 V reference. It
takes a plain 16-bit word, MSB first, with no control bits. `range=` does not
configure anything; it declares which RANGE SELECT strap the board is wired for
and selects the channel class and scaling:

| `range=` | Channel | Unit | `reference` | `lower_bound` |
| --- | --- | --- | --- | --- |
| `"0-5V"` | voltage | V | 5.0 | 0.0 |
| `"4-20mA"` | current | A | 0.020 | 0.004 |
| `"0-20mA"` | current | A | 0.020 | 0.0 |
| `"0-24mA"` | current | A | 0.024 | 0.0 |

`"4-20mA"` is the default.

**RANGE SELECT is a hardware strap.** The library neither drives nor reads those
pins, so `range=` only declares the wiring; a wrong declaration silently
mislabels every output. A 0–20 mA board declared as 4–20 mA reports a floor 4 mA
too high and a span 4 mA too narrow, while the code and the current the part
actually sources are unchanged — nothing alarms, only the scaling lies. Other
voltage ranges (bipolar, 0–10 V) need an external buffer amplifier and are not
modelled.

**LATCH idles low and latches on the rising edge.** That is the opposite
polarity of the DAC8512/AD739x `LD` load strobe, which idles high and pulses low;
wiring one as the other silently drops frames. Pass `latch_pin=` to build a
`GpiozeroRisingStrobe`, or pass a `RisingLoadStrobe` as `strobe=`. Exactly one
of the two is required: passing neither raises `DACStrobeError`, passing both
raises `ValueError`.

CLEAR and FAULT are hardware pins the library does not touch, so neither is
modelled. The part is write-only: DATA OUT only repeats the frame to the next
device in a daisy chain, so `channel.value` is the code cached from the last
successful write and `channel.readback()` raises `DACReadbackError`.

## AD5410 and AD5420

Single-channel current-output parts sharing one register set: the AD5410 is
12-bit and the AD5420 is 16-bit, with the same 4–20/0–20/0–24 mA ranges. Both
run in SPI mode 0 and source their output through the control register.

**Construction is silent.** The constructor opens the bus but sends nothing:
`reference` is `None`, `.output` is `None`, and the chip's output stays disabled
until `configure()` selects a range and/or `enable_output()` sets OUTEN.

`configure(*, range="4-20mA", slew=False, sr_clock=0, sr_step=0, rext=False,
dcen=False, force=False)` writes the control register in one 24-bit frame. It is
idempotent: identical parameters issue zero transfers unless `force=True`
re-sends the word. Changing the range updates `reference` and `lower_bound`
immediately without touching the data register, and it keeps the current
output-enable state.

`enable_output()` and `disable_output()` drive OUTEN, which is preserved across
range changes. A code write while the output is disabled raises
`DACOutputDisabledError` before any bus traffic, because the register would
change but the loop would not.

`reset()` sends the reset frame (`0x560001`) and clears the cached control state:
`reference` returns to `None` and the floor to `0.0`. The hardware RESET pin has
the same effect but is invisible to the object, so the cache then describes a
state the device no longer holds; `configure(..., force=True)` and the
`force=True` on `enable_output()`/`disable_output()` re-send their word.

**Readback costs two 24-bit transactions.** A register read is a read-request
frame followed by a NOP that clocks the answer out:

```
read status  : 02 00 00  ->  then 00 00 00
read data    : 02 00 01  ->  then 00 00 00
read control : 02 00 02  ->  then 00 00 00
```

`.value` performs both transactions on every access — nothing is cached.
`read_status()` returns `AD54x0Status(iout_fault, slew_active, overtemp)` and
`read_control()` returns `AD54x0Control(range_code, rext, outen, sr_clock,
sr_step, sr_enabled, dcen, raw)`.

Data alignment follows the resolution: the AD5410 is 12-bit left-aligned in
DB15–DB4, so the low nibble of a data frame is always zero; the AD5420 fills all
16 bits.

Range codes:

| `range=` | Code |
| --- | --- |
| `"4-20mA"` | `0b101` |
| `"0-20mA"` | `0b110` |
| `"0-24mA"` | `0b111` |

Control register bits, within the 16-bit control field after the `0x55`
address:

| Bits | Field | Meaning |
| --- | --- | --- |
| DB15–DB14 | — | unused |
| DB13 | REXT | select an external 15 kΩ current-setting resistor |
| DB12 | OUTEN | enable the current output |
| DB11–DB8 | SR_CLOCK | slew clock divider, `0..15` |
| DB7–DB5 | SR_STEP | slew step size, `0..7` |
| DB4 | SR_EN | enable the slew-rate controller |
| DB3 | DCEN | enable the daisy-chain output |
| DB2–DB0 | RANGE | range code |

`.output` on these parts is register intent only; while OUTEN is 0 it is not
evidence of the current actually flowing in the loop.

## Strobed parts

Some parts latch a clocked frame with a load line. There are two polarities, and
they are not interchangeable: a reversed strobe still transfers every frame but
latches nothing, so the register silently keeps its previous code.

| Part | Signal | Idle level | Active edge | Keyword |
| --- | --- | --- | --- | --- |
| DAC8512, AD7390, AD7391 | `LD` | high | pulses low then high | `strobe=` / `load_pin=` |
| AD420 | `LATCH` | low | pulses high then low | `strobe=` / `latch_pin=` |

The `LD` parts take exactly one of:

- `strobe=` — a `LoadStrobe` with `pulse()` and `close()` (`GpiozeroStrobe`
  drives a pin);
- `load_pin=` — a gpiozero pin number; the constructor builds a `GpiozeroStrobe`.

The AD420 takes a rising-edge strobe instead: `strobe=` may be a
`RisingLoadStrobe`, or `latch_pin=` builds a `GpiozeroRisingStrobe`.

For either family, passing neither raises `DACStrobeError`; passing both raises
`ValueError`. The GPIO versions default to a 10 microsecond pulse:
`GpiozeroStrobe(pin, pulse_width=1e-5)` and
`GpiozeroRisingStrobe(pin, pulse_width=1e-5)`.

```python
from scietex.hal.dac import DAC8512

with DAC8512(load_pin=17) as dac:
    dac.channel(0).output = 2.0
```

```python
from scietex.hal.dac import AD420

with AD420(range="4-20mA", latch_pin=17) as dac:
    dac.channel(0).current = 0.012
```

## Wiring notes

- The `LDAC` input must be tied low on MCP48xx/MCP49xx/AD53xx unless the caller
  drives it; the package does not. A floating or high LDAC accepts the input
  word but does not latch the DAC register.
- The SPI mode is per the part table: mode 0 for MCP48xx, MCP49xx, DAC8512,
  AD739x, AD420, AD5410, and AD5420; mode 1 for DAC85xx, DAC121S101, and AD53xx.
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
rejected code cannot leave the device partially updated. On the AD54x0 parts a
register read is likewise two transactions (request plus NOP), described in
[AD5410 and AD5420](#ad5410-and-ad5420).

## Errors

```
DACError
├── DACReferenceError       (ValueError)  output requested or set with no reference
├── DACCodeError            (ValueError)  raw code outside 0..max_code
├── DACReadbackError        (RuntimeError)  readback requested from a write-only part
├── DACStrobeError          (RuntimeError)  strobed part used without a load strobe
└── DACOutputDisabledError  (RuntimeError)  code write while the current output is disabled
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

The current suite reports **781 passed, 3 skipped**. The unit tests drive a
scripted transport and never open a real bus. All three skips are hardware tests
gated behind `RUN_HARDWARE_TESTS=1`: the `MCP4251` round-trip plus the new
`AD5420` readback and `AD420` write tests, each also needing a device at
`/dev/spidev0.1`. CI never enables them. No 0.2.0 part has a hardware test, and
**no current-output part has been on a bench**.

Other checks:

```bash
tox -e format,lint,type
```

## License

This project is licensed under the **MIT License** - see the LICENSE file for
details.
