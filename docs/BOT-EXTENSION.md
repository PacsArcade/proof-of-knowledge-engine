# Bot Extension — ops bots acting for a server owner 🤖💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> The MUD's operator rails are documented in [`services/mud/README.md`](../services/mud/README.md).

A pokenode owner can let a bot — **pacBOT** is the first — read their node's state and act
on their behalf: watch the event feed, answer "why is my verse slow?", broadcast a notice,
bench a griefer at 3am. The owner stays in charge: the extension is **off by default**, the
toggle is theirs, and every bot action lands in the same event log the owner reads.

## The owner's switch

Three equivalent ways to flip it:

| Where | How |
|---|---|
| Web console (`http://127.0.0.1:4001/`) | **Extensions** rail → PACBOT **ON/OFF** |
| Server console (stdin) | `ext pacbot on` / `ext pacbot off` |
| HTTP | `POST /extensions {"name":"pacbot","enabled":true}` |

State persists in `services/mud/data/extensions.json` (override: `PA_EXTENSIONS_FILE`)
and survives reboots. Toggling emits an `admin` event.

## How a bot authenticates

Bots use the node's admin rails on the admin port (default `4001`) with **two headers**:

```
X-POKE-Admin-Token: <the node's admin token>
X-POKE-Bot: pacbot
```

The `X-POKE-Bot` header is the honesty contract: it names the extension the request runs
under. While that extension is disabled the node answers **403** with a hint telling the
owner how to enable it — even with a valid admin token. Requests without the header are
treated as the owner themselves; a well-behaved bot ALWAYS sends it.

## What a bot may read

| Endpoint | Purpose |
|---|---|
| `GET /stats` | players online, rooms, verse, store backend, art mode, QA counters |
| `GET /events?since=<n>` | the live event feed (joins, parts, rune etches, admin actions) — poll with the returned `next` cursor |
| `GET /health` | alias of `/stats` for liveness checks |
| `GET /nodes` | knowledge-swarm health (corpora, shard cache, manifest verification) |
| `GET /system` + `GET /system/history` | CPU / memory / network telemetry |
| `GET /relays`, `GET /torrent` | knowledge sources + corpus transfer state |
| `GET /games`, `GET /extensions` | linked game front-ends, extension states |
| `GET /players/<name>/history` | a player's recent log lines (moderation context) |

## What a bot may do

Same rails the owner uses — every action is evented and attributable:

| Endpoint | Action |
|---|---|
| `POST /broadcast {"message"}` | operator notice to every player |
| `POST /mute` / `POST /timeout` / `POST /kick` | moderation (branded, player-respecting messages) |
| `POST /chat {"enabled"}` | Matrix chat bridge on/off |
| `POST /relays` `/relays/toggle` `/relays/remove` | manage knowledge sources |
| `POST /torrent {"action"}` | pause/resume corpus transfers |
| `POST /art {"mode":"ascii"\|"media"}` | force ASCII art or allow full media |
| `POST /reboot` / `POST /shutdown` | drain + restart / stop (bots should confirm with the owner first) |

**Not** for bots: `POST /extensions` (the owner's switch is the owner's), `POST /games`.
They aren't blocked for the owner's own tooling, but a bot flipping its own permission
switch defeats the point — pacBOT's skill refuses to.

## Troubleshooting loop (what pacBOT's extension does)

1. `GET /health` — is the node up? uptime sane?
2. `GET /events?since=<cursor>` — anything red? repeated `warn` events?
3. `GET /system/history` — CPU/mem spikes lining up with complaints?
4. `GET /nodes` + `GET /torrent` — is the knowledge swarm the bottleneck?
5. Report findings to the owner (Matrix DM / console); act only within the table above.

Building the full pacBOT skill extension (interview + cross-verse troubleshooting) is
tracked in `docs/ROADMAP.md`; this contract is what it plugs into.

## Writing your own bot

Any HTTP client works. Minimal poller:

```python
import json, time, urllib.request

BASE = "http://127.0.0.1:4001"
HDRS = {"X-POKE-Admin-Token": "<token>", "X-POKE-Bot": "mybot"}

def get(path):
    req = urllib.request.Request(BASE + path, headers=HDRS)
    return json.loads(urllib.request.urlopen(req, timeout=5).read())

cursor = 0
while True:
    feed = get(f"/events?since={cursor}")
    for e in feed["events"]:
        print(e["at"], e["kind"], e["msg"])
    cursor = feed["next"]
    time.sleep(5)
```

Register your bot's name as an extension (ask the owner to add it to
`extensions.json`) so the owner can switch **you** off too. That's the deal. 💜
