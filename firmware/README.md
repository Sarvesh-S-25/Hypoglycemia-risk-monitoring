# Firmware

Both nodes are PlatformIO projects (Arduino framework, `esp32dev`). Wire formats
are in `docs/API_CONTRACT.md` section 2; the UUIDs must match `backend/app/config.py`.

| Folder | Node | Board on the bench |
|---|---|---|
| `ecg-node/` | Primary ECG node: AD8232 + ADS1115 + MPU6500, BLE service `a000`, plus a USB serial stream | 30-pin ESP32 DevKit, `/dev/ttyACM0` |
| `foot-module/` | Foot-check module: two thermistors, BLE service `b000`, deep sleep between host check-ins | ESP32 DevKit with a CP210x bridge, `/dev/ttyUSB0` |

## Build and flash

```bash
cd firmware/ecg-node    && pio run -t upload --upload-port /dev/ttyACM0
cd firmware/foot-module && pio run -t upload --upload-port /dev/ttyUSB0
```

Stop the backend first if it is using the serial source, because only one program
can hold a port. The foot module's `platformio.ini` sets `upload_speed = 115200`;
its CP210x bridge drops out at the default 460800.

## Wiring

**ECG node.** I2C on SDA 21 / SCL 22 at 3V3: MPU6500 at `0x68`, ADS1115 at `0x48`
(ADDR to GND). AD8232 OUTPUT to ADS1115 A0, LO+ to GPIO32, LO− to GPIO33, powered
from 3V3, never 5 V. The on-board LED (GPIO2) stands in for the vibration motor.

**Foot module.** Each side is GPIO32 → 1 kΩ → ADC pin → NTC → GND, with GPIO34 for
the left side and GPIO35 for the right. The thermistors are 100 Ω NTCs (marked
`101`), hence the 1 kΩ resistors. GPIO32 powers the dividers only while reading and
is held low in deep sleep. If the dividers are wired to 3V3 instead, they draw
about 6 mA all the time. The BOOT button (GPIO0) wakes the module for an immediate
check.

## Safety

When electrodes are on a person, run the laptop on battery with the charger
unplugged (`docs/POLICIES.md` P10).
