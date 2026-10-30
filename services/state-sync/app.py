"""state-sync/app.py — the HOT translation layer keeping Luanti and the MUD in sync. 💜

The world-mutation path now PERSISTS through the shared world store (SQLite in dev, DB-2 in
prod) — the same store the MUD uses. Linked-object logic (a lever opening a specific door) and
COLD-tier follow-up enqueueing remain TODO; the toggle/on/off transition is real.

This is the translation layer. A world event from Luanti (a lever pulled) and a text command
from the MUD (`pull lever`) both get translated here into the SAME DB-2 game-state mutation,
and the resulting state is returned to the caller. Because both front-ends funnel through this
one service, a change in one world is instantly authoritative for the other.

Tier: HOT (docs/CONVENTIONS.md §1). Budget < 50 ms.
    - MUST be node-local and fast.
    - MUST NOT make any network / COLD-tier call on the request path (no Matrix, no torrent,
      no on-chain, no LLM generation). If a translated action needs COLD follow-up, enqueue it
      for a background worker; never await it inside the request.

Port: 8082.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

# Shared persistence substrate — the SAME world store the MUD uses, so both front-ends mutate
# ONE world. Dev = SQLite (PA_GAMESTATE_SQLITE); production = Postgres DB-2 (PA_DB2_URL). See
# services/common/world_store.py and CONVENTIONS §6.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common"))
import world_store  # noqa: E402

app = FastAPI(title="state-sync", version="0.0.2")
STORE = world_store.open_store()


@app.on_event("shutdown")
async def _close_store() -> None:
    STORE.close()


# --------------------------------------------------------------------------- #
# Request / response models                                                   #
# --------------------------------------------------------------------------- #

class LuantiEvent(BaseModel):
    """A world event emitted by the Luanti mod (see luanti/mods/pacsarcade/init.lua)."""
    world: str                              # world / realm id
    actor: str                              # player id who caused it
    object_id: str                          # the world object, e.g. a specific lever node
    event: str                              # e.g. "lever_pulled", "lever_reset"
    pos: Optional[dict[str, float]] = None  # {x, y, z} in the voxel world
    meta: dict[str, Any] = {}


class MudCommand(BaseModel):
    """A parsed text command from the MUD server (see services/mud/server.py)."""
    world: str
    actor: str
    verb: str                               # e.g. "pull", "push", "open"
    target: str                             # e.g. "lever", "door:north"
    args: list[str] = []


class WorldState(BaseModel):
    """The resulting authoritative state slice, sent back to whichever front-end asked."""
    object_id: str
    state: dict[str, Any]                   # e.g. {"lever": "on", "door:north": "open"}
    revision: int                           # DB-2 row version, so front-ends can reconcile


# --------------------------------------------------------------------------- #
# The shared mutation path — BOTH endpoints converge here                     #
# --------------------------------------------------------------------------- #

def _normalize(verb_or_event: str) -> str:
    """Map a MUD verb OR a Luanti event onto one shared vocabulary, so both front-ends resolve
    to the identical transition."""
    v = (verb_or_event or "").lower()
    if v in ("open", "lever_on", "on"):
        return "on"
    if v in ("close", "lever_reset", "lever_off", "off"):
        return "off"
    return "toggle"  # pull / push / lever_pulled / toggle


async def _apply_world_mutation(world: str, actor: str, object_id: str,
                                intent: str, meta: dict[str, Any]) -> WorldState:
    """Translate a normalized intent into a single world-state write and return the new state.

    This is the one place the world actually changes. Luanti events and MUD commands are both
    normalized into (object_id, intent) and routed through here so the two front-ends can never
    diverge. Persisted via the shared world store (SQLite in dev, DB-2 in prod) — node-local, so
    it stays inside the HOT budget. NOTE: any COLD follow-up (Matrix, on-chain) must be enqueued
    for a background worker here, never awaited on this path.
    """
    action = _normalize(intent)
    state_on, revision = await _read_object(world, object_id)
    if action == "toggle":
        state_on = not state_on
    elif action == "on":
        state_on = True
    elif action == "off":
        state_on = False
    revision += 1
    await _write_object(world, object_id, state_on, revision)
    return WorldState(object_id=object_id, state={object_id: "on" if state_on else "off"}, revision=revision)


# Shared objects the MUD already owns. The MUD keeps the vault lever as a bare boolean in the
# store under (room="vault", key="lever"); a Luanti lever whose object_id is one of these aliases
# reads and writes that SAME row, so `pull lever` in the vault and a right-click in Luanti are
# one switch. The revision counter lives beside it as (room, key + ".rev"). Any other object_id
# uses the generic obj:<id> record as before.
SHARED_OBJECTS: dict[str, tuple[str, str]] = {
    "vault_lever": ("vault", "lever"),
    "lever": ("vault", "lever"),
}


async def _read_object(world: str, object_id: str) -> tuple[bool, int]:
    if object_id in SHARED_OBJECTS:
        room, key = SHARED_OBJECTS[object_id]
        on = await asyncio.to_thread(STORE.get_feature, room, key, False)
        rev = await asyncio.to_thread(STORE.get_feature, room, key + ".rev", 0)
        return bool(on), int(rev)
    cur = await asyncio.to_thread(STORE.get_feature, world, f"obj:{object_id}", {"state": False, "revision": 0})
    return bool(cur.get("state", False)), int(cur.get("revision", 0))


async def _write_object(world: str, object_id: str, on: bool, revision: int) -> None:
    if object_id in SHARED_OBJECTS:
        room, key = SHARED_OBJECTS[object_id]
        await asyncio.to_thread(STORE.set_feature, room, key, bool(on))
        await asyncio.to_thread(STORE.set_feature, room, key + ".rev", revision)
        return
    await asyncio.to_thread(STORE.set_feature, world, f"obj:{object_id}", {"state": on, "revision": revision})


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #

@app.post("/event/luanti", response_model=WorldState)
async def event_luanti(evt: LuantiEvent) -> WorldState:
    """A Luanti world action (e.g. a lever pulled) → DB-2 write → resulting state."""
    # TODO: map evt.event → a normalized intent (e.g. "lever_pulled" → "toggle").
    intent = evt.event
    return await _apply_world_mutation(evt.world, evt.actor, evt.object_id, intent, evt.meta)


@app.post("/command/mud", response_model=WorldState)
async def command_mud(cmd: MudCommand) -> WorldState:
    """A MUD text command (e.g. `pull lever`) → the SAME DB-2 write → resulting state."""
    # TODO: resolve (cmd.verb, cmd.target) → (object_id, normalized intent) using the same
    #       vocabulary the Luanti path uses, so both front-ends mutate identical state.
    object_id = cmd.target                     # placeholder resolution
    intent = cmd.verb
    return await _apply_world_mutation(cmd.world, cmd.actor, object_id, intent, {"args": cmd.args})


@app.get("/state/{world}/{object_id}", response_model=WorldState)
async def get_state(world: str, object_id: str) -> WorldState:
    """Read one object's current state (no mutation). The Luanti mod polls this so a lever
    pulled in the MUD swings in the voxel world."""
    on, rev = await _read_object(world, object_id)
    return WorldState(object_id=object_id, state={object_id: "on" if on else "off"}, revision=rev)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "state-sync", "tier": "HOT"}
