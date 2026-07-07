# LATENCY — why a federated, meshed Verse still feels instant

> This doc exists because of the right question: *if Verses talk to each other over a mesh,
> and players share a corpus over a torrent, won't the game feel laggy?* The answer is no —
> **because the mesh is never on the path a player waits on.** Here is exactly how.

## The one rule

**Nothing a player waits on ever crosses the network.** We split every operation into three
tiers and keep the slow, federated, eventually-consistent things strictly in the background.

| Tier | What lives here | Budget | Crosses the network? |
|------|-----------------|--------|----------------------|
| **HOT** | MUD commands, Luanti actions, state-sync, DB-2 reads/writes | **< 50 ms** | **No** — node-local, authoritative |
| **WARM** | LLM generation, guardrail embed/KNN | **first token < 300 ms** | **No** — local GPU |
| **COLD** | Matrix federation, corpus torrent, on-chain discovery | seconds → minutes | Yes — async, background |

## HOT: gameplay is local and authoritative

Movement, looking, pulling a lever, typing a command — all of it resolves against the **local**
`postgres-gamestate` (DB-2) on the same box, through `state-sync`. There is no round-trip to
another Verse. This is identical whether one node exists or a thousand federate. Players on the
same node interact through the authoritative server; we **never** do real-time peer-to-peer
between player clients (that is where NAT traversal and jitter ruin everything). Clients are thin;
the node is the referee.

## WARM: the GPU is local, and we stream

Socratic dialogue and room generation run on the operator's own GPU. Two things keep this feeling
instant even under load:

1. **Token streaming.** We render tokens as they generate, so perceived latency is
   *time-to-first-token* (~100–300 ms), not full-completion time. A MUD's whole aesthetic is text
   scrolling in — streaming hides latency *for free*, and it fits the medium perfectly.
2. **Continuous batching (vLLM).** This is the direct answer to the concurrency worry. With many
   frens playing at once, a naive server serializes requests and the queue's tail waits. vLLM's
   continuous batching interleaves many players' token streams on one GPU, so first-token latency
   stays low as the classroom fills. The **node-wizard auto-selects** vLLM when it detects the VRAM
   and expected concurrency to justify it, and Ollama (simpler) for small/solo nodes. The rest of
   the stack talks to one OpenAI-compatible endpoint either way, so the choice is a config flag.

Extra WARM tricks:
- **Speculative pre-generation.** The Architect builds likely-next rooms during idle GPU cycles
  (from each player's `competency_node`), so they're already warm when the player walks in.
- **Content-addressed cache.** Generated rooms/embeddings are cached and reused; the COLD mesh can
  even share a room generated on Verse A with Verse B — but that sharing happens in the background.

## COLD: the mesh, kept off the path

Matrix federation (cross-Verse chat, community, milestone sharing) and the BitTorrent **corpus
mesh** are eventually-consistent background processes. They are genuinely slower and less reliable
than a LAN — so we design as if they are, and never let gameplay depend on them:

- **Corpus reads are local.** DB-1 lives on the box. The torrent layer **prefetches** popular shards
  and keeps an **LRU cache**. On a cache miss, we do not hang — we degrade **in-fiction**: *"The
  Archivist is retrieving that tome from the network…"*, fetch in the background, and continue.
- **Federation is best-effort.** A milestone shared to another Verse, a cross-node message — these
  tolerate seconds of delay because they are social, not twitch. The player is never blocked on them.
- **Discovery is a background scan.** OP_RETURN Verse announcements are read off the chain on a timer
  to populate the realm directory; nothing in a session waits on it.

## What this means for your mesh worry, concretely

Even if the mesh between Verses is *poor* — high latency, flaky peers — the player experience does
not degrade, because:
- their inputs resolve locally (HOT),
- their AI tutor streams from a local GPU (WARM),
- and the only things that touch the mesh (community chat, corpus repair, discovery) are things a
  human never taps their foot waiting for (COLD).

A slow mesh makes cross-Verse *social* features slower. It never makes *the game* slower. That
separation is the whole design, and it's enforced in code: HOT-tier services are grepped to prove
they make no COLD/WARM blocking calls on a request path (see the `state-sync-engineer` and
`mud-engine-dev` agents' definition-of-done).
