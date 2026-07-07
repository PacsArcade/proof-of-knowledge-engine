# mud — the text terminal front-end (telnet/ANSI) 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
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

**Dev mode (zero setup — this is what you run today):**

```bash
python services/mud/server.py     # serves on 127.0.0.1:4000, persists to data/gamestate.dev.sqlite
python services/mud/play.py       # a tiny client — or: telnet 127.0.0.1 4000
```

Dev mode keeps the world in a local SQLite file (`services/common/world_store.py`) and uses your
local LLM if `PA_INFERENCE_BASE_URL` + `PA_GEN_MODEL` are set, else a scripted pacbot Oracle. Your
room, inventory, `@fren`/nostr/spaces links, and etched runes persist across reconnects.

**In the stack (production, Podman):**

```bash
podman compose -f infra/compose.yaml up mud
```

In production the MUD reaches `state-sync` at `http://state-sync:8082`; dev mode uses the store directly.

## Operator console (server-side)

The MUD is a node an operator runs, not a black box. One set of actions, three ways to drive it:

- **Local stdin** — type commands in the terminal running `server.py`.
- **In-MUD** — `admin <token>` elevates a player (token auto-generated + printed at startup, or set
  `PA_ADMIN_TOKEN`), then `stats`, `nodes`, `broadcast`, `kick`, `reboot`, `shutdown`.
- **HTTP rails** (for the web-admin page) — localhost-only by default on `PA_MUD_ADMIN_PORT` (4001),
  `X-POKE-Admin-Token` auth: `GET /stats /nodes`, `POST /broadcast /kick /chat /reboot /shutdown`.

What it surfaces:
- **stats** — logged-in players (name/@fren, room, uptime, idle), node uptime, runes etched this
  session, store backend, Oracle mode.
- **nodes** — knowledge-swarm health: nodes synced, corpora/swarms, shard-cache ratio, manifest
  verification (best-effort from `corpus`, cached, COLD/non-blocking; `PA_SWARM_MOCK` for demo).
- **reboot** drains players and restarts (state persists); **shutdown** drains + closes the store.

Matrix chat is **off by default** (`PA_CHAT_MATRIX`); when on, in-room `say` also relays to the
Matrix verse room via `matrix-bridge` (COLD, never on the hot path).

Env: `PA_INFERENCE_BASE_URL`, `PA_GEN_MODEL`, `PA_ADMIN_TOKEN`, `PA_MUD_ADMIN_HOST/PORT`,
`PA_CHAT_MATRIX`, `PA_MATRIX_BRIDGE_URL`, `PA_CORPUS_URL`, `PA_SWARM_MOCK`. See `.env.example`.
