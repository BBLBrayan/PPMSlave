"""
ppm_tester.py — Browser-based 8-channel PPM tester for PPMSlave

Serves a slider webpage and sends ">ffB" UDP packets to port 5005,
replacing the BlackRock pipeline during testing.

Usage:
    pip install flask          # one-time
    python ppm_tester.py
    # open http://localhost:8080 in a browser
    # run serial_relay.py separately to forward packets to the ESP32
"""

import socket
import struct
from flask import Flask, request, jsonify, render_template_string

UDP_HOST = "127.0.0.1"
UDP_PORT = 5005

app = Flask(__name__)
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ---------------------------------------------------------------------------
# Packet builder  (matches elrs_udp_server.py / data_client.py format)
# Only ch1/ch2/ch3 are wired in the current ">ffB" format.
# ch4-ch8 sliders are shown for completeness; ESP32 holds them at neutral.
# ---------------------------------------------------------------------------
def _build_packet(channels_us) -> bytes:
    axis0 = (channels_us[0] - 1500) / 500.0   # ch1 → [-1, 1]
    axis1 = (channels_us[1] - 1500) / 500.0   # ch2 → [-1, 1]
    flag  = 1 if channels_us[2] >= 1500 else 0 # ch3 → 0 or 1
    return struct.pack(">ffB", axis0, axis1, flag)


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>PPM Tester — 8 Channels</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Courier New', monospace;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-height: 100vh;
    padding: 24px 16px;
  }
  h1 { font-size: 1.4rem; color: #00d4ff; margin-bottom: 6px; letter-spacing: 2px; }
  .subtitle { font-size: 0.75rem; color: #666; margin-bottom: 24px; }

  .grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    width: 100%;
    max-width: 900px;
    margin-bottom: 20px;
  }
  @media (max-width: 600px) { .grid { grid-template-columns: repeat(2, 1fr); } }

  .channel {
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 10px;
    padding: 14px 12px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }
  .channel.active  { border-color: #00d4ff; }
  .channel.neutral { border-color: #444; opacity: 0.75; }

  .ch-label { font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }
  .ch-name  { font-size: 0.95rem; font-weight: bold; color: #fff; }
  .ch-value { font-size: 1.3rem; color: #00d4ff; font-weight: bold; }
  .ch-unit  { font-size: 0.65rem; color: #555; }

  input[type=range] {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: #0f3460;
    outline: none;
    cursor: pointer;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: #00d4ff;
    cursor: grab;
    border: 2px solid #1a1a2e;
  }
  .channel.neutral input[type=range]::-webkit-slider-thumb { background: #666; }

  .center-btn {
    background: #0f3460;
    color: #00d4ff;
    border: 1px solid #00d4ff;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 0.7rem;
    cursor: pointer;
    font-family: inherit;
  }
  .center-btn:hover { background: #00d4ff; color: #1a1a2e; }

  .panel {
    background: #16213e;
    border: 1px solid #0f3460;
    border-radius: 10px;
    padding: 16px 20px;
    width: 100%;
    max-width: 900px;
    font-size: 0.8rem;
    line-height: 1.8;
  }
  .panel-title { color: #00d4ff; font-size: 0.75rem; letter-spacing: 1px; margin-bottom: 8px; }
  .pkt-row { display: flex; gap: 24px; flex-wrap: wrap; }
  .pkt-field { display: flex; flex-direction: column; }
  .pkt-key   { color: #888; font-size: 0.65rem; }
  .pkt-val   { color: #0f9; font-size: 0.9rem; }

  .status-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #0f9;
    margin-right: 6px;
    animation: pulse 1s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  .status-err { background: #f55; animation: none; }

  .controls {
    display: flex; gap: 12px; align-items: center;
    margin-top: 14px;
  }
  .btn {
    background: #0f3460; color: #e0e0e0;
    border: 1px solid #333; border-radius: 6px;
    padding: 6px 14px; font-size: 0.78rem;
    cursor: pointer; font-family: inherit;
  }
  .btn:hover { border-color: #00d4ff; color: #00d4ff; }
  .hz-label { color: #666; font-size: 0.72rem; }
</style>
</head>
<body>
<h1>PPM TESTER</h1>
<p class="subtitle">8-channel UDP sender → port 5005 → serial_relay.py → ESP32 PPMSlave</p>

<div class="grid" id="grid"></div>

<div class="panel">
  <div class="panel-title">LAST PACKET SENT</div>
  <div class="pkt-row">
    <div class="pkt-field"><span class="pkt-key">axis0 (ch1)</span><span class="pkt-val" id="p-ax0">0.000</span></div>
    <div class="pkt-field"><span class="pkt-key">axis1 (ch2)</span><span class="pkt-val" id="p-ax1">0.000</span></div>
    <div class="pkt-field"><span class="pkt-key">flag  (ch3)</span><span class="pkt-val" id="p-flag">0</span></div>
    <div class="pkt-field"><span class="pkt-key">raw (hex)</span><span class="pkt-val" id="p-hex">—</span></div>
    <div class="pkt-field"><span class="pkt-key">status</span><span class="pkt-val" id="p-status"><span class="status-dot"></span>OK</span></div>
  </div>
  <div class="controls">
    <button class="btn" onclick="centerAll()">Center All (1500)</button>
    <button class="btn" onclick="toggleSend()" id="send-btn">⏸ Pause</button>
    <span class="hz-label" id="hz-label">20 Hz</span>
  </div>
</div>

<script>
const CH_NAMES  = ['Up/Down','Left/Right','Action','Ch 4','Ch 5','Ch 6','Ch 7','Ch 8'];
const CH_ACTIVE = [true, true, true, false, false, false, false, false];
const values    = new Array(8).fill(1500);
let sending     = true;
let intervalId  = null;
const RATE_HZ   = 100;

function buildGrid() {
  const grid = document.getElementById('grid');
  for (let i = 0; i < 8; i++) {
    const cls = CH_ACTIVE[i] ? 'active' : 'neutral';
    grid.innerHTML += `
      <div class="channel ${cls}">
        <span class="ch-label">Channel ${i+1}</span>
        <span class="ch-name">${CH_NAMES[i]}</span>
        <span class="ch-value" id="val-${i}">1500</span>
        <span class="ch-unit">µs</span>
        <input type="range" id="sl-${i}" min="1000" max="2000" step="10" value="1500"
               oninput="onSlide(${i}, this.value)">
        <button class="center-btn" onclick="center(${i})">↺ 1500</button>
      </div>`;
  }
}

function onSlide(ch, v) {
  values[ch] = parseInt(v);
  document.getElementById('val-' + ch).textContent = v;
}

function center(ch) {
  values[ch] = 1500;
  document.getElementById('sl-'  + ch).value = 1500;
  document.getElementById('val-' + ch).textContent = 1500;
}

function centerAll() { for (let i = 0; i < 8; i++) center(i); }

async function sendPacket() {
  if (!sending) return;
  try {
    const res = await fetch('/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({channels: values})
    });
    const d = await res.json();
    document.getElementById('p-ax0').textContent  = d.axis0.toFixed(4);
    document.getElementById('p-ax1').textContent  = d.axis1.toFixed(4);
    document.getElementById('p-flag').textContent = d.flag;
    document.getElementById('p-hex').textContent  = d.hex;
    document.getElementById('p-status').innerHTML =
      '<span class="status-dot"></span>OK';
  } catch(e) {
    document.getElementById('p-status').innerHTML =
      '<span class="status-dot status-err"></span>ERR: ' + e.message;
  }
}

function toggleSend() {
  sending = !sending;
  document.getElementById('send-btn').textContent = sending ? '⏸ Pause' : '▶ Resume';
}

buildGrid();
intervalId = setInterval(sendPacket, 1000 / RATE_HZ);
document.getElementById('hz-label').textContent = RATE_HZ + ' Hz';
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/send", methods=["POST"])
def send_packet():
    data = request.get_json(force=True)
    channels = data.get("channels", [1500] * 8)
    if len(channels) < 8:
        channels = list(channels) + [1500] * (8 - len(channels))

    payload = _build_packet(channels)
    _sock.sendto(payload, (UDP_HOST, UDP_PORT))

    ax0, ax1 = struct.unpack_from(">ff", payload, 0)
    flag = payload[8]
    return jsonify(
        ok=True,
        axis0=round(ax0, 4),
        axis1=round(ax1, 4),
        flag=int(flag),
        hex=payload.hex(" "),
    )


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"[tester] http://localhost:{port}  →  UDP {UDP_HOST}:{UDP_PORT}")
    print("[tester] Run serial_relay.py in a separate terminal to forward to ESP32")
    app.run(host="0.0.0.0", port=port, debug=False)
