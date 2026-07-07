# state-sync — the translation layer (Luanti ⇄ MUD ⇄ DB-2) 💜

> Part of **Pac's Arcade — The Federated Knowledge Engine**.
> See the canonical contract in [`docs/CONVENTIONS.md`](../../docs/CONVENTIONS.md).

## Role

`state-sync` is the **translation API** that keeps both front-ends looking at the same world.
A **lever pulled in Luanti** and a **command typed in the MUD** both land here, get translated
into the **same DB-2 game-state write**, and return the resulting state. Neither front-end owns
the world — DB-2 (`postgres-gamestate`) is the single authority, and `state-sync` is the only
thing that mutates it on the hot path.

That's the whole point of this service: one world, two windows. Pull a lever in the voxel verse
and the MUD player sees the door open; type `pull lever` in the MUD and the Luanti player sees
it too — because both went through here.

## Tier

**HOT.** < 50 ms latency budget. **Node-local and fast — no network / COLD-tier calls on the
request path, ever.** No Matrix, no torrent, no on-chain, no LLM generation inside a request.
If a translated action needs COLD work (e.g. notify Matrix), it's enqueued for a background
worker, never awaited here.

## Port

**8082** (docker-compose service name: `state-sync`).

## Endpoints

| Method | Path             | Purpose |
|--------|------------------|---------|
| `POST` | `/event/luanti`  | Translate a Luanti world event (e.g. a lever pulled) → a DB-2 write; return new state. |
| `POST` | `/command/mud`   | Translate a MUD text command (e.g. `pull lever`) → a DB-2 write; return new state. |
| `GET`  | `/healthz`       | Liveness. |

Both write endpoints converge on the **same** DB-2 mutation path, so the two front-ends stay
in lock-step.

## How it fits the whole

```
 Luanti mod  ──POST /event/luanti──►                      ┌─────────────────────┐
                                     state-sync (HOT) ───► │ DB-2 postgres-      │
 MUD server ──POST /command/mud───►  (this service)   ◄─── │ gamestate (world)   │
                                                           └─────────────────────┘
```

## How to run it

```bash
docker compose up state-sync
# or, local dev:
cd services/state-sync
pip install fastapi uvicorn asyncpg   # TODO: pin in requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8082
```

Required env: `PA_DB2_URL` (the world, DB-2).

> ⚠️ **Scaffolding.** `app.py` is a commented FastAPI stub with `TODO`s where the real
> event→state translation and DB-2 writes go.
