# POKE Fleet Ops — the collective-admin game loop 🖖⛓️

> **Status:** APPROVED by Pac — building **v1** on branch `feat/fleet-ops`.
> **This file is the recall token:** any agent can read it cold and pick the work up (§0).
> **Concept mock:** LCARS bridge (published artifact — "POKE Fleet Ops · United Federation of Verses").
> **Owner:** Pac (founder). Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.

This turns real server-admin work into a Starfleet-style rank climb — **proof of work, not
proof of play** — so that hosting a node, running a class, and keeping the canon honest are *the game*.

---

## 0. Recall / dispatch protocol (how an agent picks this up)

1. This file is the source of truth — read it cold, then check the AutoClaw mailbox for `fleet-ops`.
2. Work lands on a **feature branch** (`feat/fleet-ops`), author `pac@pacsarcade.org`; **merge to main
   only on Pac's explicit go**.
3. **Coordinate via AutoClaw mailbox** — broadcast a `task_claim` to `shared/`, and do **not**
   branch-switch in a repo another agent holds (shared-checkout hazard). Never `reset --hard` there.
4. **pacBOT is a hard boundary:** another agent owns pacBOT personality/anti-bot. This build only
   defines the *seam* it plugs into (§7). Touch no pacBOT files.

---

## 1. Lore (all tweakable)

- **United Federation of Verses (UFV)** — Roddenberry's Federation, but each ship is a POKE node.
  Every verse has a **registry** (its `NCC-…` is the node's short pubkey).
- **Ranks** = the existing `frens-hub` ladder: **Ensign → Lieutenant → Lt. Commander → Commander →
  Captain → Commodore → Server Admiral** (already a `verse.json` `ranks` section).
- **Stardate** = the current **block height** (already in the console top bar — relabel + format).
- Tickets are **away missions**; the bans/complaints board is the **Tribunal** (Starfleet JAG);
  doc/content review is the **Peer-Review Board**; knowledge integrity is **canon**.

---

## 2. It already exists (~70% substrate)

| Need | Reuse |
|---|---|
| Rank ladder | `frens-hub` Ensign→Server Admiral (`verse.json` ranks) |
| Stardate | block height in console top bar (ROADMAP round 3) |
| Docs to review | `hallucination-guardrail` → operator review queue |
| Verify knowledge / safeguard canon | `/knowledge/flag` + guardrail |
| Complaints / bans | `/mute` `/timeout` `/kick` `/block` `/players/<name>/history` |
| Host/class incentives | `issue-node-cert` (operators) + class **runes** (students) |
| Theme swap | `DESIGN-CONSOLE.md` — retheme via `:root` CSS vars only |
| Officer bots plug | `BOT-EXTENSION.md` — off-by-default, owner-owned toggle, evented |

**New = the game loop that binds them.**

---

## 3. The six pillars (deliverables)

1. **Duty Roster** — one ticket queue aggregating existing feeds into ITIL-shaped tickets
   (`incident · problem · change · request`, plus `anomaly · tribunal · peer-review`). Claim →
   work → resolve → **evented to the owner log** (attributable, like every other admin action).
2. **Commendations** — a *second* currency beside runes. Runes = what you **learned** (soulbound).
   Commendations = **service done** (the proof of work). Both count; stay distinct.
3. **Review Boards** — promotion = point threshold **+ board sign-off** (a peer + one senior rank
   vouch). Earned *and* witnessed. Rubber-stamps earn nothing; seniors **spot-audit** (safeguards
   group knowledge). Anti-farming mirrors the MUD's existing reward-once rule.
4. **Leaderboards + Stardate** — per-verse and federation-wide commendation boards; stardate = block
   height.
5. **Fun Budget** — a Treasury line item that funds reward payouts (sats tips / etch fees /
   cosmetics), rendered as a live gauge. The non-profit literally funds the fun.
6. **Officer bots** — the bridge crew, each a proof-of-work station (§7).

---

## 4. Data + rails (home: knowledge-engine)

- **Store:** extend `gamestate` (DB-2) — `tickets`, `ticket_events`, `commendations`,
  `rank_state`, `board_votes`. Keep read models cheap for the console poll.
- **New endpoints (admin port 4001, same auth + eventing + `X-POKE-Bot` honesty as existing rails):**
  `GET /fleet` (combined snapshot) · `GET /roster` · `POST /roster/<id>/claim` ·
  `POST /roster/<id>/resolve {disposition}` · `POST /roster/<id>/vouch` · `GET /ranks` ·
  `GET /leaderboard` · `GET /budget` · `POST /budget` · `POST /engineer/audit`.
- **Ingest adapters** feed the roster from what already emits: `/knowledge/flag` (→ peer-review),
  `/system/history` thresholds (→ incident), Chief Engineer audits (→ incident/anomaly); later
  guardrail failures, moderation history, Architect drafts, node-cert requests.
- **Console UI:** new **Fleet Ops** rail in `services/mud/admin.html`, themed via the existing
  `:root` seam (LCARS as a selectable theme). Read-view mirror in `pacsarcade-org` `/console` later.

---

## 5. Course framework (Academy)

- **Track ladder:** CompTIA **A+ → Network+ → Security+ → (Linux+/CySA+ …)**, with **ITIL 4** as
  the service-management capstone. ITIL objects (incident/problem/change) *are* the Duty Roster —
  tightest synergy, so **author ITIL 4 Foundation first**.
- **Mechanics:** study guides → Socratic trials; practice tests → boss **practice-exam mode**
  (reuse anti-farm reward-once); completion → a **class rune** (existing `class-rune` skill).
- **Two ladders meet:** a course rune can *gate* an ops role; ops commendations drive the rank.

### ⚠️ Honesty + licensing flags (for Pac + counsel)
- **On "ITIL 5":** Pac holds third-party study guides *titled* "ITIL 5 Foundation" (the pacBOT
  agent already loaded them into pacBOT's reference shelf, with provenance caveats). Use them as
  study material — but be precise in what **we** publish: PeopleCert/AXELOS's current official
  framework is **ITIL 4**, and there is **no official "ITIL 5" certification**. Adopt ITIL 4 as the
  federated standard + author our own **"POKE-ITIL" AI/federation supplement**; treat the "ITIL 5"
  guides as one (clearly-labeled, unofficial) source, never as an official version claim.
- **ITIL is a PeopleCert/AXELOS trademark.** We may *reference/fork community study repos for
  internal learning scaffolding* and author original content, but **cannot redistribute official
  copyrighted objectives or imply we grant official certification.** Same "flag for counsel"
  pattern as miner rewards.
- The three linked repos are ITIL **v4** materials — fork into an internal study reference only,
  clearly attributed, not shipped as our curriculum verbatim.
- **"Ship's Counsel" is not a lawyer.** A compliance-advisor bot can research primary sources
  (money-transmission, the **Howey** test for runes/tokens, non-profit rules, data-privacy law)
  and draft a memo — but it holds **no license, no privilege**, and its output is *research to
  hand to real counsel*, not legal advice. Same flag-for-counsel pattern as miner rewards + ITIL.
- **On "use what's written to vanish" — the lawful reading.** Counsel's job is **lawful
  minimization**: privacy-by-design, data minimization, non-profit exemptions, self-custody
  legality, jurisdiction — using rights that *are written* to keep the footprint small and the
  org clean. The line it will not cross: it helps us stay **lawful and private**, it will not help
  evade a lawful obligation or conceal wrongdoing. "Here to rebuild" = build the clean thing right.

---

## 6. Theming (LCARS + per-verse)

- LCARS ships as one selectable theme; the seam is the `DESIGN-CONSOLE.md` `:root` token block —
  **retheme by overriding tokens, never markup.** Per-verse theme = a token set on a wrapper attr.
- **Sound:** synthesize LCARS chirps with WebAudio (no assets, offline-first); user-gesture gated;
  a sound on/off toggle; respect `prefers-reduced-motion`.
- Keep the offline-first, single-file, no-CDN rule for `admin.html`.

---

## 7. The Crew — officer bots (extension seam)

Fleet Ops isn't just a ticket queue; it's a **bridge crew** of AI officers, each a station.
Every officer is an **ops-bot extension** under `BOT-EXTENSION.md`: registered in
`extensions.json`, **off by default**, owner-owned toggle, every action **evented** and
attributable. Officers raise tickets onto the Duty Roster and report to the owner — they never
act outside the rails table. Bots can *earn* commendations (a bot that catches a real incident
gets logged) but **cannot vote on review boards** — promotion stays human.

| Seat (Starfleet) | Call sign | Does | Reuses |
|---|---|---|---|
| **Security** | `pacbot` | proof-of-humanity / anti-bot; verify a fren is real | seam only (owned by other agent) |
| **Chief Engineer** | `poke-engineer` | node-health audits, trend/anomaly flags, infra recommendations | `/health` `/stats` `/system/history` `/nodes` `/events` |
| **Ship's Counsel (JAG)** | `poke-counsel` | compliance & rights advisor; reviews what we ship for legal footing | Tribunal pillar; read-only + advisory |

- **pacBOT (Security) seam:** `verify_human(player, signal) -> {verdict, confidence}` + a roster
  hook (a suspicious-activity signal can raise a ticket). **Implement nothing here** — the other
  agent's personality + anti-bot logic fills it in and merges cleanly. Touch no pacBOT files.
- **Chief Engineer:** see §10 — the "don't trust, verify" auditor. Implemented in v1 (it is *not*
  pacBOT-owned), so the fleet has one working officer from day one.
- **Ship's Counsel:** advisory only — see the legal flags in §5. Never auto-acts; drafts a memo
  onto the Tribunal / Peer-Review board for a human to weigh. Seam in v3.

---

## 8. Phased slices

- **v1 (this slice):** Duty Roster + commendations + rank/board model + LCARS theme in `admin.html`,
  fed by real ingest adapters (`/knowledge/flag`, `/system/history`, Chief Engineer). **Chief
  Engineer (`poke-engineer`)** ships as the first working officer. Regtest/dev only.
- **v2:** Academy — ITIL 4 Foundation track (trials + practice-exam boss + rune on completion);
  Chief Engineer scheduled audits go from manual to timer-driven.
- **v3:** federation leaderboards, Fun Budget disbursement wiring, org `/console` read-view;
  **Ship's Counsel** advisory memos wired to the Tribunal board.
- **Later:** pacBOT behavior drops into the §7 seam; ordinals for one-of-a-kind trophies (Epic 3).

---

## 9. Decisions (LOCKED for v1)

1. Home of record: **knowledge-engine console** (`admin.html`); org web read-view later. ✅
2. First course: **ITIL 4 Foundation** (v2). ✅
3. pacBOT: **seam only** — no pacBOT files touched. ✅
4. First working officer: **Chief Engineer in v1** (`poke-engineer`). ✅
5. Infra note: a **second VPS + a backup of Pac's own server**, plus **2 physical servers** Pac
   owns, need a **hosting location** (Pac is mobile / in an RV) — colo or a fixed site. This is
   exactly the class of call **Chief Engineer** exists to inform. Tracked for the infra plan.

---

## 10. Chief Engineer — scheduled audits ("don't trust, verify") 🛠️

The Bitcoin maxim as an ops principle: the auditor **recomputes from raw signal** instead of
trusting a reported status field. If `/stats` says "healthy," Engineer re-derives health from
`/system/history`, `/events`, `/nodes`, and (where wired) the block tip — and flags the gap.

- **What it audits:** CPU/mem/net trend vs. the ZAP **550% cap** (sustained exceedance locks the
  box 1h), event feed for repeated `warn`/`error`, knowledge-swarm shard/manifest verification,
  block-tip staleness, QA-flag backlog.
- **Cadence:** on-demand `POST /engineer/audit` now; scheduled (nightly deep + hourly light) via a
  **systemd timer or platform Cron** in prod. Each run posts an **audit report** event and opens
  roster tickets for anything red — attributable and evented, same as any officer.
- **Output = infra input:** each audit ends with a short **recommendation** ("mem trending toward
  cap — cap AMP servers or add swap"), never an auto-mutation. Owner decides.
- **Trends over snapshots:** rolling window so it reports *direction*, not just a number.
- **Read-only + regtest by default.** No `/reboot` `/shutdown` without explicit owner confirm.

---

## 11. Implementation notes (v1 as built) — READ THIS FIRST if you're picking up

Branch **`feat/fleet-ops`** (off `main`), author `pac@pacsarcade.org`, **not merged** (merge on Pac's go).

### Commits (in order)
1. `docs(fleet-ops): land the Fleet Ops recall token` — this file.
2. `feat(fleet-ops): Duty Roster persistence in world_store` — `services/common/world_store.py`.
3. `feat(fleet-ops): server rails, ingest adapters, Chief Engineer` — `services/mud/server.py`.
4. `feat(fleet-ops): console Fleet Ops rail + LCARS theme` — `services/mud/admin.html`.

### What's built + verified
- **Store** (`services/common/world_store.py`): Fleet Ops tables + methods on `SqliteWorldStore`;
  symmetric `NotImplementedError` stubs on `PostgresWorldStore`. **Unit-smoke-tested green.**
- **Server** (`services/mud/server.py`): ladder + standings + promotion, the §4 rails, ingest
  (`/knowledge/flag` → Peer-Review), and `chief_engineer_audit()`. `poke-engineer` + `poke-counsel`
  registered in `_EXT_DEFAULTS` (off by default). **Exercised end-to-end over HTTP — all green**
  (claim→resolve→commendation, vouch, bot-vouch 403, self/double-vouch 409, audit, budget, snapshot).
- **Console** (`services/mud/admin.html`): FLEET OPS panel (Duty Roster, Rank Track, Commendations,
  Fun Budget gauge, stardate), header **LCARS**/ARCADE theme chips + **SOUND** (WebAudio, synthesized),
  per-verse theming via `data-verse`. ⚠️ **NOT yet browser-validated** — Pac couldn't reach the demo
  (localhost-only). Loads/serves fine; needs one human (or headless) click-through to confirm the JS
  renders. Risk is low (plain string-concat JS, reuses the existing `apiGet/apiPost/refresh` seam).

### Run / test the node (dev, regtest, SQLite)
```bash
cd services/mud
PA_MUD_DATA_DIR=/tmp/fleet PA_ADMIN_TOKEN=fleetdemo PA_BLOCK_HEIGHT=897432 \
PA_MUD_PORT=4880 PA_MUD_ADMIN_PORT=4881 PA_MUD_WS_PORT=4882 python server.py
# console: http://127.0.0.1:4881/  (gate token: fleetdemo)
# ports 4000-4002 (and 4100-4102) are often already taken by other nodes — pick free ones.
# reachability: binds 127.0.0.1 by default. For LAN/remote access set PA_MUD_ADMIN_HOST=0.0.0.0
# (token-gated, but that's an outward-facing exposure — get Pac's OK first).
```
Seed a demo roster by POSTing (admin token header `X-POKE-Admin-Token: fleetdemo`) to
`/knowledge/flag`, `/roster`, `/roster/<id>/claim|resolve|vouch`, `/commend`, `/budget`,
`/engineer/audit`. ⚠️ Use **ASCII only** in curl bodies on Windows Git Bash — em-dashes get mangled
to invalid UTF-8 and the server falls back to defaults (a shell artifact, not a bug).

### Next (v2/v3 — see §8)
Browser-validate the console → org `/console` read-view → Academy (ITIL 4 Foundation; the pacBOT
agent already staged "ITIL 5 Foundation" study guides in pacBOT's reference shelf) → Fun Budget
disbursement → Ship's Counsel memos → pacBOT proof-of-humanity into the §7 seam.
