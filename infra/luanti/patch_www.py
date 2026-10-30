#!/usr/bin/env python3
"""Point a fresh luanti-wasm www/index.html at the local bridge and add the dev harness hooks.
Usage: patch_www.py <www-dir>. Edits: (1) PROXIES = the local wsudp bridge, (2) ?autolaunch=1
clicks Launch when ready, (3) Luanti stdout is mirrored to console.log (for headless runs)."""
import sys
p = sys.argv[1].rstrip("/") + "/index.html"
s = open(p).read()
a = s.index("const PROXIES = ["); b = s.index("];", a) + 2
s = s[:a] + 'const PROXIES = [\n          [ "ws://127.0.0.1:5214", "This ship (local bridge)" ],\n      ];' + s[b:]
marker = "      // Someone who followed an invite link is only told"
s = s.replace(marker, "      // PA dev harness: ?autolaunch=1 clicks Launch as soon as the launcher is ready.\n      if (new URLSearchParams(location.search).has('autolaunch')) { const _e = enableLaunchForm; enableLaunchForm = function() { _e(); setTimeout(() => document.getElementById('launch').click(), 300); }; }\n\n" + marker, 1)
s = s.replace('          mtl.onprint = (text) => {\n              tcon_print("", text);', '          mtl.onprint = (text) => {\n              console.log("LUANTI: " + text);\n              tcon_print("", text);', 1)
open(p, "w").write(s)
