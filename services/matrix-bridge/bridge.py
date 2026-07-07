"""matrix-bridge/bridge.py — relay MUD/Luanti chat ⇄ Matrix rooms. 💜

SCAFFOLDING / STUB. The async relay shape is real; the Matrix client wiring is a TODO.

This bridge moves chat both ways between the in-game front-ends (MUD, Luanti) and Matrix rooms
on the node's Dendrite homeserver, and carries the Warden's quarantine notices to the operator's
encrypted Matrix admin room.

Tier: COLD. Matrix federation is async, eventually-consistent, and crosses the network.
    *** This bridge is NEVER on the gameplay hot path. ***
The MUD/Luanti hand us a chat line and return immediately; we deliver to Matrix in the
background. Nothing in here is ever awaited by a HOT-tier request.

Port: 8084.
"""

from __future__ import annotations

import asyncio
import os

PA_MATRIX_SERVER_NAME = os.environ.get("PA_MATRIX_SERVER_NAME", "verse.local")
MATRIX_HOMESERVER_URL = os.environ.get("PA_MATRIX_HOMESERVER_URL", "http://matrix:8008")
BRIDGE_PORT = 8084

# Background queue of outbound chat lines. HOT front-ends enqueue and return; we drain async.
_outbound: "asyncio.Queue[dict]" = asyncio.Queue()


class MatrixBridge:
    """Two-way, fully-async relay. Nothing here blocks gameplay."""

    def __init__(self) -> None:
        self._client = None            # TODO: matrix-nio AsyncClient

    async def connect(self) -> None:
        """Log in to the local Dendrite homeserver and start sync."""
        # TODO: AsyncClient(MATRIX_HOMESERVER_URL, user=…); login with the bridge's access token;
        #       register a message callback -> self.on_matrix_message; start sync_forever().
        raise NotImplementedError("TODO: connect matrix-nio client to Dendrite")

    # -- in-game  ->  Matrix (async egress) --------------------------------- #

    async def enqueue_from_game(self, world: str, actor: str, text: str, room_alias: str) -> None:
        """Called by MUD/Luanti (fire-and-forget). Returns instantly; delivery is background."""
        await _outbound.put({"world": world, "actor": actor, "text": text, "room": room_alias})

    async def _egress_worker(self) -> None:
        """Drain the outbound queue into Matrix rooms, in the background."""
        while True:
            msg = await _outbound.get()
            try:
                # TODO: resolve msg["room"] alias -> room_id; client.room_send a formatted line
                #       like "<actor> text". Retry/backoff on failure — COLD, never a hang.
                pass
            finally:
                _outbound.task_done()

    # -- Matrix  ->  in-game (inbound relay) -------------------------------- #

    async def on_matrix_message(self, room, event) -> None:
        """A message arrived in a bridged Matrix room; relay it back into the game world."""
        # TODO: map room -> (world, in-game channel); push the line to the MUD/Luanti chat
        #       surfaces (again async — this is not on any hot path).
        raise NotImplementedError("TODO: relay inbound Matrix message into the game")

    # -- Warden quarantine notices ------------------------------------------ #

    async def notify_operator_quarantine(self, summary: str, admin_room: str) -> None:
        """Route a Warden quarantine to the operator's encrypted Matrix admin room."""
        # TODO: send `summary` to the admin_room (E2EE). This is the human-in-the-loop path
        #       from the guardrail — the operator approves/rejects from Matrix.
        raise NotImplementedError("TODO: send quarantine notice to operator admin room")


async def main() -> None:
    bridge = MatrixBridge()
    # TODO: also expose a tiny HTTP surface on BRIDGE_PORT so services (Warden) can POST notices.
    await bridge.connect()
    await asyncio.gather(bridge._egress_worker())


if __name__ == "__main__":
    asyncio.run(main())
