import struct
import unittest

from backend.voice import Audio, End, MAX_FRAME_SAMPLES, MAX_SAMPLES, ProtocolError
from backend.wire import decode_input, playback_frame


class WireTest(unittest.TestCase):
    def test_upload_position_is_in_samples_and_pcm_remains_little_endian(self):
        frame = struct.pack("!BBI", 1, 1, 320) + bytes.fromhex("3412")
        self.assertEqual(decode_input(frame), Audio(320, bytes.fromhex("3412")))

    def test_end_uses_exclusive_sample_position(self):
        self.assertEqual(decode_input('{"v":1,"type":"turn.end","samples":321}'), End(321))

    def test_rejects_malformed_audio(self):
        header = struct.pack("!BBI", 1, 1, 0)
        for frame in (
            b"", header, header + b"x", header + b"xx" * (MAX_FRAME_SAMPLES + 1),
            struct.pack("!BBI", 1, 2, 0) + b"xx",
            struct.pack("!BBI", 2, 1, 0) + b"xx",
            struct.pack("!BBI", 1, 1, MAX_SAMPLES) + b"xx",
        ):
            with self.subTest(size=len(frame)), self.assertRaises(ProtocolError):
                decode_input(frame)

    def test_rejects_invalid_end_control(self):
        for frame in (
            "null", "{", " " * 257,
            '{"v":true,"type":"turn.end","samples":1}',
            '{"v":1,"type":"turn.end","samples":true}',
            '{"v":1,"type":"turn.end","samples":0}',
            '{"v":1,"type":"turn.end","samples":1,"extra":0}',
        ):
            with self.subTest(frame=frame), self.assertRaises(ProtocolError):
                decode_input(frame)

    def test_playback_has_distinct_direction(self):
        self.assertEqual(playback_frame(320, bytes.fromhex("3412")).hex(), "0102000001403412")
