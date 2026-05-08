"""
serial_relay.py — UDP → USB Serial bridge for PPMSlave
Listens on the same UDP port as elrs_udp_server.py (5005) and forwards
raw 9-byte packets to the ESP32-C3 over USB serial.  Run one or the other,
not both at the same time.
"""

import socket
import struct
import argparse
import time
import serial


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Relay UDP control packets to ESP32 PPMSlave over serial"
    )
    parser.add_argument("--udp-host", default="0.0.0.0")
    parser.add_argument("--udp-port", type=int, default=5005)
    parser.add_argument("--serial-port", default="/dev/ttyACM0",
                        help="ESP32 USB serial device (e.g. /dev/ttyUSB0 or COM3)")
    parser.add_argument("--baud", type=int, default=921600)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.udp_host, args.udp_port))
    sock.settimeout(1.0)

    ser = serial.Serial(args.serial_port, args.baud, timeout=0.1)

    print(f"[relay] UDP {args.udp_host}:{args.udp_port}  →  {args.serial_port}@{args.baud}")
    print("[relay] Ctrl-C to stop\n")

    pkt_count = 0
    t_start = time.monotonic()

    while True:
        try:
            data, addr = sock.recvfrom(256)
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            break

        if len(data) < 9:
            print(f"[relay] Short packet ({len(data)} bytes) from {addr} — skipped")
            continue

        payload = data[:9]
        ser.write(payload)

        pkt_count += 1
        ax0, ax1 = struct.unpack_from(">ff", payload, 0)
        flag = payload[8]
        elapsed = time.monotonic() - t_start
        print(f"[relay #{pkt_count:>6}  {elapsed:7.2f}s]  {str(addr):<22}  "
              f"ax0={ax0:+.3f}  ax1={ax1:+.3f}  flag={flag}")


if __name__ == "__main__":
    main()
