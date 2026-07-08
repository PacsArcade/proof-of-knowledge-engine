# Verse Guide — imagine, build, and dock a verse 🌌💜

> Part of **Pac's Arcade — Proof of Knowledge Engine (P.O.K.E.)**.
> A **verse** is the world a pokenode hosts. Pac's Arcade runs the bitcoin-education
> verse; frens.earth runs the starship hub (`frens-hub`) where every fren boards as an
> **Ensign** and climbs toward **Server Admiral**; Degen Wonderland will run a
> story-verse of its own. Same engine, different worlds — a verse is *data*.

## What's in a verse pack

```
services/mud/verses/<id>/verse.json
```

| Section | What it defines |
|---|---|
| `id`, `name`, `tagline` | identity — the banner, HUD and console all follow it |
| `rooms` | title, description, exits (north/south/east/west/up/down), NPCs, ASCII art |
| `npcs` | every NPC: `kind` (`socratic` teacher / `boss`), `persona` (its AI system prompt), scripted `trial` or riddle, fallback lines |
| `ranks` | level → title ladder (frens-hub: Ensign → … → Server Admiral) |
| `home` | the default name + description for players' own rooms |
| `strings` | welcome / goodnight / can't-go lines, in your verse's voice |
| `gallery` | art pieces on display — ASCII always; add `media: {kind, url}` and web clients render the real image or video (owner toggle: `art ascii|media`) |

NPCs are **run by the node's local AI**: the `persona` is the system prompt, the engine
feeds it the player's recent memory from DB-2 so your characters *remember frens*.
Without a local model configured, the scripted `trial`/`fallback` lines carry the scene.

## The pacBOT "imagine a verse" interview

You don't have to design alone. The intended creation flow is a conversation — pacBOT
interviews you, builds the pack with you, and sets up the server around you:

1. **Imagine** — pacBOT probes: *What story does your site tell? Who arrives, and what
   should they feel in the first ten seconds? What must a fren UNDERSTAND to say they've
   beaten it?* Theme, audience, lore, tone — your answers become `name`, `strings`,
   room descriptions.
2. **Teach** — every verse teaches something real. pacBOT helps you pick the knowledge
   spine (bitcoin is the default at Pac's Arcade; DW adds its story on top) and turns it
   into Socratic trials and boss riddles — questions, accepted keys, rune names.
3. **Iterate** — pacBOT drafts rooms/NPCs, you react ("darker", "more Alice", "the boss
   should mock you gently"), it revises. Repeat until it feels like your world.
4. **Hardware & placement** — where will the node live? Home box, VPS, the site's own
   server? pacBOT asks about CPU/RAM/disk and picks the inference backend to match —
   then hands off to the **node-wizard** skill for the actual install and bring-up.
5. **Server setup** — ports, `PA_*` env, admin token, systemd/compose — node-wizard
   territory, driven for you.
6. **Troubleshooting extension** — at the end, pacBOT registers its ops-bot extension
   for your node (off by default, your switch) so it can help you diagnose issues later.
   Contract: [`docs/BOT-EXTENSION.md`](BOT-EXTENSION.md).

*(The interview ships as a pacBOT skill extension — see ROADMAP. Until it lands, this
guide + the scaffolder cover the same ground by hand.)*

## By hand: scaffold → theme → run

```bash
# 1. scaffold a runnable starter (2 rooms, teacher, boss — search for REPLACE ME)
python services/mud/new_verse.py degen-wonderland --name "Degen Wonderland"

# 2. edit services/mud/verses/degen-wonderland/verse.json

# 3. run it
PA_VERSE=degen-wonderland python services/mud/server.py

# 4. play it — terminal or browser
python services/mud/play.py            # telnet :4000
# http://127.0.0.1:4001/play           # web client
```

Broken packs never brick a node — the loader falls back to `pacsarcade` and says why.

**Testing checklist** (what "solid" means):
- every exit walks both ways; `look` reads well in the 72-col frame
- `talk <npc>` opens the trial; wrong answers coach, right answers etch the rune
- `challenge` → boss → defeat animation → rune card
- `home`, `rename room`, `invite`/`visit`, `gallery`/`view` all feel native to your theme

## Docking your verse to the main hub

A verse alone is a room; docked, it's part of the pokenetwork:

1. **Point at the hub**: `PA_FRENS_URL=https://frens.earth` — new players get walked
   through claiming their `@fren`, so identity travels between verses.
2. **Publish your knowledge sources**: node console → **Knowledge Connections** → add
   your corpus/relay refs. Owners toggle sources on/off per node — trust is the gate.
3. **Link your front-ends**: console → **Linked Games** — the MUD is built in; a Luanti
   voxel world or any other client for the same verse registers here.
4. **Get certified**: the `issue-node-cert` skill quizzes the operator, signs a
   "Certified Education Node" credential and publishes your verse to the federated map.

## House rules for verses

- **Education first.** Every rune must be earned by demonstrated understanding — trials
  and bosses gate on *grasping* something, never on grinding or paying.
- **"fren", never "friend."** 💜 Consequences, not prohibitions.
- **Regtest by default** for anything that etches — mainnet only after audit.
- **The player's record is theirs**: runes are soulbound, provenance survives transfer,
  and `backup` anchors identity via nostr — one batched Merkle anchor, never a tx per player.
