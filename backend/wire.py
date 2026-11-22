"""Version 1 frames for a connection dedicated to a single voice turn."""

import json
import struct

from backend.voice import Audio, End, MAX_FRAME_SAMPLES, MAX_SAMPLES, ProtocolError

VERSION = 1
UPLOAD = 1
PLAYBACK = 2
HEADER = struct.Struct("!BBI")
MAX_CONTROL_BYTES = 256


def decode_input(message: str | bytes) -> Audio | End:
    if isinstance(message, str):
        if len(message.encode("utf-8")) > MAX_CONTROL_BYTES:
            raise ProtocolError("oversized control")
        try:
            control = json.loads(message)
        except (ValueError, RecursionError):
            raise ProtocolError("invalid control") from None
        if (
            not isinstance(control, dict)
            or set(control) != {"v", "type", "samples"}
            or type(control["v"]) is not int
            or control["v"] != VERSION
            or control["type"] != "turn.end"
            or type(control["samples"]) is not int
            or not 1 <= control["samples"] <= MAX_SAMPLES
        ):
            raise ProtocolError("invalid turn end")
        return End(control["samples"])

    payload_size = len(message) - HEADER.size
    if not 2 <= payload_size <= MAX_FRAME_SAMPLES * 2 or payload_size % 2:
        raise ProtocolError("invalid upload size")
    version, direction, position = HEADER.unpack_from(message)
    if version != VERSION or direction != UPLOAD or position + payload_size // 2 > MAX_SAMPLES:
        raise ProtocolError("invalid upload header")
    return Audio(position, message[HEADER.size:])


def playback_frame(position: int, pcm: bytes) -> bytes:
    """Encode an output frame with its segment-relative sample position."""
    if not 0 <= position <= 0xFFFFFFFF or not pcm or len(pcm) % 2:
        raise ProtocolError("invalid playback frame")
    return HEADER.pack(VERSION, PLAYBACK, position) + pcm
