# POKE Node — Admin Portal Integration Spec (for the SCAR overhaul) 🖖

> **Audience:** the design team rebuilding the admin console (the "SCAR — Sovereign Corps Access
> Relay" LCARS portal). **Purpose:** everything the portal needs to render and drive a live POKE node,
> so the new UI drops onto the existing backend **without backend changes**. Owner: Pac.
> **State as of 2026-07-09** (`main` @ merge `7e9adef`). Companion docs: `FLEET-OPS.md` (Duty Roster),
> `ACADEMY-APLUS.md` + `ACADEMY-ITIL4.md` (courses), `DESIGN-CONSOLE.md` (theme tokens).

## 0. TL;DR for the design team

- The portal is a **thin client over one HTTP API** on the node's **admin port** (`:4001` by
  default). Everything on the SCAR mockup — the live tail, health telemetry, Duty Roster, alerts —
  is already served as JSON. **You render; the node computes.** No backend rewrite needed.
- **Auth = one header:** `X-POKE-Admin-Token: <token>`. Gate the portal on it (the current console
  stores it in `localStorage.poke_admin_token`). Bots use a *separate* `PA_BOT_TOKEN` — never the
  admin token.
- **Reskin freely:** the whole look is CSS custom properties (`--pa-*`) on `:root`. LCARS is already a
  selectable theme (override tokens, never markup). See §6.
- Two distinct surfaces on one node: the **operator portal** (this doc, admin port) and the
  **player game** (telnet + browser `/play`, game port). Keep them mentally separate.
- The reference implementation is the current single-file console `services/mud/admin.html` — it is
  the *contract in code*: every endpoint + field the portal needs is already consumed there.

---

## 1. Topology — one node, two audiences

```
                       ┌───────────────────────────── POKE node (services/mud/server.py) ─────────┐
  operators  ─────────▶│  ADMIN HTTP  :4001   (token-gated JSON API)   ← THE PORTAL TALKS TO THIS  │
  (SCAR portal)        │     GET snapshots · POST actions · SSE-less 2–5s poll                     │
                       │                                                                           │
  players    ─────────▶│  GAME  telnet :4000   ·   browser WS bridge :4002  (via /play)            │
  (frens.earth)        │     rooms · trials · items · runes · Duty Roster escalations              │
                       └────────────────────────────────────────────────────────────────────────-─┘
  store: SqliteWorldStore (dev) / PostgresWorldStore (prod, DB-2 "gamestate")
  ports: PA_MUD_PORT=4000 · PA_MUD_ADMIN_PORT=4001 · PA_MUD_WS_PORT=4002  (defaults; pick free ones)
```

The portal only ever touches the **admin HTTP** surface. The game surface is players' business; the
portal *observes* it (who's online, events, the roster) and *acts on it* (moderation, budget, audits).

---

## 2. Auth & polling model

- **Header:** every admin call carries `X-POKE-Admin-Token: <token>`. Missing/wrong → `401`
  (the console clears its token and re-shows the gate). There's a per-IP failed-auth rate-limit, and
  the node **refuses to serve admin on a non-loopback host unless `PA_ADMIN_TOKEN` is explicitly
  set** (security hardening F1/F3). So the portal must have the operator paste/hold the token.
- **Principal:** admin token → `human`; a distinct `PA_BOT_TOKEN` → `bot`. Human-only actions (e.g.
  vouching a promotion) reject bot principals. The portal is always a `human` caller.
- **No websockets/SSE on admin** — the current console **polls**: a heavy snapshot every ~5s and the
  event tail every ~2s. The portal can keep that cadence or tune it. All GETs are cheap read-models.
- **Public (unauthed) GETs:** `/config` (how a browser reaches the game) and `/u/<handle>` (a fren's
  public profile). Everything else is token-gated.

---

## 3. The API contract (what the portal renders/drives)

Base URL = `http://<host>:4001`. Shapes below are the **real** payloads (trimmed).

### 3a. Read snapshots (GET) — map to the SCAR panels

| Endpoint | Feeds SCAR panel | Shape (key fields) |
|---|---|---|
| `/stats` | header, PLAYERS, QA | `{uptime_s, player_count, world, verse, players[], bans[], matrix_bridge, game_chat, chat_matrix, demo_mode, qa:{flagged,in_review,corrected,latest}}` |
| `/system/history?window=60` | **HEALTH TELEMETRY** (CPU/VRAM/mesh bars) | `{cpu:[…], mem:[…], net:[…]}` rolling series |
| `/events?since=<n>` | **SERVER CONSOLE — LIVE TAIL** | `{events:[{id,at,kind,msg}], next}` — poll with `since=next`; `kind∈{admin,qa,audit,etch,…}` |
| `/fleet` | **DUTY ROSTER** (one combined snapshot) | `{stardate, verse, tickets[], counts:{open,claimed,resolved}, kinds[], ladder[], officers[], leaderboard[], budget{}, engineer_enabled, promotion_vouches}` |
| `/roster?status=` | Duty Roster list | `{tickets:[{id,code,kind,title,detail,source,severity,status,claimed_by,disposition,created_at,…}], kinds[]}` |
| `/roster/<id>/timeline` | ticket drill-in | `{events:[…]}` (claim→work→resolve→vouch trail) |
| `/ranks`, `/leaderboard`, `/budget` | rank track, commendations, **Fun Budget** | ranks/standings; leaderboard `[{name,points,awards,is_bot}]`; budget `{allocated_sats,spent_sats,remaining_sats,pct_spent,network}` |
| `/nodes` | **FLEET MAP** | `{online, reason?}` (federation/corpus mesh) |
| `/health`, `/system` | health rollup | node vitals |
| `/extensions` | **BOT DECK** | `{extensions:{<id>:{enabled,desc}}}` — e.g. `pacbot`, `poke-engineer`, `poke-counsel` |
| `/modules` | course catalog | `{modules:[{lvl,code,name,path,prereq,rune,access}]}` |
| `/relays`, `/torrent`, `/sitelink`, `/games`, `/block`, `/bans`, `/players/<name>/history` | mesh/site/games/stardate/moderation | see `admin.html` renderers |

### 3b. Actions (POST, JSON body, same header)

- **Duty Roster:** `/roster` (raise) · `/roster/<id>/claim` `{officer}` · `/roster/<id>/resolve`
  `{officer,disposition}` · `/roster/<id>/vouch` `{voter}` (human-only) · `/commend`
  `{recipient,points,reason}` · `/budget` `{allocated_sats,spent_sats}` · `/engineer/audit` (run the
  Chief Engineer now → `{verdict:GREEN|AMBER|RED, findings[], recommendations[], opened[]}`).
- **Ingest:** `/knowledge/flag` `{topic,quote,by}` → raises a peer-review ticket. **Courses escalate
  the same way** (see §5) — that's how a game fault becomes a SCAR alert/ticket.
- **Moderation & ops:** `/broadcast` `/kick` `/mute` `/timeout` `/ban` `/unban` `/watch` `/social`
  `/gamechat` `/chat/restrict` · `/reboot` `/shutdown` (guarded) · `/relays[/remove|/toggle]`
  `/games[/remove|/toggle]` `/extensions` (toggle a bot) `/art` `/torrent` `/sitelink`.
- **Courses:** `/modules` `{action:create|edit|propose}` is currently a **stub** ("the Architect
  wires this next") — the catalog is authored in code/verse data today. Flag if the portal needs live
  module CRUD.

> The single source of truth for shapes is the running node + `admin.html`. If a field's missing for a
> panel you're designing, ping me and I'll expose it on the API rather than have you scrape.

---

## 4. Domain model — Duty Roster / Fleet Ops

- **Tickets are ITIL objects.** `kind ∈ {incident, problem, change, request, anomaly, tribunal,
  peer-review}`; codes `INC-0001`, `CHG-0002`, … ; `status ∈ {open, claimed, resolved}`. Ingest
  adapters raise them: knowledge-flag → peer-review, Chief Engineer audit → incident/anomaly,
  **Academy escalations → incident/request** (`source:"academy"`).
- **Two currencies:** **runes** (what you *learned* — soulbound certs) vs **commendations** (service
  *done* — the roster proof-of-work). Keep them visually distinct.
- **Rank + review board:** promotion = points past a per-verse threshold **AND** peer vouches. Bots
  earn commendations but **cannot vouch** (promotion stays human). Ranks are **honor-only — they must
  never authorize spend** (a documented security invariant; keep it if the Fun Budget gains real
  value).
- **Chief Engineer** (`poke-engineer`, off by default): "don't trust, verify" — recomputes health
  from raw signal, returns `GREEN/AMBER/RED` + findings + opens tickets. The portal's **HIGH-PRIORITY
  ALERTS** rail is a natural home for its RED/AMBER output.
- **Fun Budget:** a Treasury line (sats) rendered as a gauge; `network:"regtest"` today (play money —
  matches the SCAR "REGTEST · SIMULATION / PLAY MONEY" banner).

---

## 5. Domain model — the Academy (courses)

Courses are **playable**, authored as verse data (`services/mud/verses/<verse>/verse.json`), not
portal UI. Two mechanics, both ending in a **soulbound class rune** (`PACS•<TRACK>•<CODE>`):

- **Socratic trials / boss exams** (Q&A): e.g. ITIL Academy on the frens-hub *Training Deck* →
  `PACS•ITIL•SERVICEOPS`, `PACS•ITIL•FOUNDATION`.
- **Field-service scenarios** (hands-on): rooms hold **items** (`take`/`use`) and **fixtures**
  (`examine`, `use <tool> on <thing>`, `escalate`). The **CompTIA A+** wing (frens-hub, west of the
  shuttle bay) ships PC-won't-POST, printer, and **escalation** levels + an A+ exam →
  `PACS•APLUS•{HARDWARE,PRINTERS,ESCALATION,CORE}`.
- **The portal tie-in:** escalating a fault raises a **real Duty Roster ticket** (`source:"academy"`,
  e.g. `INC-0001 "Federation relay down — matrix bridge 8448 CLOSED"`). So the SCAR **SIMULATOR** page
  (running scenarios / play-money drills) and **DUTY ROSTER** are two ends of one loop: crew fix what
  they can and escalate the rest, and it shows up as a ticket/alert. Class runes surface via
  `/players/<name>/history`-adjacent data and the `class_certificates` store.
- **Content is unofficial** (CompTIA/ITIL are trademarks) — surface course/rune titles with the
  "unofficial / practice" wording they already carry; never imply official certification.

---

## 6. Theming & brand seam (reskin without touching markup)

- The entire palette is CSS custom properties on `:root` (`--pa-bg, --pa-fg, --pa-edge, --pa-cyan,
  --pa-neon, --pa-coin, --pa-pink, --pa-font-pixel, …`). **LCARS is already a theme**
  (`html[data-theme="lcars"]` overrides tokens + rounds pills). Per-verse accents via
  `html[data-verse="…"]`. The SCAR look = an LCARS token set; extend, don't fork markup.
  (`DESIGN-CONSOLE.md` is the token reference.)
- **Brand vocabulary already in the data:** stardate = block height (or Bitcoin Federated Time),
  ranks (Ensign→Server Admiral), sats budget, "REGTEST · SIMULATION / PLAY MONEY", node id =
  `NCC-<npub>`, "fren" not "friend". Reuse verbatim.
- **Sound + motion:** WebAudio chirps are synthesized (no assets), user-gesture gated, with an on/off
  toggle; honor `prefers-reduced-motion`. Keep offline-first (no CDN) if the portal must run on-box.

---

## 7. Player entry / identity (how frens.earth users reach the game)

*(Operational details — the exact login + deploy runbook is in §9, pending the pipeline map.)*
- `GET /config` (public) tells a browser how to reach the game (WS bridge URL). `/play` serves the
  browser client; the WS bridge is `PA_MUD_WS_PORT`.
- Players get an identity via `link fren <@handle>` (a pairing code), nostr, or spaces; a public
  profile renders at `/u/<handle>`. `PA_FRENS_URL` connects a node to frens.earth.
- The portal's PLAYERS/BOT DECK panels read `/stats.players[]` and `/extensions`.

---

## 8. Status — live vs pending (so the team knows what's real)

**Live on `main` (`7e9adef`):** Duty Roster + ranks + commendations + Fun Budget + Chief Engineer;
security hardening (256-bit token, rate-limit, bot principal, escaped output); Bitcoin Federated Time
+ hidden Observatory; **A+ + ITIL Academy** with the field-service item engine; the self-contained
`admin.html` console (LCARS/ARCADE themes, sound) as the reference client.

**Pending / seams:** org web `/console` read-view; Ship's Counsel advisory memos; per-operator
identity (closes the residual F2 vouch issue; also unblocks bot certs); live `/modules` CRUD (the
"Architect" seam); richer multi-question exams; Network+/Security+ tracks.

**Division of labor:** the **portal UI is the design team's**; the **node API, game engine, Duty
Roster, and course content are mine**. The contract between us is the admin HTTP API (§3) + the token
theme seam (§6). If the portal needs a new field or endpoint, that's a backend change — send it my
way rather than scraping `admin.html`.

---

## 9. Login & deploy runbook

### Player login / identity — the honest state (important for the login overhaul)
- **Game entry is currently OPEN.** A browser hits `/play`, opens a WS to `PA_MUD_WS_PORT`, and **the
  first line you type is your name** (`get_or_create_player(name)`). There is **no OAuth / nostr /
  frens.earth SSO yet.** `PA_FRENS_URL` is only a **UX flag** — nothing connects to frens.earth, and
  `verify_code()` is a **mock** (`server.py:944-950`). So a "frens.earth login" does not yet admit a
  *specific verified* account; anyone can type any handle.
- **The login/profile system already exists in the `pacsarcade-org` repo** (nostr **NIP-07**
  signed-challenge sign-in, display handle `user@space`) — **the design team is porting it to
  frens.earth and owns this surface** (plus external exposure of `/play`). In *this* engine, entry is
  still open-by-name and `verify_code()` is a mock; the real identity binding lands when the
  frens.earth login integrates against the game (a frens.earth endpoint + a shared secret to be wired
  into `.env`). The web client header marks itself *"the seam for the login/experience overhaul"* —
  that's the hook the ported login plugs into. **Net for the backend: no game-side auth work needed
  from me; the portal/login team drives it, and I expose whatever binding hook they need.**
- **Exposure:** the prod container publishes only telnet `4000` today. To reach the browser game,
  publish the WS bridge `4002` and reverse-proxy `/play`; keep admin `4001` on loopback behind an
  authenticated proxy (the node also **fails closed off-loopback unless `PA_ADMIN_TOKEN` is pinned**).

### Deploy — manual rootless Podman (no CI/webhook)
Prod = Podman **Quadlet** `systemd --user` units (`infra/quadlet/*.container`, `Restart=always`),
repo at `~/pacsarcade/knowledge-engine`, env in `infra/.env`. Ship an update:
```
cd ~/pacsarcade/knowledge-engine && git pull            # main @ 7e9adef
podman compose -f infra/compose.yaml build mud          # rebuild image
systemctl --user restart mud && systemctl --user status mud
```
Verify by observable effects: `curl -H "X-POKE-Admin-Token: $TOKEN" 127.0.0.1:4001/fleet` returns
JSON; boot log shows `verse FRENS Starship` (with `PA_VERSE=frens-hub`); telnet the game, `west` →
`take screwdriver` works. Key env in `infra/.env` (values stay on the box, never in chat):
`PA_VERSE=frens-hub`, `PA_FRENS_URL=https://frens.earth`, `PA_ADMIN_TOKEN` (pinned 256-bit),
`PA_BOT_TOKEN` (distinct), `PA_NETWORK=regtest`, ports, `PA_GAMESTATE_BACKEND`/`PA_DB2_URL` for
Postgres. Constraint: ZAP VPS caps CPU at 550% (sustained → 1h lock).

---

## 10. Integration checklist (for "it comes together seamlessly")

1. Portal gates on `X-POKE-Admin-Token`; handles `401` by re-prompting.
2. Poll `/fleet` + `/events` on the 5s/2s cadence (or your tuned values); render from the §3 shapes.
3. Map panels → endpoints per §3a (BRIDGE=`/stats`+`/events`+`/system/history`; DUTY ROSTER=`/fleet`
   +`/roster`; BOT DECK=`/extensions`; FLEET MAP=`/nodes`; SIMULATOR=course/escalation loop, §5).
4. Wire actions (§3b) with optimistic UI + refetch; respect human-only guards.
5. Theme via `--pa-*` tokens under `html[data-theme="scar"]` (or extend `lcars`); no markup forks.
6. Treat runes ≠ commendations; ranks are honor-only; budget is play-money (regtest) — label it so.
7. Anything missing for a panel → request a backend field/endpoint (don't scrape the reference HTML).
