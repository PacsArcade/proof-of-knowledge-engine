# ROADMAP — the next heavy lift 🚀

Captured from Pac's play-test feedback. This round landed the polish + a roadmap; the epics below
are the next features. Grouped so we can pick a coherent slice at a time.

---

## Landed this round (polish)
- Banner: named the game **POKEMUD**, "presents" on its own line, clearer `help`/`quit` line,
  and a **login glimmer** (the title shimmers through colors on connect).
- Exit message → "POKEMUD is going offline. GG's, fren."
- **Border-break fixed** — removed double-width emoji from inside the framed body (that was the
  broken border at the award ceremony).
- **Boss now moves** — the Wraith flickers position/face across frames; animations slowed (~1.1s
  a frame) so you can actually watch them.
- **Down/up doors render** — up/down markers on the frame border + a text `Exits:` line.
- **Backup no longer clutters Bitcoin** — it's a signed **nostr** attestation now (see Epic 3).
- `mud-engine-dev` agent got a **rendering QA checklist** (no in-frame double-width glyphs, every
  exit shown, border-length invariants, legible animation pacing, narrow-width test).

---

## Epic 1 — Identity: nostr sign-in, name@space, pairing, verification
- **Nostr admin sign-in.** pacsarcade-org has a new nostr sign-in module — reuse it. The console
  **token is for first setup only**; once an admin links their nostr key we verify *them* (NIP-07
  / signed challenge) and encourage syncing nostr. Console shows: "token = bootstrap; sync nostr
  for real auth." *(Touches: MUD rails auth, admin.html, a shared nostr-verify helper.)*
- **name → user@space.** After a player links, their display handle becomes `user@space`
  (e.g. `pac@frens`, `pac@pacsarcade`). Same for self-hosting admins. The prompt/who/say/profile
  all use it. *(Small: a `display_handle(p)` helper + which space they linked.)*
- **Pairing code everywhere.** The in-MUD `link fren` code should be documented + consumable on
  the **frens.earth** repo and the **pacsarcade-org** repo, and linkable through the pacsarcade
  profile. Split of concerns: **frens = basic profile/identity**; **games + education = the
  arcade**. The arcade handle should surface in the **social/extra fields of the nostr profile**.
- **Rune verification UX.** Walk the player through *verifying* their rune (show the etch tx / ord
  lookup), not just earning it.

## Epic 2 — Learning: the Interview Bot + instructor analytics
- **Profile as a conversation.** When a new player does `profile` (or on first join), the Interview
  Bot (LLM) has a real conversation about **what they want to learn**, and stores it. Feeds the
  Architect's room/lesson generation. *(Uses the existing tiny-context + player_memory plumbing.)*
- **Server-side learner profiles for instructors.** Track where players **get stuck** (repeated
  wrong answers, long dwell, giving up) → is the material too hard? Surface this as a **task for the
  class-instructor bot** to review with the content owner. This is the "improve the class" loop.
  *(New: per-lesson difficulty signals in DB-2 → a review queue the instructor persona works.)*
- **Cross-verse memory (the "pokenetwork").** A player's memories/progress replicate across verses
  tied to the pokenetwork, so the arcade remembers you wherever you roam. *(Big: a sync protocol —
  likely nostr events + the corpus/relay mesh; privacy + conflict rules needed.)*

## Epic 3 — Bitcoin: runes, ordinals, spaces, backup
- **Ordinals.** *Answer: yes — the design covers both* (`docs/RUNES.md`: we **etch** runes and
  **inscribe** ordinals). Today the game shows **runes** (fungible-ish, one per class). Ordinals
  (unique inscriptions) are a natural fit for a **one-of-a-kind** credential/trophy — decide which
  achievements are runes vs. inscribed ordinals, and show both in the admin panel.
- **Spaces protocol + timing.** pacsarcade-org bakes in **spaces** Bitcoin names and does a **block
  inscription every 6789 blocks**. Options: (a) **batch** rune etches / backup anchors to ride that
  same cadence (one tx for many — the anti-clutter win), or (b) **walk the user through** doing
  their own etch/inscription and then **verifying** it. Likely both: batched by default, guided for
  the curious.
- **Backup (done this round, more to do).** Backup is now a **nostr** attestation — no per-player
  Bitcoin clutter. Runes are already on-chain (etched). Next: implement the **optional batched
  Merkle anchor** (one periodic tx committing many players' hashes, timed to the space cadence) and
  the real nostr publish via `bitcoin-bridge`/a nostr signer.

## Epic 4 — Operator console
- **Histograph.** A rolling **last-~60s** graph of CPU/memory (and maybe players/swarm) in the
  dashboard — sample on the 5s poll into a ring buffer, draw a sparkline/bar history. *(admin.html
  keeps a client-side ring buffer; optionally a `/system/history` endpoint.)*
- **Hosting space.** Show **what space this node hosts at** (`PA_SPACE`, e.g. `@pacsarcade`) in the
  console + node widget + startup. *(Small: new env + surface it.)*
- **Ordinals/runes in the panel.** We already show "runes etched this session"; add ordinals +
  per-class breakdown once Epic 3 lands.

## Epic 5 — Reach: the "togo" edition + magical branding
- **Small screens / cyberdecks.** A **togo version** for phones, Raspberry Pi, and the cyberdeck
  builds — a study buddy on the go. Make the board width responsive (`PA_MUD_WIDTH`), wrap all
  content (including the help + HUD) to it, and offer a compact layout under ~50 cols.
- **Magical banner art.** Pull the **pacsarcade.org branding** and craft richer ASCII art for the
  login (the glimmer is a start). Generate frames with `chafa`/`ffmpeg` (see `services/mud/art/`).

---

## Direct answers to your questions
- **"Did this stack include ordinals?"** Yes in the design (etch runes / inscribe ordinals). The
  game currently issues **runes**; ordinals are Epic 3 — great for unique trophies.
- **"What does backup anchor on chain? Are we cluttering Bitcoin?"** It *was* heading toward a
  per-player OP_RETURN (would clutter). Fixed this round: backup is a **nostr event**; the runes
  are already on-chain; only an **optional batched anchor** ever touches Bitcoin, timed to the
  spaces cadence — one tx for many, never one per player.
- **"No down arrow to the boss."** Fixed — up/down now render on the frame + an `Exits:` line, and
  the game-dev agent now checks for this class of bug.
- **"Boss wasn't moving / animation too fast / border broke."** Fixed — the Wraith animates,
  frames are paced to read, and no in-frame double-width glyphs (which caused the border break).
