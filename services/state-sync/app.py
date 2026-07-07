"""state-sync/app.py — the HOT translation layer keeping Luanti and the MUD in sync. 💜

SCAFFOLDING / STUB. Structurally real FastAPI app; every DB-2 write is a TODO.

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

import os
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

# DB-2, the live world / Blackboard. See .env.example / CONVENTIONS §6.
PA_DB2_URL = os.environ.get("PA_DB2_URL", "postgresql://arcade:change-me@postgres-gamestate:5432/gamestate")

app = FastAPI(title="state-sync", version="0.0.1-stub")

# TODO: open an asyncpg pool to PA_DB2_URL on startup; close on shutdown.
#       Keep the pool warm — connection setup must not land in the 50 ms budget.
_db_pool = None


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

async def _apply_world_mutation(world: str, actor: str, object_id: str,
                                intent: str, meta: dict[str, Any]) -> WorldState:
    """Translate a normalized intent into a single DB-2 write and return the new state.

    This is the one place the world actually changes. Luanti events and MUD commands are
    both normalized into (object_id, intent) and routed through here so the two front-ends
    can never diverge.
    """
    # TODO: BEGIN; SELECT current object state FOR UPDATE; compute the transition
    #       (e.g. a "logic gate lever" toggles + may open a linked door); UPDATE world_object
    #       and any linked objects; bump revision; COMMIT. All node-local, all inside the
    #       HOT budget. Return the resulting WorldState.
    # TODO: if the transition should notify Matrix or trigger any COLD work, enqueue it for a
    #       background worker HERE — do NOT await it.
    raise NotImplementedError("TODO: apply DB-2 world mutation for %r on %r" % (intent, object_id))


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


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "state-sync", "tier": "HOT"}
