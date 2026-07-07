# matrix-bridge — MUD/Luanti chat ⇄ Matrix rooms 💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

`matrix-bridge` relays chat **both ways** between the in-game front-ends (the MUD and the Luanti
voxel verse) and **Matrix rooms** on the node's Dendrite homeserver. A fren saying something in
the MUD shows up in the realm's Matrix room; a message posted from Matrix (a phone, another
client, a federated server) shows up in-game. It's how a verse stays social across devices and
across federated nodes.

It also carries the **Warden's quarantine notices** to the operator's encrypted **Matrix admin
room** — that's how the human-in-the-loop guardrail reaches the operator.

## Tier

**COLD.** Matrix federation is seconds→minutes, async, and crosses the network. **This bridge is
explicitly never on the gameplay hot path.** The MUD and Luanti hand chat lines to the bridge and
move on immediately; delivery to Matrix happens in the background, eventually-consistent.

## Port

**8084** (docker-compose service name: `matrix-bridge`).

## How it fits the whole

```
 MUD / Luanti chat ──(async, fire-and-forget)──► matrix-bridge (COLD) ──► Matrix rooms
                                          ▲                                     │
                                          └─────────── inbound relay ◄──────────┘
 Warden quarantine ──────────────────────► matrix-bridge ──► operator's Matrix admin room
```

## How to run it

```bash
docker compose up matrix-bridge
# or, local dev:
cd services/matrix-bridge
pip install matrix-nio httpx   # TODO: pin in requirements.txt
python bridge.py               # connects to the local Dendrite homeserver
```

Required env: `PA_MATRIX_SERVER_NAME`; reaches Dendrite at `http://matrix:8008`.

> ⚠️ **Scaffolding.** `bridge.py` is a commented async stub with `TODO`s where the Matrix client
> login, the room relays, and the in-game egress go.
