#!/usr/bin/env python3
"""Serve the built luanti-wasm www/ tree with the two headers browsers require for
SharedArrayBuffer (COOP same-origin, COEP require-corp). Dev only, loopback by default.
Usage: serve_www.py <www-dir> [port] [bind]"""
import functools, http.server, sys

class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".wasm": "application/wasm", ".js": "text/javascript", ".pack": "application/octet-stream"}
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

d = sys.argv[1]; port = int(sys.argv[2]) if len(sys.argv) > 2 else 5213
bind = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
http.server.ThreadingHTTPServer((bind, port), functools.partial(H, directory=d)).serve_forever()
