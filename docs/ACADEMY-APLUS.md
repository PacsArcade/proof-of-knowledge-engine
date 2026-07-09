# POKE Academy — CompTIA A+ Field Service 🛠️

> **Status:** built + **validated end-to-end** on branch `feat/academy-itil4`, author
> `pac@pacsarcade.org` — **unmerged** (merge on Pac's go). Home verse: **frens-hub** (the ops verse).
> **Pivot (2026-07-08):** courses are the gap → build *playable, hands-on* course content. A+ first
> (printers, PC faults, escalating tickets). The web portal/console is the **design team's** — this is
> game content only; no `admin.html` edits.

The trial engine taught concepts by Q&A. A+ needs **hands** — so this slice adds a small
**field-service layer** to the MUD: you pick up real tools and parts, `examine` a fault, `use <tool>
on <thing>` to diagnose and repair, and `escalate` what's beyond a field fix (which raises a real
Duty Roster ticket). Same "data, not code" rail as the NPC trials — scenarios live in `verse.json`.

---

## ⚠️ Licensing (unofficial — flag for counsel)

**CompTIA A+® is a CompTIA trademark.** We teach A+ *concepts* (troubleshooting method, hardware,
printers, escalation) **in our own original words**; we do **not** reproduce copyrighted objectives
or exam items, and we grant **no official certification**. Every rune title says **"unofficial"**.
Same stance as the ITIL flags in `docs/FLEET-OPS.md §5` / `docs/ACADEMY-ITIL4.md`.

---

## The field-service engine (new, reusable — `services/mud/server.py`)

Data-driven; no code per scenario. A room in a verse pack may declare:

- **`items`** — portable objects: `{id, name, aka[], desc, portable?}`. Indexed at load into
  `ITEM_INDEX`; inventory stores **ids**, renders **names**. Verbs: `take`/`get`, `drop`,
  `inventory` (i), `examine <item>`.
- **`fixtures`** — fixed things you troubleshoot: `{id, name, aka[], look, look_solved, reveals{},
  examine_grants?, uses{}, escalate?}`.
  - **`examine <fixture>`** shows `look`, plus any `reveals[flag]` lines whose flag the player has
    earned, plus a hint. `examine_grants` sets a flag (e.g. you must *see* a fault before escalating).
  - **`use <tool> on <fixture>`** looks up `uses[<item-id>]` (or `uses[""]`/`uses["hands"]` for
    bare-handed). A rule: `{needs?, needs_hint?, say, grants?, solve?, rune?, escalate?}`. `needs`
    gates on a prior flag (diagnose-before-fix); `grants` sets a progress flag; `solve` marks the
    fixture fixed and, if `rune`, etches a class rune (`etch_class_rune`).
  - **`escalate <fixture>`** (or a fixture whose `escalate` is set): raises a **Duty Roster ticket**
    via `STORE.raise_ticket(kind, title, detail, source="academy", dedup_key, verse)` and can also
    etch a rune. Teaches *know when to escalate*.

Per-player progress = **per-player feature flags** (`STORE.get/set_feature("scn:"+name, key)`), so
every crew member's broken PC is their own. Nothing in the portal; all game-side.

**Authoring a new level = pure `verse.json` data.** Add items to a room, a fixture with a `uses`
chain (diagnose → fix) and/or an `escalate` block, and a rune spec. No server code.

---

## The A+ wing (in `frens-hub`, off the shuttle bay — `west`)

A Starfleet-flavored IT shop; hard faults escalate to the Duty Roster (cf. the SCAR mockup's
"MATRIX BRIDGE DOWN · ticket SCAR-0142").

| Room | What's there |
|---|---|
| **The Repair Bay** (hub) | parts bins: magnetic screwdriver, PSU tester, spare power supply, DDR RAM, toner. The **A+ Practice Exam** boss (`challenge`). |
| **Crew Berth 7** (north) | **the crew terminal — won't POST** (Level: hardware) |
| **The Comms Closet** (south) | **the manifest-printer — jammed + low toner** (Level: printers); **the federation relay — dark, port 8448** (Level: escalation) |

### Levels (validated 2026-07-08 — a fresh crew member earned every rune)

1. **PC won't POST** → `PACS•APLUS•HARDWARE` (+120). `use screwdriver on terminal` (open) →
   `use tester on terminal` (12V rail dead → diagnose) → `use supply on terminal` (swap PSU → fix &
   verify). Reseating RAM first is a **red herring** that teaches *check power before parts*.
2. **Printer troubleshooting** → `PACS•APLUS•PRINTERS` (+120). `use printer` (bare-handed: clear the
   jam) → `use toner on printer` (order matters: path before consumable).
3. **Know when to escalate** → `PACS•APLUS•ESCALATION` (+100). `examine relay` (server-side, above a
   field tech) → `escalate relay` → **raises `INC-0001` on the Duty Roster** (source `academy`).
4. **A+ Core exam** (boss) → `PACS•APLUS•CORE` (+200). The 6-step method; the skipped step after a
   fix is **verify** full system functionality.

Runes are `PACS•APLUS•<CODE>` (Pac's naming pick), soulbound, regtest/demo (`PA_DEMO_MODE`),
Treasury-funded.

---

## Roadmap — more A+ levels (all authorable as `verse.json` data)

Next faults to add (each a fixture + a tool chain, some with escalation):
- **No display / POST beep codes** (reseat GPU, read the beep pattern) · **No network** (bad cable →
  cable tester → `ipconfig`/DHCP; escalate a switch-port fault) · **Boot failure** (bootable USB,
  boot order, `chkdsk`) · **Malware / suspicious process** (isolate → scan → escalate a breach) ·
  **Overheating** (dust, thermal paste, fan) · **Mobile / no-charge** (port, battery) · **ESD/safety**
  gate. Then a fuller multi-question A+ exam boss chain.

Later tracks (same engine): **Network+**, **Security+**, then **ITIL 4** ties the ticket workflow
together (the ITIL Academy — Instructor + Foundation Exam — already lives on the Training Deck; see
`docs/ACADEMY-ITIL4.md`).

---

## Play / replay it

```
# frens-hub verse, dev/regtest/SQLite, free ports:
PA_VERSE=frens-hub PA_MUD_DATA_DIR=/tmp/aplus PA_ADMIN_TOKEN=fleetdemo PA_BLOCK_HEIGHT=903420 \
PA_MUD_PORT=4993 PA_MUD_ADMIN_PORT=4994 PA_MUD_WS_PORT=4995 python services/mud/server.py
# telnet 127.0.0.1:4993 then:
#   west · take screwdriver · take tester · take supply · take toner
#   north · examine terminal · use screwdriver on terminal · use tester on terminal · use supply on terminal
#   south · south · use printer · use toner on printer · examine relay · escalate relay
#   north · challenge · answer verify
```
Automated harness: `scratchpad/play_aplus.py <freshname>`. The escalated ticket shows on the Duty
Roster (`GET /roster`) and thus in the portal. **ASCII-only** in curl bodies on Windows Git Bash.
