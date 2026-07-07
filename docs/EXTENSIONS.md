# EXTENSIONS — plug any world into the POKE engine 🔌

> **POKE is the engine. A game is an extension.** The engine brings the tutor, the curriculum, the
> knowledge, the identity, and the rewards. Your world brings the *place*. Speak the small protocol
> below and your game inherits all of it — the same brain, in a new world.

This is the architecture Pac's Arcade is built on: **same knowledge, many worlds.** POKEMUD (a
terminal MUD) and the Voxel Verse (Luanti) are the two reference extensions. A RedM server, a
roguelike, a Discord bot, or your own engine are all just… the next extension.

---

## The engine is already modular

The engine is a set of **local, network-separated services** — not a monolith your game links
against. An extension talks to them over a tiny surface (HTTP + the shared DB), so extensions can be
written in *any* language and swapped freely. The seam is deliberate: no engine code assumes it's
talking to a MUD.

```
                ┌──────────────────────── POKE ENGINE (one brain) ─────────────────────────┐
   your world   │  state-sync   orchestrator   corpus        bitcoin-bridge   world_store   │
  ┌──────────┐  │  (world       (Oracle +      (knowledge     (soulbound       (identity ·   │
  │ EXTENSION│◄─┼─►state, HOT)  quests, WARM)  mesh, COLD)    runes, COLD)     memory · xp)  │
  └──────────┘  │       ▲            ▲             ▲               ▲               ▲          │
   MUD · Luanti │       └────────────┴─────────────┴───────────────┴───────────────┘         │
   · RedM · …   │                    one DB-2 world + one shared corpus                       │
                └──────────────────────────────────────────────────────────────────────────┘
```

Because POKEMUD and the Voxel Verse **both** drive `state-sync` against the **same** DB-2, a lever
pulled in one world is already pulled in the other. That's not a special case — it's the protocol.

---

## The five seams an extension speaks

An extension is any front-end that renders a world and wires player intent to these engine
capabilities. You implement as many as your world needs; the rest degrade gracefully.

| # | Seam | Engine service | What your world sends / gets |
|---|------|----------------|------------------------------|
| 1 | **World state** (HOT) | `state-sync` :8082 | `POST /event/<world>` or `/command/<world>` — a player action → one shared DB-2 mutation → the new state back. This is how two worlds stay one world. |
| 2 | **Teaching** (WARM) | `orchestrator` :8080 | Ask the **Oracle** to pose/assess a question; when a player demonstrates mastery it writes a `competency_node`. Ask the **Architect** to generate a room / quest / boss targeting that player's gaps. Output streams. |
| 3 | **Knowledge** (COLD) | `corpus` :8083 | Retrieve grounded facts for a topic; subscribe to *verses* (≈ nostr relays) and sync a shared library over BitTorrent. Bring the common knowledge, or bring your own. |
| 4 | **Rewards** (COLD) | `bitcoin-bridge` :8085 | Etch a **soulbound rune** when a class is passed; verify it; publish a backup. Regtest-gated (see `docs/SECURITY.md`). |
| 5 | **Player** | `world_store` / DB-2 | One identity, memory, and attributes (level · XP · runes · energy) that follow the player across every world. Link `@fren` / nostr / spaces once. |

Everything obeys the **three tiers** (`docs/LATENCY.md`): the player-facing loop is node-local and
fast; the mesh (knowledge, rewards, federation) is background. An extension must never block the
player on a COLD call.

---

## Build a POKE extension — the checklist

1. **Render a world** in your medium (text, voxels, a AAA map — your call).
2. **Translate player actions → `state-sync`** so your world mutates the shared state (and any other
   world sees it). Read state back to render.
3. **Surface the Oracle**: let players ask/answer; show the streamed reply; let the engine award
   competency and etch runes. (Reuse the `pacbot` educator voice.)
4. **Show the player's identity + attributes** from `world_store` — the same `@fren`, level, and runes
   they carry everywhere.
5. **Respect the guardrail + the money gates.** Never present ungrounded "facts"; never mint value on
   an unsafe network. The engine enforces both — don't route around them.
6. **Keep the hot path local.** Fast for the player; the mesh stays in the background.

That's it. You didn't have to build a tutor, a curriculum, a knowledge base, an identity system, or a
rewards ledger — you brought a world and borrowed a brain.

---

## Worked examples

- **POKEMUD** (`services/mud/`) — the reference extension. Terminal + ANSI, a persistent window, the
  Oracle, a boss, runes, and an operator console. Read it as the canonical implementation of seams 1–5.
- **The Voxel Verse** (`luanti/mods/pacsarcade/`) — a Luanti mod. A pulled lever POSTs to
  `state-sync`; the same DB-2 the MUD reads. Same knowledge, rendered in blocks.
- **RedM (sketch, future)** — a RedM (Red Dead Redemption MP) server as an extension: an NPC
  "professor" is the Oracle; a mission-giver asks the engine for a quest tuned to what the player is
  learning; completing it etches a rune to their wallet; the town's library is a corpus verse the
  server subscribes to. The cowboy never sees the engine — just a world that happens to teach.

---

## Why this matters

Education tools die in silos — one app, one curriculum, one login. POKE inverts it: **the learning
lives in the engine, and the worlds are interchangeable.** A player's knowledge, credentials, and
identity are theirs, portable across every world that speaks the protocol — a terminal today, a voxel
world tomorrow, your game next. Bring a world. We'll bring the knowledge. 💜
