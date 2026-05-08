#!/bin/bash
set -e

echo "=== PPMSlave install ==="

# System packages
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv ufw

# Python dependencies
pip3 install --user pyserial flask

# Serial port access (dialout group)
if ! groups "$USER" | grep -q dialout; then
    sudo usermod -aG dialout "$USER"
    echo "[!] Added $USER to dialout group — log out and back in for serial access to take effect"
fi

# Open UDP port 5005 for incoming control packets (needed for Tailscale deployment)
sudo ufw allow 5005/udp > /dev/null 2>&1 || true

echo ""
echo "=== Done ==="
echo ""
echo "Run:"
echo "  python3 serial_relay.py --serial-port /dev/ttyACM0"
echo "  python3 ppm_tester.py   (test only — open http://localhost:8080)"
echo ""
echo "ESP32 flashing: open PPMSlave.ino in Arduino IDE"
echo "  Board: ESP32C3 Dev Module"
echo "  USB CDC On Boot: Enabled"
echo "  Baud: 921600"
