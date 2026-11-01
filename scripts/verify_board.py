"""Check real firmware replies; this does not claim LEDs were visually checked."""
import argparse
from collections import deque
import time
import serial

STATES = ("running", "paused", "idle", "waiting", "error", "unknown", "pending", "disconnected")


def verify(port, button_seconds=0, expected_pin=None, expected_count=None):
    device = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
    device.dtr = False
    device.rts = False
    device.port = port
    device.open()
    recent = deque(maxlen=6)
    try:
        device.reset_input_buffer()
        deadline, next_ping, boot = time.monotonic() + 8, 0.0, None
        info = None
        while time.monotonic() < deadline:
            if time.monotonic() >= next_ping:
                device.write(b"CAR1 HELLO\n")
                next_ping = time.monotonic() + 0.5
            line = device.readline().decode("ascii", "replace").strip()
            if line:
                recent.append(line)
            if line.startswith("CAR1 READY "):
                boot = line.split()[-1]
            if line.startswith("CAR1 INFO "):
                info = dict(part.split("=", 1) for part in line.split()[2:] if "=" in part)
            if boot and (info is not None or (expected_pin is None and expected_count is None)):
                break
        if boot is None:
            raise RuntimeError("No CAR1 handshake. Recent serial messages: " + repr(list(recent)))
        print("PASS: firmware handshake", flush=True)
        if expected_pin is not None and (info or {}).get("led_pin") != str(expected_pin):
            raise RuntimeError("Firmware LED GPIO does not match selected build target")
        if expected_count is not None and (info or {}).get("led_count") != str(expected_count):
            raise RuntimeError("Firmware LED count does not match selected build target")
        if info:
            print("PASS: LED configuration " + repr(info), flush=True)
        for state in STATES:
            device.write(("CAR1 STATE " + state + "\n").encode())
            deadline = time.monotonic() + 1.5
            matched = False
            while time.monotonic() < deadline:
                if device.readline().decode("ascii", "replace").strip() == "CAR1 ACK " + state:
                    matched = True
                    break
            if not matched:
                raise RuntimeError("No ACK for " + state)
            print("PASS: state ACK " + state, flush=True)
            time.sleep(0.25)
        if button_seconds:
            print(f"Press and release BOOT within {button_seconds} seconds (no Codex control).", flush=True)
            deadline, next_ping = time.monotonic() + button_seconds, 0.0
            while time.monotonic() < deadline:
                if time.monotonic() >= next_ping:
                    device.write(b"CAR1 STATE idle\n")
                    next_ping = time.monotonic() + 0.5
                parts = device.readline().decode("ascii", "replace").strip().split()
                if len(parts) == 4 and parts[:3] == ["CAR1", "BUTTON", boot] and parts[3].isdigit():
                    print("PASS: physical BOOT event", flush=True)
                    return
            raise RuntimeError("No BOOT event observed in the test window; button test not passed.")
    finally:
        try:
            device.write(b"CAR1 STATE disconnected\n")
        finally:
            device.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--button-seconds", type=int, choices=range(0, 61), metavar="0..60", default=0)
    parser.add_argument("--expect-led-pin", type=int)
    parser.add_argument("--expect-led-count", type=int)
    args = parser.parse_args()
    verify(args.port, args.button_seconds, args.expect_led_pin, args.expect_led_count)
