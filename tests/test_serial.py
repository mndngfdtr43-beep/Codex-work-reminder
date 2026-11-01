from unittest.mock import patch
from bridge.serial_link import Board
from bridge.state import State


class FakeSerial:
    def __init__(self, **kwargs):
        self.data = bytearray()
        self.sent = []
        self.is_open = False

    def open(self):
        assert not self.dtr and not self.rts
        self.is_open = True

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        self.data.clear()

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, count):
        result = self.data[:count]
        del self.data[:count]
        return result

    def write(self, data):
        self.sent.append(data)


def test_partial_noise_overflow_handshake_ack_and_replayed_button():
    with patch("serial.Serial", FakeSerial), patch("time.monotonic", return_value=10):
        board = Board("TEST")
        board.send_state(State.RUNNING, 8)
        assert board.serial.sent == [b"CAR1 HELLO\n"]
        board.serial.data += b"boot noise\n" + b"x" * 200 + b"CAR1 READY bad\nCAR1 RE"
        assert not board.poll(8)
        assert not board.ready
        board.serial.data += b"ADY abcd\n"
        assert not board.poll(8)
        assert board.ready
        board.send_state(State.RUNNING, 8.1)
        assert board.serial.sent[-1] == b"CAR1 STATE running\n"
        board.serial.data += b"CAR1 BUTTON abcd 1\n"
        assert board.poll(10)
        board.serial.data += b"CAR1 BUTTON abcd 1\nCAR1 BUTTON old 2\n"
        assert not board.poll(11)
        board.close()
        assert board.serial.sent[-1] == b"CAR1 STATE disconnected\n"


def test_held_or_buffered_startup_button_is_ignored():
    with patch("serial.Serial", FakeSerial), patch("time.monotonic", return_value=1):
        board = Board("TEST")
        board.serial.data += b"CAR1 READY a\nCAR1 BUTTON a 1\n"
        assert not board.poll(1)


def test_ack_does_not_identify_unflashed_board():
    with patch("serial.Serial", FakeSerial), patch("time.monotonic", return_value=1):
        board = Board("TEST")
        board.serial.data += b"CAR1 ACK running\n"
        board.poll(1)
        assert not board.ready
