<!--
  PLAYER GUIDE — starter template for a P.O.K.E. node.
  Copy this to your node/site and fill the {{PLACEHOLDERS}}. It's written in the Pac's Arcade
  voice: "fren" not "friend", runes are ETCHED, education over prohibition, GG's. Keep it short —
  a player should be able to read it in two minutes and start playing.
  Operator checklist is at the bottom; delete these comment blocks before you publish.
-->

# 🕹️ How to play — {{NODE_NAME}}

Welcome, fren. This is **{{NODE_NAME}}**, a learning arcade running on P.O.K.E. (Proof of Knowledge
Engine). You explore, you talk to the Oracle, you prove you understand something, and it
**etches a rune** only you can carry. The high score is understanding. 💜

## Get in

- **In a browser:** open **{{PLAY_URL — e.g. https://{{NODE_HOST}}/play}}** and name yourself.
- **In a terminal:** `telnet {{NODE_HOST}} {{PORT}}`  ·  or run the tiny client: `python services/mud/play.py {{NODE_HOST}} {{PORT}}`

That's it — no install, no account, no fees. Ever.

## The controls

| Type this | It does |
|-----------|---------|
| `look` (`l`) | look around the room |
| `north` `south` `east` `west` `up` `down` | move (n/s/e/w shortcuts work) |
| `talk oracle` · `answer <text>` · `ask oracle <q>` | talk with the Oracle — it asks, you answer |
| `challenge` | face a boss (a lesson you have to prove) |
| `stats` · `examine <name>` | your attributes · look at another fren |
| `link fren <name>` · `verify <code>` | claim your handle and bind it |
| `backup` | save your progress (a signed attestation — no clutter on Bitcoin) |
| `profile` · `certs` · `inventory` · `who` · `say <msg>` | you, your runes, your bag, who's here, chat |
| `help` · `quit` | the controls · leave (we'll say goodnight) |

**You don't have to be exact** — "sup" to the Oracle, "go down", "who's the boss" all just work.

## The Oracle & the bosses

The Oracle won't hand you answers — it trades in questions. Show it you truly understand, and it
**etches a class rune** to your wallet: on-chain, soulbound (yours, non-transferable), stamped with
the block it was earned. Bosses are lessons with teeth — beat one and the rune is yours. You only
earn a lesson's reward **once**; come back when there's something *new* to learn (no farming, fren).

## Your identity (optional)

Link your **@fren** handle with `link fren <name>` and `verify <code>` to carry your name and runes
across the pokenetwork. {{IF FRENS: this node is connected to {{FRENS_URL}}.}} Your progress is kept
between visits — we'll welcome you back and pick up where you left off.

## What you can learn here

<!-- List YOUR node's classes/areas. Example: -->
- **{{CLASS_CODE}} — {{CLASS_NAME}}** ({{AREA}} › {{TOPIC}}) → rune `{{VERSE•PREFIX•CODE}}`
- _{{add your modules — the Architect can help you organize them}}_

## House rules

Be kind. Operators can mute/timeout/kick — you'll always be told why, and your seat and progress
stay safe. Questions? {{CONTACT — e.g. say hi in {{CHAT_LINK}}}}.

GG's, and welcome to the arcade. 💜

<!--
  ───────────────────────── OPERATOR CHECKLIST (delete before publishing) ─────────────────────────
  [ ] Replace every {{PLACEHOLDER}} (node name, host, port, play URL, frens URL, classes, contact).
  [ ] Set your world/space in the console (PA_SPACE) so it shows on player profiles.
  [ ] List your real modules under "What you can learn here" (consult THE ARCHITECT to organize).
  [ ] If you host a custom login/branding, mirror it here so the guide matches the game.
  [ ] Keep the voice: fren / etched / trusted source / GG's — nothing that reads as paid.
  [ ] Two-minute read max. Cut anything a player doesn't need before their first session.
-->
