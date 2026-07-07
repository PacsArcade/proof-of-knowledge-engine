"""webbridge.py — a minimal, zero-dependency WebSocket bridge so browsers can play POKEMUD. 💜

Browsers can't open a raw telnet socket, so we speak WebSocket (RFC 6455) and reuse the exact same
`handle_client` game loop the telnet server uses — one engine, two transports. This is stdlib only
(no `websockets` package): a small handshake + frame codec over asyncio streams, plus reader/writer
ADAPTERS shaped like `asyncio.StreamReader`/`StreamWriter` so the MUD doesn't know the difference.

Each browser text message = one input line. Each `p.send(...)` = one WS text frame (the MUD redraws
the whole screen per frame, so the browser just renders the latest frame — see webclient.html).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


async def handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    """Read the HTTP Upgrade request and complete the WebSocket handshake. True on success."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=10)
    except Exception:
        return False
    if not request_line:
        return False
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        if b":" in line:
            k, _, v = line.decode("latin1").partition(":")
            headers[k.strip().lower()] = v.strip()
    key = headers.get("sec-websocket-key")
    if not key or "websocket" not in headers.get("upgrade", "").lower():
        writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        try:
            await writer.drain()
        except Exception:
            pass
        return False
    accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
    writer.write(resp.encode())
    await writer.drain()
    return True


def _build_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    """Server->client frame (never masked)."""
    b0 = 0x80 | opcode
    n = len(payload)
    if n < 126:
        header = struct.pack("!BB", b0, n)
    elif n < 65536:
        header = struct.pack("!BBH", b0, 126, n)
    else:
        header = struct.pack("!BBQ", b0, 127, n)
    return header + payload


async def _read_frame(reader: asyncio.StreamReader):
    """Read one client->server frame → (opcode, payload). Client frames MUST be masked."""
    hdr = await reader.readexactly(2)
    b0, b1 = hdr[0], hdr[1]
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    ln = b1 & 0x7F
    if ln == 126:
        ln = struct.unpack("!H", await reader.readexactly(2))[0]
    elif ln == 127:
        ln = struct.unpack("!Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
    data = await reader.readexactly(ln) if ln else b""
    if masked and ln:
        data = bytes(data[i] ^ mask[i % 4] for i in range(ln))
    return opcode, data


class WSReader:
    """Looks enough like asyncio.StreamReader for the MUD: `readline()` returns the next browser
    message as a line; `at_eof()` signals the socket closed."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._r = reader
        self._w = writer
        self._eof = False

    def at_eof(self) -> bool:
        return self._eof

    async def readline(self) -> bytes:
        while True:
            try:
                opcode, data = await _read_frame(self._r)
            except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
                self._eof = True
                return b""
            if opcode == 0x8:                       # close
                self._eof = True
                return b""
            if opcode == 0x9:                       # ping -> pong
                try:
                    self._w.write(_build_frame(data, 0xA))
                    await self._w.drain()
                except Exception:
                    self._eof = True
                    return b""
                continue
            if opcode == 0xA:                       # pong
                continue
            if opcode in (0x0, 0x1, 0x2):           # (continuation)/text/binary = an input line
                return data + b"\n"


class WSWriter:
    """Looks enough like asyncio.StreamWriter for the MUD. Buffers writes and flushes one WS text
    frame per `drain()` — and the MUD does one write+drain per screen render, so 1 frame = 1 screen."""

    def __init__(self, writer: asyncio.StreamWriter):
        self._w = writer
        self._buf = bytearray()
        self._peer = writer.get_extra_info("peername")

    def get_extra_info(self, name: str):
        return self._peer if name == "peername" else None

    def write(self, data: bytes) -> None:
        self._buf += data

    async def drain(self) -> None:
        if self._buf:
            self._w.write(_build_frame(bytes(self._buf), 0x1))
            self._buf.clear()
        await self._w.drain()

    def close(self) -> None:
        try:
            self._w.write(_build_frame(b"", 0x8))
            self._w.close()
        except Exception:
            pass
