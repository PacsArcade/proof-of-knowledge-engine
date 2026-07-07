# mud — the text terminal front-end (telnet/ANSI) 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

`mud` is the **text terminal MUD server** — the retro front-end into the same world the Luanti
voxel verse renders. It's a **persistent-window** client: the game lives in one fixed double-line
frame that **redraws in place** — the room, the Oracle's dialogue, your rune card, your profile all
update *inside* the window (doors show as arrow-gaps in the frame), while a message log underneath
carries transient lines (says, arrivals, operator notices). Special effects (boss animations, the
rune-etch) redraw the frame frame-by-frame. Every command that touches the world (`pull lever`,
`look`) mutates DB-2 via **state-sync** — the MUD never owns world state.

In-game commands include: movement + `look`, `talk oracle` / `answer` / `ask oracle`, `challenge`
(the boss in the dungeon, `down` from the entrance), `pull lever`, `stats` (your attributes) /
`examine <name>` (another fren), `link fren|nostr|space` + `verify <code>`, `backup` (anchor
progress on-chain), `profile`, `certs`, `inventory`, `say`, `who`, `help`. Players have **attributes**
(level, knowledge XP, runes, energy) shown in the window HUD; XP comes from the Oracle and bosses.

**You don't have to be exact.** A **fast path** runs known commands instantly (zero LLM, zero lag);
anything unrecognized (or free chat with an NPC) takes the **fuzzy path** — heuristics first, then the
local LLM with a *tiny* context (compact state + the player's last few turns from DB-2, so no
memory-blowing context runs). So "sup" to the Oracle, "go down", "who's the boss" all just work when
`PA_INFERENCE_BASE_URL` + `PA_GEN_MODEL` are set; without a model it falls back to heuristics.

If the node is wired to **frens.earth** (`PA_FRENS_URL`), new players are walked through claiming
their `@fren`; standalone nodes keep the plain experience.

Boss/lesson animations use the `animate()` primitive — see [`art/`](art/) for the frame pipeline.

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
python services/mud/server.py     # telnet :4000 · WebSocket :4002 · console+game web :4001
python services/mud/play.py       # a tiny terminal client — or: telnet 127.0.0.1 4000
```

**Play in a browser** — open **`http://127.0.0.1:4001/play`**. A self-contained web client
([`webclient.html`](webclient.html)) connects over a **stdlib WebSocket bridge**
([`webbridge.py`](webbridge.py)) to the *same* game loop the telnet client uses — one engine, two
transports — and renders the server's ANSI redraws with a tiny in-browser interpreter + a CRT
theme. Great for the flagship site and phones/cyberdecks; the design team can restyle it freely.
Point your local arcade site at it, and set `PA_LOCAL_SITE_URL` to link back from the console/game.

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
- **Web console** — open `http://127.0.0.1:4001/` in a browser: a self-contained arcade dashboard
  ([`admin.html`](admin.html)) with labeled widgets (node, players, knowledge-swarm, controls). The
  page loads without a token; paste the admin token once and it's stored locally and sent on every
  API call. Backed by the localhost HTTP rails (`X-POKE-Admin-Token` auth): `GET /stats /nodes`,
  `POST /broadcast /kick /chat /reboot /shutdown`.

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
