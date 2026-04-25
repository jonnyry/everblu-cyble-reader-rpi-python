# EverBlu Cyble Water Meter Reader

Python implementation for reading an **Itron EverBlu Cyble Enhanced V2.1** water
meter over 433 MHz using a **Raspberry Pi 5** and a **CC1101** SPI
transceiver. Ports the field-tested C project
[`neutrinus/everblu-meters`](https://github.com/neutrinus/everblu-meters) to
native Python 3 and adds a wiring/health diagnostic suite.

> The meter uses the proprietary **Radian** protocol (2-FSK on 433.82 MHz). It
> only wakes to listen on **weekdays, typically 06:00–18:00**. Outside the
> window the meter will not respond — this is expected, not a bug.

## Hardware

### Water meter

![Water meter with an Itron EverBlu Cyble RF unit attached](images/water-meter.jpg)

*Yes, my meter is dirty!*

### Raspberry Pi & CC1101 module

![CC1101 RF module connected to a Raspberry Pi 5](images/rpi-cc1101.jpg)

### CC1101 module

![CC1101 RF module close up](images/cc1101.jpg)

### Wiring (Pi header pin → CC1101 pin):

| Pi header | BCM       | CC1101 pin |
| --------- | --------- | ---------- |
| Pin 17    | 3V3       | VCC        |
| Pin 20    | GND       | GND        |
| Pin 11    | GPIO17    | GDO0       |
| Pin 13    | GPIO27    | GDO2       |
| Pin 19    | MOSI      | MOSI       |
| Pin 21    | MISO      | MISO       |
| Pin 23    | SCLK      | SCK        |
| Pin 24    | CE0       | CSN        |

Enable SPI on the Pi: `sudo raspi-config` → *Interface Options* → *SPI* → enable. Reboot.

## Install

Run the following to setup your python environment, and grant access to SPI and GPIO:

```bash
./install.sh
```
`install.sh` does the following:
1. Enables SPI via raspi-config.
2. Install system packages via apt
3. Grant current user access to SPI and GPIO
4. Create a Python virtual environment
5. Install Python packages.

**You must log out and back in (or reboot) for the spi/gpio group membership to take effect.**

## Diagnostics (run this first)

Verify the board is wired correctly and the CC1101 is alive **before**
trying to talk to the meter:

```bash
./run.sh diag
```

Example output:

```
[PASS] CC1101 PARTNUM/VERSION: PARTNUM=0x00 VERSION=0x14
[PASS] PATABLE write/read-back: wrote=['0x11', '0x22', '0x33', '0x44', '0x55', '0x66', '0x77', '0x88'] read=['0x11', '0x22', '0x33', '0x44', '0x55', '0x66', '0x77', '0x88']
[PASS] Strobe & state transitions: IDLE=0x01 RX=0x0D IDLE2=0x01
[PASS] Frequency register programming: wrote 433820000 Hz, read back 433819855 Hz (err 145 Hz)
[PASS] GDO0/GDO2 wiring: GDO0(pin17): low=0 high=1; GDO2(pin27): low=0 high=1
[PASS] XOSC/192 clock on GDO0: 2690 edges in 10.0 ms (observed ~134.5 kHz, true 135.4 kHz; polling can undersample)
[PASS] RX noise floor (RSSI): min=-131.5 avg=-102.3 max=-99.0 dBm over 50 samples
[PASS] Config register dump: 47 registers: 0D 2E 06 47 55 00 FF 00 00 00 00 08 00 10 AF 75 F6 83 02 00 00 15 07 00 18 1D 1C C7 00 B2 87 6B FB B6 10 E9 2A 00 1F 41 00 59 7F 3F 81 35 09
```

## Reading the meter

To read the meter, provide the first two components of serial number of RF unit (eg `15-0202517-123`) to the `--year` and `--serial` parameters as follows:

```bash
./run.sh read_meter --year 15 --serial 202517 --json
```

Example output:

```json
{
  "meter_id": "55SF123456",
  "timestamp": "2026-04-24T09:49:23.587257+0100",
  "liters": 1996330,
  "reads_counter": 44,
  "battery_months": 9,
  "window_start_hour": 6,
  "window_end_hour": 18
}
```

**Please note: the timestamp is taken from the Raspberry Pi and is NOT returned in the meter payload.**

#### Arguments:

| Option                   | Description                                                                 |
|--------------------------|-----------------------------------------------------------------------------|
| `--year`                 | First segment of the label serial (`15-0202517-123` → `15`)                 |
| `--serial`               | Middle segment of the label serial with leading zeros stripped (e.g. `15-0202517-123` → `0202517`). |
| `--freq-offset-hz`       | Frequency trim (Hz) added to 433.82 MHz; only needed if not using default -15000 calibration. |
| `--retries 3`            | Retry count; the meter may miss the first wake-up                           |
| `--retry-delay 5`        | Seconds between retries                                                     |
| `--json`                 | Machine-readable output                                                     |
| `--raw`                  | Include the raw hex frame                                                   |
| `--verbose`              | Include debug frames (request payload, RX phase info)                       |
| `--additional-readings`  | Include the list of additional readings (unspecified/unclear purpose)       |

### Finding the right frequency offset (first time on a new CC1101)

CC1101 modules ship with crystals that drift a few kHz from nominal; the
meter's narrow RX filter will drop the request unless you trim for it. On
this installation the sweep picked up the meter at `-20 kHz` first try, with
a reliable band from `-30 kHz` to `-10 kHz`; `-15 kHz` is now the default.

To recalibrate for a different module:

```bash
# 1. Coarse sweep (±80 kHz in 20 kHz steps):
./run.sh freq_scan --year 15 --serial 202517 --start-hz -80000 --stop-hz 80000 --step-hz 20000

# 2. Narrow in on the hit with a finer step:
./run.sh freq_scan --year 15 --serial 202517 --start-hz -30000 --stop-hz -10000 --step-hz 2500
```

Pick the midpoint of the reliable band and either pass it as
`--freq-offset-hz <value>` to `read_meter.py` or update the `freq_offset_hz`
default in `everblu/config.py`.

## Package layout

```
everblu/
    config.py            Meter / radio / GPIO configuration dataclasses
    cc1101_regs.py       CC1101 register & strobe constants, default config table
    cc1101.py            Thin spidev-based CC1101 driver
    gpio.py              lgpio-based GPIO wrapper (Pi 5 compatible)
    radian.py            Pure-Python Radian protocol (CRC, encode, decode, parse)
    reader.py            Wake-up + request + 2-stage RX orchestration
    diagnostics.py       Wiring / chip health checks
scripts/
    diag.py              CLI: run diagnostics
    read_meter.py        CLI: read the meter
    freq_scan.py         CLI: sweep frequency to find the crystal calibration
tests/
    test_radian.py       CRC, encode/decode and frame construction tests
    test_cc1101.py       Driver tests against an in-memory SPI mock
```

## Testing

Hardware-independent unit tests:

```bash
./run.sh unit_test
```

## Protocol notes

See comments in `everblu/radian.py` for the encoding details. Summary:

- TX: ~2 s wake-up (`0x55` bytes at 2.4 kbps, no preamble/sync), followed
  by a 39-byte frame = 9-byte fixed sync pattern + 19-byte CRC-Kermit-protected
  payload carrying the meter year + 24-bit serial. The 19-byte payload is
  async-serial encoded: each byte prepended with a 0 start bit, followed by
  three 1 stop bits, transmitted LSB-first.
- RX: two-stage sync capture. First SYNC `0x5550` at 2.4 kbps to grab the
  short ACK; then re-sync on `0xFFF0` at 9.59 kbps for the long index frame
  with `PKTCTRL0=0x02` (infinite length).
- Decode: the CC1101 captures at 4× the symbol rate, so `decode_4bitpbit`
  collapses 4-sample runs and strips the start/stop framing, yielding the
  raw payload bytes. Litres are a 32-bit little-endian integer at offset 18;
  see `parse_meter_report` for other documented fields.

## Credits

Derived from [`neutrinus/everblu-meters`](https://github.com/neutrinus/everblu-meters)
(C/wiringPi) and the
[`psykokwak-com/everblu-meters-esp8266`](https://github.com/psykokwak-com/everblu-meters-esp8266)
fork, which in turn reverse-engineered the Radian protocol from
<http://www.lamaisonsimon.fr/wiki/doku.php?id=maison2:compteur_d_eau:compteur_d_eau>.

## License

The license is unknown, citing one of the authors:

> I didn't put a license on this code maybe I should, I didn't know much about it in terms of licensing. this code was made by "looking" at the radian protocol which is said to be open source earlier in the page, I don't know if that helps?
