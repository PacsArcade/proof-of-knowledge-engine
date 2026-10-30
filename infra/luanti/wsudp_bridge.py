#!/usr/bin/env python3
"""wsudp_bridge.py - minimal WebSocket to UDP bridge for luanti-wasm (dev, offline).

The luanti-wasm browser client (paradust7/luanti-wasm, MIT) speaks a small proxy protocol over
a WebSocket (see webshims src/emsocket/proxy.js, MIT):
    text  NEWADDR                      -> ADDR <virtual-ip> <passcode> <joincode>
    text  BIND <passcode> UDP <port>   -> BIND OK, then binary frames both ways
    frame = 24 byte header (magic 0x778B4CF6, 16 byte IPv6 peer, u16 port, u16 len) + payload
The upstream server "lwproxy" (MIT) only routes between browsers and to an allowlist of TCP hosts,
so it cannot reach a normal dedicated Luanti server. This bridge does that one job: it forwards
the client's datagrams as real UDP to an allowlisted host:port (the local Luanti server) and wraps
the replies. Nothing else: no TCP PROXY, no other destinations.

Usage: wsudp_bridge.py --listen 127.0.0.1:5214 --map fd00::7=127.0.0.1:30000
"""
import argparse, asyncio, ipaddress, secrets, struct, sys
import websockets

MAGIC = 0x778B4CF6
HDR = struct.Struct(">I16sHH")
ALLOW: set = set()
# The browser client only sends to addresses on the proxy's private fd00::/16 network (packets
# to any other address go "nowhere" inside the wasm socket layer). So each real server is
# published under a virtual fd00:: address: --map fd00::7=127.0.0.1:30000.
VMAP: dict = {}      # (virtual ip, port) -> (real ip, port)
RMAP: dict = {}      # (real ip, port) -> (virtual ip, port)
PASSCODES: dict = {}


def to_v6(ip: str) -> bytes:
    a = ipaddress.ip_address(ip)
    if a.version == 4:
        a = ipaddress.IPv6Address("::ffff:" + ip)
    return a.packed


def from_v6(b: bytes) -> str:
    a = ipaddress.IPv6Address(b)
    return str(a.ipv4_mapped) if a.ipv4_mapped else str(a)


class Relay(asyncio.DatagramProtocol):
    def __init__(self, ws):
        self.ws = ws

    def datagram_received(self, data, addr):
        if not getattr(self, "logged", False):
            self.logged = True
            print("first reply from", addr, len(data), "bytes", flush=True)
        vaddr = RMAP.get((addr[0], addr[1]), addr)
        frame = HDR.pack(MAGIC, to_v6(vaddr[0]), vaddr[1], len(data)) + data
        asyncio.ensure_future(self.ws.send(frame))


async def handler(ws):
    bound = None
    seen = {}
    transport = None
    try:
        async for msg in ws:
            if isinstance(msg, str):
                parts = msg.split()
                if msg.startswith("PING"):
                    await ws.send("PONG" + msg[4:])
                elif parts[:1] == ["NEWADDR"]:
                    addr = "fd00::%x:%x:%x:%x" % tuple(secrets.randbits(16) for _ in range(4))
                    pw = secrets.token_urlsafe(12).replace("-", "A").replace("_", "B")[:16]
                    PASSCODES[pw] = addr
                    print("NEWADDR ->", addr, flush=True)
                    await ws.send("ADDR %s %s %s" % (addr, pw, secrets.token_hex(4).upper()))
                elif parts[:1] == ["BIND"] and len(parts) == 4 and parts[1] in PASSCODES and parts[2] == "UDP":
                    loop = asyncio.get_running_loop()
                    transport, _ = await loop.create_datagram_endpoint(lambda: Relay(ws), family=2)
                    bound = True
                    print("BIND OK", parts[3], flush=True)
                    await ws.send("BIND OK")
                elif parts[:1] == ["BIND"]:
                    await ws.send("BIND FAILED")
                else:
                    print("refused command:", parts[:1], file=sys.stderr)
                    await ws.close()
                    return
            else:
                if not bound or len(msg) < HDR.size:
                    continue
                magic, ip6, port, n = HDR.unpack_from(msg)
                if magic != MAGIC or len(msg) != HDR.size + n:
                    continue
                dest = (from_v6(ip6), port)
                dest = VMAP.get(dest)
                if dest is None:
                    print("blocked destination", from_v6(ip6), port, flush=True)
                    continue
                if not seen.get(dest):
                    seen[dest] = True
                    print("first datagram to", dest, n, "bytes", flush=True)
                transport.sendto(bytes(msg[HDR.size:]), dest)
    except websockets.ConnectionClosed:
        pass
    finally:
        if transport:
            transport.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:5214")
    ap.add_argument("--map", action="append", required=True,
                    help="virtual=real, e.g. fd00::7=127.0.0.1:30000 (virtual port = real port)")
    a = ap.parse_args()
    for m in a.map:
        v, real = m.split("=")
        rip, rport = real.rsplit(":", 1)
        VMAP[(v, int(rport))] = (rip, int(rport))
        RMAP[(rip, int(rport))] = (v, int(rport))
    host, port = a.listen.rsplit(":", 1)
    async with websockets.serve(handler, host, int(port), max_size=2 ** 16):
        print("wsudp_bridge listening", a.listen, "map", sorted(VMAP.items()), flush=True)
        await asyncio.Future()


asyncio.run(main())
