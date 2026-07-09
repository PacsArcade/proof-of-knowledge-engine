# POKE Academy — ITIL 4 Foundation (Fleet Ops v2) 🎓

> **Status:** first **collision-free slice built + validated** on branch `feat/academy-itil4`
> (off `main` @ `68900df`), author `pac@pacsarcade.org` — **unmerged** (merge on Pac's go).
> **Parent plan:** `docs/FLEET-OPS.md` §5 (Course framework) + §8 v2. This doc is the Academy's
> own recall token; read it with FLEET-OPS.md §5 for the legal flags.

The Academy turns "study the craft of running a node" into the same play loop as everything else in
the engine: **study → Socratic trial → boss practice-exam → a soulbound class rune.** ITIL 4 is the
first course because **the Duty Roster already speaks ITIL** — its ticket kinds *are* ITIL objects, so
the course you take and the missions you run reinforce each other.

---

## ⚠️ Licensing & honesty (read before publishing anything)

This is the same "flag for counsel" pattern as miner rewards. **Locked stance (FLEET-OPS.md §5):**

- **ITIL® is a PeopleCert/AXELOS trademark.** We teach **ITIL 4 concepts in our own original words**;
  we do **not** reproduce copyrighted syllabus objectives or exam questions, and we do **not** grant
  or imply any **official certification**. Every rune/title here is marked **"unofficial"**.
- **ITIL 4 is the current official framework. There is no official "ITIL 5" certification.** Pac holds
  third-party guides *titled* "ITIL 5 Foundation" (staged only in pacBOT's reference shelf — **not
  touched by this work**). Use them as background study material, never as a version claim.
- Our credential is a **practice/understanding badge** ("you demonstrated you get it"), not a
  PeopleCert pass. The rune titles say so.
- Runes here are **regtest/demo** (`PA_DEMO_MODE` on) and **etch fees are paid by the non-profit
  Treasury** — students never pay (class-rune skill default).

---

## The thesis — the course and the roster are the same objects

The Duty Roster ticket kinds are already ITIL (`world_store.py` `_TICKET_PREFIX`):

| Roster kind | ITIL object | Academy lesson |
|---|---|---|
| `incident` (INC) | **Incident** — unplanned interruption to a service | L5 · restore vs. root-cause |
| `problem` (PRB) | **Problem** — a cause of one or more incidents | L5 · problem management |
| `change` (CHG) | **Change** — add/modify/remove that could affect services | L5 · change enablement |
| `request` (REQ) | **Service request** — a normal, low-risk ask | L5 · request fulfilment |

So a fren who passes the ITIL practices lesson has literally learned to read the board they'll work.
The long-term loop (deferred wiring, below): passing a lesson can **raise a practice ticket** onto the
Duty Roster, and resolving real tickets earns the commendations that drive rank — two ladders, one
world.

---

## Built + validated in this slice (data-only, zero engine changes)

All in the **clean** `services/mud/verses/pacsarcade/verse.json` — it reuses the existing generic
trial/boss engine (`trial_open`/`trial_judge`/`boss_open`/`boss_judge` → `etch_class_rune`), so **no
`server.py` edit was needed**. Two new rooms, two new NPCs:

- **The Service Academy** (`academy`, west of the entrance) — **the Instructor** (`kind: socratic`).
  Trial: *"server's down, you need it back NOW vs. finding out WHY later — what's the 'restore now'
  ticket?"* → **`incident`** → rune **`PACS•ITIL•SERVICEOPS`** "Service Ops: Incident vs Problem
  (ITIL 4, unofficial)", +100 xp.
- **The Examination Hall** (`exam_hall`, north of the Academy) — **the Foundation Exam**
  (`kind: boss`, a practice exam). Riddle: *the first ITIL 4 guiding principle* → **`focus on value`**
  → rune **`PACS•ITIL•FOUNDATION`** "Service Management Foundation (ITIL 4, unofficial — POKE)",
  +150 xp.

**End-to-end validation (2026-07-08):** drove the live MUD over TCP as a fresh player —
`west → talk instructor → answer incident` etched `PACS•ITIL•SERVICEOPS` (+100 xp); `north →
challenge → answer value` → "the Examiner nods and stamps your record" (+150 xp); status bar showed
**🎓 2** runes and the player advanced **Fren → Student**. Anti-farm reward-once and the "already hold
this" path both fire. Harness: `scratchpad/play_academy.py`.

---

## The ITIL 4 Foundation ladder (design — target curriculum)

Original framing; each lesson = one Socratic trial NPC (or a boss for the capstone). Starter question
bank below is authored and accurate; expand on Pac's go. Runes proposed as `PACS•ITIL•<CODE>`.

| Lvl | Code | Lesson | Core concept (taught in our words) | Starter trial answer-key |
|---|---|---|---|---|
| 1 | `ITIL•VALUE` | What a service *is* | Value is **co-created**; a service enables outcomes without the customer owning the costs/risks | `co-creation` / `value` |
| 2 | `ITIL•DIMENSIONS` | The Four Dimensions | Orgs&people · info&tech · partners&suppliers · value streams&processes — miss one and the service wobbles | `four dimensions` |
| 3 | `ITIL•PRINCIPLES` | The 7 Guiding Principles | focus on value · start where you are · progress iteratively w/ feedback · collaborate & promote visibility · think & work holistically · keep it simple & practical · optimize & automate | `focus on value` (**shipped as the exam boss**) |
| 4 | `ITIL•SVS` | Service Value System & Chain | Demand → **value chain** (plan·improve·engage·design&transition·obtain/build·deliver&support) → value | `service value chain` |
| 5 | `ITIL•SERVICEOPS` | Incident · Problem · Change · Request | The Duty Roster practices — restore vs. root-cause vs. controlled change vs. routine ask | `incident` (**shipped as the Instructor**) |
| ★ | `ITIL•FOUNDATION` | **Practice Exam (boss)** | mixed-topic understanding check; reward-once | multi-key (**shipped: guiding-principle question**) |

*This slice ships L5 (Instructor) + the ★ capstone (Exam boss). L1–L4 are authored as design above and
drop straight into `verse.json` as more `socratic` NPCs when we expand.*

### Starter question bank (authored, ready to wire)
- **L1 Value:** "ITIL 4 says a service doesn't just *deliver* value — it does something subtler *with*
  the person using it. Value is co-_____ between provider and consumer. Finish the word." → `created`.
- **L2 Four Dimensions:** "Name the dimension that covers the *people and structures* who deliver a
  service — not the tech, not the suppliers, not the workflows." → `organizations and people`.
- **L4 Value Chain:** "The value chain has an activity for keeping a live service *running and
  supported* day to day. Name that activity." → `deliver and support`.
- **L5 Problem (companion to the shipped Incident trial):** "You've restored the service, but it keeps
  breaking. ITIL has a separate ticket for hunting the *underlying cause*. Name it." → `problem`.

---

## Mechanics → engine mapping (what to reuse)

- **Socratic lesson** → an NPC with `kind:"socratic"` + `trial:{question,keys,class,xp,pass_line,
  already,retry}`. Substring key-match; `class.class_id` unique; reward-once via `has_certificate`.
- **Practice exam** → an NPC with `kind:"boss"` (+ `energy_win/miss`, `fail_hint`, `victory_line`,
  `already_lines`, optional `anim`/`defeat_anim`). Same reward path.
- **Completion → rune** → `etch_class_rune(player, class, xp)` (`server.py:846`) → `record_competency`
  (0.9) + `etch_certificate` (idempotent, soulbound). Demo-mode mocks the chain; the real path is
  `runes.py`/Postgres.
- **Gating** ("understanding-gated" in the console) = a module row whose `access` isn't `OPEN`; the
  real gate is passing the trial that guards it. A course rune can later **gate an ops role**.

---

## Deferred wiring (next — needs `server.py`; do when the tree is clean)

1. **Console Training-Modules rows** — add the ITIL ladder to `_MODULES` (`server.py:2803`) so the
   panel lists the track with cert-rune + access. (Reconcile rune naming — see open decisions.)
2. **Completion → Duty Roster hook** — in `trial_judge`/`etch_class_rune`, on a passed L5 lesson call
   `STORE.raise_ticket("change"/"incident", …, source="academy", dedup_key=f"itil:{class_id}:{player}")`
   so the Academy feeds the roster (the two-ladders loop). Idempotent target; greenfield seam.
3. **Richer practice exam** — the engine is one-question-per-NPC; a real multi-question exam needs a
   small Academy engine (question rotation / N-of-M pass) or a chain of boss questions.
4. **Wire `POST /modules`** (the Architect stub, `server.py:1628`) if we want console-authored modules
   rather than data-pack-authored.

---

## Open decisions (for Pac)

1. **Home verse.** This slice lives in `pacsarcade` (the clean demo verse). Long-term the Academy may
   belong in `frens-hub` (the ops/rank verse) or its own verse. Where should it live?
2. **Rune naming.** Three conventions exist: `_MODULES` uses `PACS•ARCADE•<CODE>`, class-rune uses
   `PACS•<CLASS>`, this uses `PACS•ITIL•<CODE>`. Pick one for the ITIL track (runes are ~permanent).
3. **Content depth now.** Expand to the full L1–L4 trials this pass, or hold at the validated L5 +
   capstone slice and expand on your go?

---

## Play / replay it

```
# dev/regtest/SQLite — from services/mud, on free ports:
PA_MUD_DATA_DIR=/tmp/acad PA_ADMIN_TOKEN=fleetdemo PA_BLOCK_HEIGHT=897432 \
PA_MUD_PORT=4993 PA_MUD_ADMIN_PORT=4994 PA_MUD_WS_PORT=4995 python server.py
# then telnet 127.0.0.1:4993 and:  west · talk instructor · answer incident · north · challenge · answer value
```
Automated harness: `scratchpad/play_academy.py <freshname>` (skips the attract intro, plays both
trials, prints a signals summary). **ASCII-only** in any curl seed bodies on Windows Git Bash.
