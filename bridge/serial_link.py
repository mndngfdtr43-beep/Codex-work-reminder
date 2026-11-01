"""Bounded ASCII protocol over USB UART. Opening the port keeps DTR/RTS low."""
import time
from .state import ButtonGate, State

MAX_LINE = 96


def candidate_ports():
    from serial.tools import list_ports
    return [p for p in list_ports.comports() if p.vid in {0x1A86, 0x10C4, 0x303A}]


class Board:
    def __init__(self, port):
        import serial
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0, write_timeout=0.5)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.serial.reset_input_buffer()
        self.gate = ButtonGate()
        self.buffer = bytearray()
        self.overflow = False
        self.last_ack = 0.0
        self.last_hello = -10.0
        self.last_tx = -10.0
        self.ready_at = None
        self.started_at = time.monotonic()

    @property
    def ready(self):
        return self.gate.boot is not None and time.monotonic() - self.last_ack < 3.0

    def write(self, text):
        self.serial.write((text + "\n").encode("ascii"))

    def send_state(self, state: State, now: float, force=False):
        if now - self.last_hello > 1.0 and not self.ready:
            self.write("CAR1 HELLO")
            self.last_hello = now
        if self.gate.boot is not None and (force or now - self.last_tx > 0.5):
            self.write("CAR1 STATE " + state.value)
            self.last_tx = now

    def poll(self, now: float) -> bool:
        pressed = False
        for byte in self.serial.read(min(self.serial.in_waiting, 4096)):
            if byte == 10:
                if not self.overflow:
                    parts = self.buffer.decode("ascii", errors="replace").strip().split()
                    if len(parts) == 3 and parts[:2] == ["CAR1", "READY"]:
                        if self.gate.boot != parts[2]:
                            self.ready_at = now
                        self.gate.ready(parts[2])
                        self.last_ack = now
                    elif len(parts) == 3 and parts[:2] == ["CAR1", "ACK"]:
                        if parts[2] in {s.value for s in State}:
                            self.last_ack = now
                    elif len(parts) == 4 and parts[:2] == ["CAR1", "BUTTON"]:
                        try:
                            accepted = self.gate.accept(parts[2], int(parts[3]), now)
                            pressed |= accepted and self.ready and self.ready_at is not None and now - self.ready_at > 1.0
                        except ValueError:
                            pass
                self.buffer.clear()
                self.overflow = False
            elif len(self.buffer) < MAX_LINE and not self.overflow:
                self.buffer.append(byte)
            else:
                self.overflow = True
        return pressed

    def close(self):
        try:
            if self.serial.is_open and self.gate.boot:
                self.write("CAR1 STATE disconnected")
        finally:
            self.serial.close()
