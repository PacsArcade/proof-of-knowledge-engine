<!-- Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.) -->

# 🕹️ Pac's Arcade — The Proof of Knowledge Engine (P.O.K.E.)

> ### One mind. Every world.
> P.O.K.E. is a local-first, self-hosted **education engine** — a tutor that can't make things up, a
> living curriculum drawn from a library as deep as Wikipedia, and an on-chain **proof of what you've
> learned** — that *any game can plug into*. Learn real things by **playing**. Own what you earn.
> Fully open-source. Runs offline. No Discord. No proprietary APIs. Ever. 💜

## The engine — and the worlds that plug into it

**POKE is the engine. Games are extensions.** The engine carries the hard parts: a Socratic AI swarm,
a hallucination-guarded curriculum, a shared knowledge mesh, portable identity, and soulbound **rune**
rewards. A world just brings the *place*.

- 🕹️ **POKEMUD** — the reference extension: a retro terminal world, playable right now.
- 🧊 **The Voxel Verse** — the *same knowledge*, rendered in 3D on Luanti (Minetest).
- 🤠 **…your world next** — a RedM server, a roguelike, your own game. Speak the POKE protocol and
  your world inherits AI tutors, quests, shared knowledge, identity, and rewards — for free.

> **Same knowledge, many worlds. Bring a world — tap the group knowledge, or bring your own.**

How a game plugs in: **[`docs/EXTENSIONS.md`](docs/EXTENSIONS.md)** · the design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## What the engine actually does (worth reading twice)

Point *any* world at POKE and every player gets:

- **A tutor that won't lie.** A local LLM Oracle teaches Socratically; every fact it generates is
  checked against a real corpus, and anything it can't ground is quarantined for a human. The AI
  *makes the world* — it doesn't *make things up*.
- **A curriculum that adapts.** The engine remembers each player — what they know, where they stick —
  and grows rooms, quests, and bosses aimed at their gaps.
- **Proof you can hold.** Master a subject and the engine **etches a soulbound rune** to your wallet:
  your name, the moment you earned it, on Bitcoin, non-transferable, *yours*. A lost device never
  loses your record.
- **Knowledge that travels.** Nodes subscribe to each other's *verses* like nostr relays and sync a
  shared library over BitTorrent. Carry the common knowledge, or seed your own.
- **An identity that's yours.** Link your `@fren` / nostr / spaces name once — it follows you into
  every world on the network.

And it stays **fast**, because the mesh is never on a path a player waits on (below).

## Meet the Oracle — in its own words

> *"I'm the attendant at Pac's Arcade. I don't hand out answers — I trade in questions. Show me you
> truly understand a thing, and I'll etch it into a rune only you can carry. I run on your machine, I
> learn what you're chasing, and I'll find you in whatever world you walk into. Insert a token, fren.
> The high score is understanding."*

The build contract every service agrees on is [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md).

## Why it feels instant even though it's a mesh

The single rule: **the mesh is never on a path a player waits on.** Three tiers —

- **HOT** (< 50 ms): gameplay resolves against the *local* database. No network hop.
- **WARM** (first token < 300 ms): the AI runs on your *local* GPU and **streams** — text scrolls
  in immediately, which is the whole MUD aesthetic. vLLM's continuous batching keeps it fast even
  with a full classroom.
- **COLD** (async): federation, the shared corpus, on-chain discovery — all background,
  eventually-consistent, never blocking the game.

Full rationale (and the answer to *"won't the mesh be laggy?"*): [`docs/LATENCY.md`](docs/LATENCY.md).

---

## Repository layout

```
knowledge-engine/                the POKE engine + its reference extensions
│
├── services/                  ══ THE ENGINE ══  (shared by every world)
│   ├── orchestrator/            the AI swarm — Oracle · Architect · Custodian · Archivist · Warden
│   ├── guardrail/               hallucination check vs the corpus (the "won't lie" seam)
│   ├── corpus/                  the knowledge mesh — subscribe to verses, sync over BitTorrent
│   ├── bitcoin-bridge/          soulbound rune rewards + on-chain discovery
│   ├── state-sync/              world-state translation  ← the EXTENSION seam
│   ├── matrix-bridge/           community / cross-verse federation
│   └── common/                  world_store — identity · memory · attributes (one brain, many worlds)
│
├── services/mud/              ══ EXTENSION ══  POKEMUD — the terminal world (+ web operator console)
├── luanti/mods/pacsarcade/    ══ EXTENSION ══  the Voxel Verse (Luanti/Minetest)
│                                (your world goes here next — see docs/EXTENSIONS.md)
│
├── connectors/                bring-your-own knowledge sources feeding the corpus
├── docs/                      ARCHITECTURE · EXTENSIONS · LATENCY · SECURITY · CONVENTIONS · RUNES · CORPUS-MESH · ROADMAP
├── .claude/                   the AI build crew — agents (one per subsystem) + skills (node-wizard, pacbot, …)
└── infra/ · scripts/          rootless Podman stack (compose + Quadlet) · node-doctor · bootstrap
```

---

## Target machine

The reference node is **Arch Linux, bare metal**:

- AMD Ryzen 7 7800X3D · 64 GB RAM · **RTX 4070 Ti SUPER (16 GB VRAM)** · fast NVMe.

It runs entirely offline once set up. Less hardware works — the wizard adapts and warns you.
(Everything runs on **rootless Podman** — no root daemon, no `docker.sock`; other distros work too.
The commands below are Arch's `pacman`.)

---

## 🚀 Quick start — let the wizard do it

The friendliest path. The **node-wizard** reads your hardware, asks what you want to teach,
picks your inference backend, installs what's missing, loads the corpus, brings the stack up,
and hands you a **Certified Education Node** certificate at the end.

```bash
git clone <your-fork-url> knowledge-engine && cd knowledge-engine
./scripts/node-doctor.sh          # see what the wizard sees
claude                            # then: "run the node-wizard"
```

Because the wizard is a Claude Code skill, run it from inside `claude` in this repo. Prefer to
do it by hand? Follow the manual guide below — it does exactly what the wizard automates.

---

## 🕹️ Play the MUD in 30 seconds (no stack needed)

Want a taste of the world before standing up the whole node? The MUD has a **dev mode** that
runs on nothing but Python 3.11 — no Podman, no database, no models:

```bash
python services/mud/server.py     # serves the arcade on 127.0.0.1:4000
python services/mud/play.py       # in another terminal — or use: telnet 127.0.0.1 4000
```

Name yourself, `look`, head `north` to the Oracle's Alcove, `talk oracle`, and `answer` its
question. Demonstrate you understand self-custody and it etches you a **soulbound class rune** —
block time and original wallet on the card, exactly like the real thing (regtest mock in dev).
Then go `east` to the Puzzle Vault and `pull lever`. The Oracle talks to your local LLM if one is
running (`PA_INFERENCE_BASE_URL` + `PA_GEN_MODEL`); otherwise it falls back to a scripted pacbot.

Your progress **persists**: room, inventory, and earned runes are written to a local SQLite file
(`data/gamestate.dev.sqlite`), so reconnecting with the same name resumes right where you left off —
and the Oracle won't etch a rune you already hold. It's the exact same store contract the
production node uses against Postgres DB-2 (`services/common/world_store.py`).

---

## 🔧 Manual local build (server admin)

### 1. System dependencies (Arch)

```bash
# Rootless Podman + a compose front-end (no daemon, no root socket)
sudo pacman -S --needed podman podman-compose
# Give your user a subuid/subgid range for user namespaces (rootless):
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER"
podman system migrate
# Let systemd --user (the Quadlet production path) start at boot without a login:
loginctl enable-linger "$USER"

# NVIDIA driver + container toolkit, then generate the Podman CDI spec (rootless GPU)
sudo pacman -S --needed nvidia nvidia-utils nvidia-container-toolkit
nvidia-ctk cdi generate --output="$HOME/.config/cdi/nvidia.yaml"

# Corpus tooling (Kiwix reads the Wikipedia ZIM); jq for the wizard
sudo pacman -S --needed jq
# kiwix-tools is in the AUR:
yay -S kiwix-tools        # or: paru -S kiwix-tools
```

Verify the GPU is visible to rootless Podman via CDI:

```bash
podman run --rm --device nvidia.com/gpu=all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

> `scripts/node-doctor.sh` checks all of the above (podman, compose, subuid/subgid, linger, CDI)
> and tells you exactly what's missing. For a hardened, auto-restarting production deploy, use the
> **Quadlet** systemd units in [`infra/quadlet/`](infra/quadlet/) instead of compose.

### 2. Configure the node

```bash
cp .env.example .env
./scripts/node-doctor.sh          # prints a JSON hardware report + recommendations
```

Edit `.env` using the report. Key choices (all explained in [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md)):

- `PA_NETWORK=regtest` — **leave this.** Play money, zero risk. Mainnet is gated (see step 8).
- `PA_INFERENCE_BACKEND=ollama` — small/solo node. Use `vllm` for a busy classroom (see step 3).
- `PA_GEN_MODEL=` — a quantized 7–8B chat model that fits 16 GB (the doctor suggests one).
- `PA_EMBED_MODEL=nomic-embed-text` — embeddings for the corpus + guardrail.
- `PA_CORPUS=simple-wikipedia` — start here (hours to embed, not weeks).

### 3. Choose & warm the inference backend

Two backends, one OpenAI-compatible interface — pick by how many frens play at once:

- **Ollama** (simplest, solo/small): see [`infra/inference/ollama.md`](infra/inference/ollama.md).
- **vLLM** (continuous batching, low first-token latency under load, classroom/busy):
  see [`infra/inference/vllm.md`](infra/inference/vllm.md).

Pull your models (Ollama example):

```bash
podman compose -f infra/compose.yaml --profile ollama up -d inference
podman compose -f infra/compose.yaml exec inference ollama pull "$PA_GEN_MODEL"
podman compose -f infra/compose.yaml exec inference ollama pull nomic-embed-text
```

> **Latency tip:** we stream tokens everywhere, so the player sees text immediately. If you have
> the VRAM and expect a crowd, `vllm` keeps first-token latency low as the room fills. Either way,
> the mesh between Verses stays off the gameplay path — see [`docs/LATENCY.md`](docs/LATENCY.md).

### 4. Bring up the databases

The two brains initialize from the SQL in `infra/postgres/`:

```bash
podman compose -f infra/compose.yaml up -d postgres-gamestate postgres-source
```

- **DB-2 `postgres-gamestate`** (5432) — the live world / the Blackboard.
- **DB-1 `postgres-source`** (5433, pgvector) — *The Source*: the read-only, vectorized corpus
  the guardrail checks against.

### 5. Clone Wikipedia into DB-1 (the corpus)

Download the **Simple English Wikipedia** ZIM (a few GB) from the Kiwix library, drop it in
`data/`, then ingest → chunk → embed → pgvector:

```bash
mkdir -p data
# grab the latest simple-english maxi ZIM from https://library.kiwix.org (wikipedia_en_simple_all_maxi)
#   e.g. wget -P data/ <kiwix-mirror>/wikipedia_en_simple_all_maxi_YYYY-MM.zim
python services/corpus/ingest.py --zim data/wikipedia_en_simple_all_maxi_*.zim
```

Prefer not to embed from scratch? Join the **knowledge swarm** and pull ready-made, **signature-
verified** shards from other Verses — Pac's Arcade seeds the canonical *common knowledge* corpus,
and you can add your own sources alongside it (content-addressed over BitTorrent, background, cached):

```bash
python services/corpus/torrent.py sync-common      # pull the common corpus (on by default)
python services/corpus/torrent.py link-source <id>  # also seed/share your own material
python services/corpus/torrent.py serve             # background daemon: prefetch + LRU cache
# Pac's Arcade only: `python services/corpus/torrent.py seed` packs DB-1 and publishes the magnet.
```

Every shard is checked against a **signed manifest** before it touches DB-1 — poisoned "knowledge"
fails closed. Full design: [`docs/CORPUS-MESH.md`](docs/CORPUS-MESH.md). Upgrade path: set
`PA_CORPUS=en-wikipedia` for the full ~6.9M-article corpus (lots of disk + a multi-week local
embed), or `curated` for just your subjects. See
[`.claude/skills/corpus-ingest`](.claude/skills/corpus-ingest/SKILL.md).

### 6. Bring up the whole Verse

```bash
./scripts/bootstrap.sh
```

This starts, in tier order, the databases → inference → bitcoin (regtest) + Matrix → the swarm,
guardrail, state-sync, corpus, bridges → the MUD and Luanti. It health-checks as it goes.

### 7. Play

```bash
telnet localhost 4000              # the text MUD
# or point a Luanti/Minetest client at localhost:30000 for the Voxel Verse
```

Talk to the **Oracle** — it should stream a Socratic reply. Pull a lever in Luanti and watch the
same state change reflected in the MUD: that's `state-sync` keeping one world in two windows.

### 8. Earn your certificate 🎓

Once the node is healthy and you've told the wizard what you teach:

```bash
./scripts/issue-cert.sh
```

You get a **Certified Education Node** credential — self-signed by your node's own key (no central
authority), optionally published as a **nostr badge** and/or an **OP_RETURN** announce so other
Verses add you to the realm directory. Details:
[`docs/ONBOARDING-WIZARD.md`](docs/ONBOARDING-WIZARD.md) · [`.claude/skills/issue-node-cert`](.claude/skills/issue-node-cert/SKILL.md).

> That cert is for **operators**. Your **students** earn a different credential: a **soulbound
> class rune** etched to their own wallet when they complete a class (one rune per class, fees paid
> by the non-profit treasury). It's non-transferable by convention, and the issuing transaction records
> the **block time earned** and the **original wallet** — so a lost or compromised wallet never means
> losing your education: provenance proves who earned it, and the node can re-issue. See
> [`docs/RUNES.md`](docs/RUNES.md) · [`.claude/skills/class-rune`](.claude/skills/class-rune/SKILL.md).
> (You can see the whole loop today in the MUD dev mode — it etches a mock one.)

---

## The agent swarm (runtime)

An `openclaw`-managed swarm over a persistent **Blackboard** (DB-2), not context windows alone:

| Agent | Role |
|-------|------|
| **Oracle** | Socratic interviewer (brain = the `pacbot` educator); assesses mastery, awards competency |
| **Architect** | Generates Training Dungeon rooms targeting each player's knowledge gaps |
| **Custodian** | Manages seed-phrase loot via Shamir's Secret Sharing — **regtest-only** until sign-off |
| **Archivist** | Corpus, pgvector, the torrent mesh |
| **Warden** | Runs the guardrail loop; routes quarantines to your encrypted Matrix admin room |

Personas live in [`services/orchestrator/agents/`](services/orchestrator/).

## Bitcoin & safety — read before you flip anything

The seed-phrase-as-loot reward handles **real money**, so it ships locked down:

- **Regtest is the default.** Testnet is opt-in. **Mainnet is gated** behind an explicit ack
  *and* a passing `security-auditor` review. **Class runes obey the same gate** (regtest + `ord`).
- Seed-loot is **off** by default (`PA_SEED_LOOT_ENABLED=false`).
- The full 24-word seed is **never** stored in one place (Shamir's Secret Sharing).
- Anything that awards value must pass the guardrail first (fail closed on money paths).

**Do not skip [`docs/SECURITY.md`](docs/SECURITY.md).** There's also a flagged legal question about
distributing Bitcoin rewards from a non-profit — for Pac + counsel, not for code.

---

## Building on this with Claude Code

This repo ships its own AI build crew in [`.claude/`](.claude/). From `claude` inside the repo:

- **Sub-agents** (`.claude/agents/`) — one specialist per subsystem: `state-sync-engineer`,
  `mud-engine-dev`, `luanti-modder`, `llm-orchestration-engineer`, `corpus-ingestion-engineer`,
  `guardrail-engineer`, `matrix-federation-engineer`, `bitcoin-integration-engineer`.
- **Skills** (`.claude/skills/`) — `node-wizard` (onboarding), `issue-node-cert`, `class-rune`
  (soulbound student certs), `corpus-ingest`, `hallucination-guardrail`, `seed-loot-forge`, and
  `pacbot` (the bitcoin/nostr educator).

Each agent knows its tier and its guardrails, so work stays inside the latency and safety contracts.

## Federating with other Verses

Point your Matrix homeserver at another operator's, and let OP_RETURN discovery populate your realm
directory. Federation is COLD-tier — it enriches community without ever slowing your local game.
See [`.claude/agents/matrix-federation-engineer.md`](.claude/agents/matrix-federation-engineer.md).

## Troubleshooting

| Symptom | Look at |
|---------|---------|
| GPU not seen in containers | re-run `nvidia-ctk cdi generate`, then test with the `nvidia-smi` container above |
| A service won't go healthy | `podman compose -f infra/compose.yaml logs <service>` |
| Oracle replies are empty/slow | confirm `PA_GEN_MODEL` is pulled; check the inference container; try `vllm` under load |
| Corpus queries return nothing | did step 5 finish? check DB-1 row count; or join the torrent mesh |
| "Refusing: mainnet not acked" | intended — read `docs/SECURITY.md` |

---

## License & contributing

**AGPL-3.0-or-later** — network copyleft keeps every fork community-owned (see [`LICENSE`](LICENSE)).
Pac's Arcade is a non-profit; this engine is meant to be forked and run by frens everywhere. 💜
Coordinate changes via the cross-agent protocol in `.claude/rules/`.
