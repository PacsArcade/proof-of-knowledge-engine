# mud — the text terminal front-end (telnet/ANSI) 💜

> Part of **Pac's Arcade — The Federated Knowledge Engine**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

`mud` is the **text terminal MUD server** — the retro front-end into the same world the Luanti
voxel verse renders. Connect over telnet, get an ANSI / 8-bit-styled scrolling world. Every
command that touches the world (`pull lever`, `open door`, `look`) is sent to **state-sync**,
which translates it into a DB-2 write — so the MUD and Luanti are always looking at the **same**
game state. The MUD never owns world state; DB-2 does, via `state-sync`.

When the MUD shows **LLM output** (Oracle dialogue, Architect room description), it **streams
tokens** as they generate.

## Tier

**HOT.** < 50 ms for world commands. World reads/writes go through `state-sync` (also HOT, also
node-local) — the MUD never makes a COLD-tier call on the command path. Chat lines destined for
Matrix are handed to `matrix-bridge` asynchronously, off the hot path.

## Port

**4000** (telnet; docker-compose service name: `mud`).

## Why streaming matters here

A MUD is scrolling text. With token streaming, perceived latency is **time-to-first-token**, not
time-to-full-response — the Oracle "starts talking" almost immediately and the text scrolls in as
it's generated, which is exactly how a MUD already feels. Streaming turns the WARM LLM budget
(first token < 300 ms) into a natural fit for the medium.

## How it fits the whole

```
 telnet client ──► mud (HOT) ──commands──► state-sync (HOT) ──► DB-2
                     │
                     ├──LLM dialogue (streamed)──► inference (WARM)
                     └──chat lines (async)───────► matrix-bridge (COLD)
```

## How to run it

```bash
docker compose up mud
# or, local dev:
cd services/mud
python server.py           # listens on 0.0.0.0:4000
# then, from another terminal:
telnet localhost 4000
```

Required env: `PA_INFERENCE_BASE_URL`, `PA_GEN_MODEL` (streamed dialogue); reaches `state-sync`
at `http://state-sync:8082`.

> ⚠️ **Scaffolding.** `server.py` is a commented asyncio stub with `TODO`s where the telnet
> protocol handling, the state-sync calls, and the token streaming go.
