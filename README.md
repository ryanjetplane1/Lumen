# Lumen Mini

Lumen Mini is a pocket sized system monitor powered by USB-C that sits on your desk for extra functionality. Built on the ESP32, it houses a 1.3" OLED display showing CPU load, RAM usage, and whatever is playing. Complete with a prebuilt progress bar and a synth GUI the hardware can be reprogramed to fit your needs. When you reach for the volume, a rotary encoder handles it along with play, pause, and skip. When you turn off your PC, Lumen Mini fades to a simple clock.

---

## Features

- Live CPU % and RAM usage
- Now-playing track name, progress bar, and position timer
- Animated synth visualizer that fades out smoothly on pause
- Clock (12-hour) when nothing is playing
- Volume control via rotary encoder with live % overlay
- Single / double / triple click for pause, next, previous track
- WiFi NTP clock fallback when PC is disconnected

---

## Hardware Required

| Part | Notes |
|---|---|
| ESP32-C3 SuperMini | Any vendor; black PCB version |
| 1.3" SH1106 OLED (128×64) | I2C, 4-pin — **not** the 0.96" SSD1306 |
| Rotary encoder with pushbutton | EC11 or equivalent |
| Breadboard + jumper wires | Or solder directly |

---

## Wiring

All logic runs at **3.3V**. Do **not** use 5V — the ESP32-C3 SuperMini I/O is not 5V tolerant.

### OLED Display (I2C)

| OLED Pin | ESP32-C3 SuperMini Pin |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SDA | GPIO8 |
| SCL | GPIO9 |

### Rotary Encoder

| Encoder Pin | ESP32-C3 SuperMini Pin | Notes |
|---|---|---|
| VCC (+) | 3.3V | |
| GND | GND | |
| CLK (A) | **GPIO10** | Hardware interrupt pin |
| DT (B) | **GPIO2** | Hardware interrupt pin |
| SW (button) | **GPIO3** | |

GPIO10 and GPIO2 are used for the encoder CLK and DT lines because they are reliable hardware interrupt-capable pins on the ESP32-C3 that are free from boot-strapping conflicts. GPIO9 is the BOOT button pin — avoid it for encoder use. GPIO8 is a strapping pin tied to the onboard LED — avoid pulling it low on boot.

---

## Software Setup

### PC Side (Python)

**Requirements:** Windows 10/11, Python 3.10+

Install dependencies:
```
pip install psutil pyserial keyboard pycaw comtypes winrt-runtime
```

Edit `main.py` and set your COM port:
```python
COM_PORT = 'COM3'
```

Run:
```
python main.py
```

> The script must be running for the display to show PC stats. It will also control media keys via the encoder.

### ESP32 Side (Arduino)

**Arduino IDE board setup:**
1. In Arduino IDE, go to **File → Preferences**
2. Add to Additional Boards Manager URLs:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. Go to **Tools → Board → Boards Manager**, search `esp32` by Espressif and install
4. Select board: **Tools → Board → esp32 → ESP32C3 Dev Module**
5. Set **USB CDC On Boot: Enabled** (required for Serial over USB-C)

**Install libraries** via Library Manager:
- `Adafruit SH110X`
- `Adafruit GFX Library`

Edit the sketch and set your WiFi credentials:
```cpp
const char* ssid     = "your-network";
const char* password = "your-password";
```

Set your timezone offset in seconds from UTC:
```cpp
const long gmtOffset_sec = -18000;  // UTC-5 (Eastern Standard Time)
const int  daylightOffset_sec = 3600;  // 1 hour DST
```

Upload the sketch via USB-C.

---

## How It Works

```
[Windows PC]
  Python script reads:
    - CPU / RAM via psutil
    - Media info via Windows Media Transport Controls (winrt)
    - System volume via pycaw
  Sends a pipe-delimited packet over USB serial ~20x per second

[ESP32-C3 SuperMini]
  Receives packet, parses fields
  Encoder interrupts → sends CW / CCW / PAUSE / NEXT / PREV back to PC
  Python receives those and fires media/volume keyboard shortcuts
  Display renders based on current state
```

---

## Display Modes

| Condition | Display Shows |
|---|---|
| No PC connection | WiFi NTP clock + date |
| PC connected, music playing | Song name, progress bar, synth visualizer |
| PC connected, music paused | Visualizer fades out → clock (12h) |
| Volume changed | Volume % overlay + bar for 1.5s |

---

## Troubleshooting

**Display shows nothing after upload**
Confirm SDA/SCL are on GPIO8/GPIO9. Confirm the display is SH1106 and not SSD1306 (different driver).

**Serial not connecting / wrong COM port**
Check Device Manager on Windows. Make sure no other program (Arduino IDE Serial Monitor, etc.) has the port open.

**Volume reads off by 1**
Make sure you are running the latest `main.py` — an earlier version used `int()` instead of `round()` for volume scalar conversion.

**Encoder feels jittery or skips**
Add a 100nF ceramic capacitor between CLK and GND, and between DT and GND, right at the encoder pins. This filters electrical noise on the interrupt lines.

**WiFi clock shows wrong time**
Adjust `gmtOffset_sec` for your timezone. EST = -18000, CST = -21600, MST = -25200, PST = -28800. If DST is active add 3600.
