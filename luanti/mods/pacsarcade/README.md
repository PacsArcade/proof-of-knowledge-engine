# pacsarcade — the Luanti (Minetest engine) mod 💜

> Part of **Pac's Arcade — The Federated Knowledge Engine**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../../docs/CONVENTIONS.md).

## Role

This mod is the **voxel-verse front-end** into the Federated Knowledge Engine — the graphical
twin of the text MUD. It renders the world in 3D, but it does **not** own world state. Every
world action funnels through the node-local `state-sync` service, so the Luanti world and the
MUD are always looking at the **same** DB-2 game state. Pull a lever here, and the MUD player
sees the door open too.

It ships two stubs:

- A **"logic gate lever"** node. Right-clicking it POSTs a world event to
  `state-sync` `POST /event/luanti`, which mutates DB-2 and returns the resulting state.
- A **chat hook** (`register_on_chat_message`) that forwards in-game chat to `matrix-bridge`
  (COLD, async, fire-and-forget) and returns `false` so normal in-world chat still happens.

## Tier

**HOT** for world actions (the state-sync call is node-local and fast). Chat forwarding is
handled on the **COLD** tier by `matrix-bridge` — the mod hands off the line and returns
immediately; it never blocks the game step on Matrix.

## Port

The Luanti server itself listens on **30000/udp** (docker-compose service name: `luanti`). This
mod reaches sibling services at `state-sync:8082` and `matrix-bridge:8084`.

## Install / run

1. Mount this folder as a mod in your Luanti world (`worldmods/pacsarcade` or a configured
   mod path).
2. Enable it for the world (in the world's `world.mt`, `load_mod_pacsarcade = true`).
3. **Whitelist HTTP** so the mod can reach node-local services. In `minetest.conf`:
   ```
   secure.http_mods = pacsarcade
   ```
   Without this, `minetest.request_http_api()` returns nil and the levers stay inert (the mod
   logs a warning and degrades gracefully — never crashes).
4. Start the `luanti` service (`docker compose up luanti`) alongside `state-sync` and
   `matrix-bridge`.

## Files

| File | Purpose |
|------|---------|
| `mod.conf`  | Mod metadata (`name = pacsarcade`, description, depends). |
| `init.lua`  | Registers the logic-gate lever + chat-forwarding hook (stub). |
| `README.md` | This file. |

> ⚠️ **Scaffolding.** `init.lua` is a commented stub. The node registers and the HTTP calls are
> wired, but textures, DB-2 state reflection (swinging the linked door), and room-alias mapping
> are marked `TODO`.
