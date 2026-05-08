# PPMSlave

ESP32-C3 Mini firmware and host scripts that bridge the **BlackRock** BattleBots UDP
control stream to an EdgeTX radio via a CPPM signal on the DSC trainer port.
BlackRock drives the robot's game logic and operator overlay; PPMSlave translates
its UDP output into radio stick inputs so the robot can be driven over a standard
RC link without modifying the BlackRock codebase.

---

## Pipeline

```
┌─────────────────────────────────────┐   Machine A (operator)
│  Caltech overlay  (Pygame)          │
│    └─ cb_van/transmission/          │
│         data_client.py              │
│         packs ">ffB", UDP → 5005    │
└─────────────────┬───────────────────┘
                  │  UDP  (localhost or Tailscale)
                  ▼
┌─────────────────────────────────────┐   Machine B (robot)
│  serial_relay.py                    │
│  listens UDP :5005                  │
│  writes 9 raw bytes to serial       │
└─────────────────┬───────────────────┘
                  │  USB serial  921600 baud
                  ▼
┌─────────────────────────────────────┐
│  PPMSlave.ino  (ESP32-C3 Mini)      │
│  decodes packet, drives CPPM        │
│  on GPIO 4  @ 11 ms frame           │
└─────────────────┬───────────────────┘
                  │  3.5mm DSC jack  (CPPM)
                  ▼
         EdgeTX radio  (Master/Jack)
                  │  DSMX 1F  11 ms
                  ▼
         Spektrum AR620 receiver
                  │
                  ▼
         Robot ESCs / servos
```

---

## BlackRock Interface

PPMSlave consumes the same UDP packet that `cb_van/transmission/data_client.py`
already produces. **BlackRock is never modified.**

### Packet format
```
9 bytes, big-endian:  struct.pack(">ffB", axis0, axis1, flag)

  axis0 : float32  [-1.0, 1.0]   forward / reverse
  axis1 : float32  [-1.0, 1.0]   left / right
  flag  : uint8    0 or 1        action / weapon button
```

### Channel mapping
| PPM Channel | Source  | Range (µs)      |
|-------------|---------|-----------------|
| ch1         | axis0   | 1000 – 2000     |
| ch2         | axis1   | 1000 – 2000     |
| ch3         | flag    | 1000 (off) / 1750 (on) |
| ch4         | neutral | 1500            |

Conversion: `ppm_us = 1500 + axis × 500`

---

## Hardware

### ESP32-C3 Mini wiring
```
ESP32-C3 GPIO4 ─────────────── 3.5mm Tip    (CPPM signal)
ESP32-C3 GND   ──┬──────────── 3.5mm Sleeve (GND)
                 └── 10 kΩ ─── 3.5mm Ring   (pulled low — activates DSC slave detect)
```

### EdgeTX radio setup
| Setting | Value |
|---------|-------|
| Model Setup → Trainer | **Master / Jack** |
| Per-channel mode (ch1–ch3) | `=` (replace), weight 100 |
| Internal RF protocol | **DSMX** |
| Sub-type | **1F** (11 ms, ≤ 7 channels) |

### Receiver
Spektrum AR620 — 6-channel, DSMX/DSM2, 11 ms update rate in DSMX 1F mode.

---

## Files

| File | Machine | Purpose |
|------|---------|---------|
| `PPMSlave.ino` | Robot (ESP32) | Reads serial packets, generates 4-ch CPPM on GPIO 4 |
| `serial_relay.py` | Robot | Receives UDP on :5005, writes raw bytes to ESP32 serial |
| `ppm_tester.py` | Operator | Browser slider page — tests the PPM chain without BlackRock |
| `goals.md` | — | Architecture notes, packet spec, wiring, latency analysis |

---

## Running

### 1 — Flash the ESP32
Open `PPMSlave.ino` in Arduino IDE.
- Board: **ESP32C3 Dev Module**
- USB CDC On Boot: **Enabled**
- Flash, then open Serial Monitor at **921600** baud to verify output.

### 2 — Start the relay (Machine B / robot)
```bash
pip install pyserial
python serial_relay.py --serial-port /dev/ttyACM0   # adjust port as needed
```

### 3 — Start BlackRock (Machine A / operator)
```bash
cd BlackRock/battlebots-main
python cb_van/caltech_controller.py
```

`data_client.py` sends UDP packets to port 5005. By default this is localhost;
for a two-machine Tailscale setup change `output_ip` in `data_client.py` to
Machine B's Tailscale IP.

---

## Testing Without BlackRock

`ppm_tester.py` is a standalone Flask app with 8 browser sliders that sends
the same `">ffB"` UDP packets as BlackRock.

```bash
pip install flask
python ppm_tester.py          # open http://localhost:8080
```

Move the Ch1/Ch2 sliders — the ESP32 serial monitor should show `ax0`/`ax1`
changing and EdgeTX channel monitor should track them live.

---

## Tailscale Deployment

For two-machine use (operator laptop + robot Pi):

**Machine B (robot)** — no changes needed, `serial_relay.py` already binds `0.0.0.0:5005`.
```bash
python serial_relay.py --serial-port /dev/ttyACM0
```

**Machine A (operator)** — point BlackRock at Machine B's Tailscale IP:
```python
# BlackRock/battlebots-main/cb_van/transmission/data_client.py  line 113
output_ip = "100.x.y.z",   # Machine B Tailscale IP
```

Ensure port 5005 UDP is allowed through Machine B's firewall:
```bash
sudo ufw allow 5005/udp
```

---

## Latency Budget

| Stage | Time |
|-------|------|
| UDP send rate (BlackRock) | ~10 ms |
| Serial tx @ 921600 baud (9 bytes) | ~0.1 ms |
| PPM frame | 11 ms |
| DSMX 1F RF hop | 11 ms |
| **Worst case total** | **~32 ms** |
| **Average** | **~16 ms** |
