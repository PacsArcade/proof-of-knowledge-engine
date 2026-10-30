#!/usr/bin/env python3
"""Headless-chromium CDP driver for the luanti-wasm smoke test (dev). Loads a URL, collects
console lines for N seconds of REAL time, then saves a screenshot.
Usage: cdp_shot.py <debug-port> <url> <seconds> <out.png> [steps.json]
steps.json: [{"t": 40, "shell": "cmd"}, {"t": 45, "shot": "a.png"}] run at t real seconds after load."""
import asyncio, base64, json, subprocess, sys, urllib.request
import websockets

async def main(port, url, secs, out, steps=()):
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
    page = next(t for t in tabs if t["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2**26) as ws:
        n = 0
        async def call(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            return n
        await call("Runtime.enable"); await call("Log.enable"); await call("Page.enable")
        await call("Page.navigate", url=url)
        loop = asyncio.get_running_loop(); t0 = loop.time(); end = t0 + secs
        steps = sorted(steps, key=lambda x: x["t"])
        async def shot(path):
            i = await call("Page.captureScreenshot", format="png")
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == i:
                    open(path, "wb").write(base64.b64decode(m["result"]["data"])); print("saved", path); return
                if m.get("method") == "Runtime.consoleAPICalled":
                    print("console:", " ".join(str(a.get("value", "")) for a in m["params"]["args"])[:300])
        while loop.time() < end:
            while steps and loop.time() - t0 >= steps[0]["t"]:
                st = steps.pop(0)
                if "shell" in st:
                    print("shell:", st["shell"], subprocess.run(st["shell"], shell=True, capture_output=True, text=True).stdout.strip()[:300])
                if "shot" in st:
                    await shot(st["shot"])
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 1))
            except asyncio.TimeoutError:
                continue
            if m.get("method") == "Runtime.consoleAPICalled":
                print("console:", " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"]["args"])[:300])
            elif m.get("method") == "Runtime.exceptionThrown":
                print("exception:", json.dumps(m["params"]["exceptionDetails"])[:300])
        i = await call("Page.captureScreenshot", format="png")
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == i:
                open(out, "wb").write(base64.b64decode(m["result"]["data"])); print("saved", out); break

asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4],
                 json.load(open(sys.argv[5])) if len(sys.argv) > 5 else ()))
