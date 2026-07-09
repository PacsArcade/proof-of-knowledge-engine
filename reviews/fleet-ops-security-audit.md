# Fleet Ops — Security Audit

**Target:** `feat/fleet-ops` (commits `1dcb00a~1..7b21499`) — the frens.earth MUD
collective-admin surface.
**Scope:** `services/common/world_store.py` (Fleet schema + roster/commendation/rank/board
methods), `services/mud/server.py` (admin HTTP rails, Chief Engineer, promotion logic),
`services/mud/admin.html` (console Fleet Ops rail), `docs/FLEET-OPS.md`.
**Auditor:** security-auditor persona. **Date:** 2026-07-08.
**Prior findings:** none on record (`.autoclaw/memory/personas/security-auditor/` empty — this
is the seed audit; lessons appended below).

## Method & threat model

Read every new send path, auth check, token store, and DB write in the diff. Threat model:

- **(a) Network attacker on the wire.** The admin rails bind `127.0.0.1:4001` *by default*, but
  this branch is explicitly the "MUD admin **network** expansion" — the premise is exposing the
  admin surface to other frens/nodes (`PA_MUD_ADMIN_HOST=0.0.0.0` or a reverse proxy). The audit
  assumes that deployment, because that's what the feature is for.
- **(b) Local attacker / co-tenant with the admin token.** Officer bots (`poke-engineer`,
  `pacbot`, `poke-counsel`) are given the *same* `X-POKE-Admin-Token` as the human owner
  (`docs/BOT-EXTENSION.md`). So "authenticated" ≠ "human owner" — a bot, or anything that has
  read the token, is inside the trust boundary.
- **(c) Accidental disclosure.** Auto-generated token printed to the server console; free-text
  ticket fields rendered in the console DOM.

## Findings

### F1 — Admin surface protected by a 32-bit auto-generated token — **HIGH** — must-fix (blocker)
**Location:** `services/mud/server.py:94` (`ADMIN_TOKEN = ... secrets.token_hex(4)`), guarding
every mutating rail in `do_POST` (`server.py:1541-1706`) and the new Fleet Ops GETs
(`server.py:1514+`).
**Risk:** When `PA_ADMIN_TOKEN` is unset, the token is `token_hex(4)` = **4 bytes / 32 bits**
(8 hex chars). `secrets.compare_digest` is correctly constant-time, but there is **no rate
limiting, lockout, or attempt logging** on the HTTP rails (`_authed`, `server.py:1397`). Against
a network-exposed `:4001` (threat (a) — the whole point of this branch), 32 bits is online-
guessable, and every hit grants broadcast, kick, **reboot, shutdown**, budget writes, and
promotion. The in-MUD `admin <token>` path (`server.py:1726`) is the same token over the game
socket, widening the guess surface.
**Fix:** (1) Default to `token_hex(32)` (256-bit) when generating. (2) **Refuse to serve the
admin rails on a non-loopback host unless `PA_ADMIN_TOKEN` is explicitly set** — fail closed in
`_start_admin_http` (`server.py:1712`) if `ADMIN_HTTP_HOST` isn't loopback and the token was
auto-generated. (3) Add a simple per-IP failed-attempt backoff on `_authed`. Load-bearing
invariant: a network-reachable admin port must never run on an auto-minted low-entropy token.

### F2 — Promotion integrity is forgeable: `voter` is client-controlled — **MEDIUM** — must-fix (blocker)
**Location:** `server.py:1668-1680` (`/roster/<id>/vouch`, `voter = data.get("voter") or ...`)
→ `world_store.py:244-265` (`vouch`), promotion gate `server.py:529` / `540-551`.
**Risk:** A review board convenes at `FLEET_PROMOTION_VOUCHES` (default 2) *distinct* vouches.
But `voter` is free text from the POST body, and the only uniqueness guard is
`UNIQUE(ticket_id, voter)` (`world_store.py:94`). A single token holder can POST
`voter:"alice"` then `voter:"bob"` on the same resolved mission and manufacture the quorum —
`self`-vouch is blocked (`world_store.py:253`) but sockpuppet vouches are not. Result: anyone
with the token can promote any candidate (or themselves via a second name) to **Server Admiral**.
Today this is a gamification/"proof of work" integrity control on regtest, but `docs/FLEET-OPS.md`
ties ranks and commendations to the Fun Budget and future reward payouts — the moment sats key
off rank, this becomes a theft primitive.
**Fix:** Bind `voter` to an authenticated identity, not a request field — derive it from the
operator's session/tag server-side, or require each vouch to carry its own proof (a per-officer
credential). At minimum, gate promotion on distinct *authenticated* voters and record the source
IP/identity in `board_votes` so sockpuppets are detectable. Until then, treat promotions as
advisory, not reward-bearing.

### F3 — "Promotion stays human" bypass: bot-gate trusts a self-declared header — **MEDIUM** — must-fix (blocker)
**Location:** `server.py:1674` (`if self.headers.get("X-POKE-Bot", "").strip(): return 403`).
**Risk:** The rule "bots earn, humans vouch" (`docs/FLEET-OPS.md §7`) is enforced only by
checking the `X-POKE-Bot` header the caller sets on itself. Because bots hold the same admin
token (threat (b)), a bot can simply **omit the header** and its vouch counts as a human's. The
honesty contract is voluntary; the security control can't be. Combined with F2, an autonomous
officer bot could resolve a mission, drop the header, cast the required vouches under invented
names, and self-promote — with no human in the loop, which is exactly what the control exists to
prevent.
**Fix:** Don't derive human-ness from a spoofable header. Issue bots a *distinct* credential
(separate token or signed identity) so the server knows a caller is a bot regardless of headers,
and enforce the human-only rule on that. This is the same root cause as F2 (identity is
client-asserted) — fixing identity binding closes both.

### F4 — Fun Budget writes are unattributed free input — **LOW** — accept-with-docs (regtest)
**Location:** `server.py:1691-1693` (`/budget`), `server.py:584-591` (`fleet_budget_set`).
**Risk:** `allocated_sats`/`spent_sats` are operator-set with no `awarded_by`/actor recorded and
no history — fine while `network: regtest` and nothing spends, but there's no audit trail of who
moved the budget. If this ever gauges a real treasury pool, unattributed writes are a problem.
**Fix:** Record actor + timestamp per budget change (mirror the `ticket_events` pattern) before
the budget references anything spendable. Acceptable to defer while regtest-only — **document it
as a GA blocker** for the reward pool.

### F5 — Chief Engineer `verdict` injected unescaped into console DOM — **LOW** — should-fix
**Location:** `admin.html` audit render (`+ '<div class="av '+a.verdict+'">CHIEF ENGINEER — '+a.verdict+'</div>'`).
**Risk:** `a.verdict` and `a.stardate` are interpolated into `innerHTML` without `flEsc`. Both
are server-computed (RED/AMBER/GREEN; block height), so not attacker-controlled today — but every
*other* server string in this file is escaped, so this is an inconsistent trust assumption one
refactor away from a stored-XSS sink if `verdict` ever carries upstream text.
**Fix:** Wrap in `flEsc(...)` for consistency; treat "all server strings are escaped in the DOM"
as the invariant.

### F6 — Postgres backend hard-fails every Fleet Ops call — **INFO** — availability note
**Location:** `world_store.py:281-327` (all `PostgresWorldStore` fleet methods `raise
NotImplementedError`; DB-2 SQL is TODO).
**Risk:** Correct fail-loud design (better than silent wrong data). But if frens-hub runs the
Postgres backend before `infra/postgres/04-db2-fleet-ops.sql` lands, the roster, ranks,
leaderboard, and Chief Engineer audit all throw 500s. This is a deployment-ordering trap, not a
vulnerability.
**Fix:** Land DB-2 before flipping any Fleet-Ops-enabled node to Postgres; until then pin those
nodes to the SQLite store.

## What's solid (verified, not just assumed)

- New Fleet Ops **GET** rails (`/fleet`, `/roster`, `/ranks`, `/leaderboard`, `/budget`) sit
  **after** the `_authed()` gate (`server.py:1462-1463`) — not public. ✓
- Console renders ticket `title`, `code`, `disposition`, officer names, leaderboard names, and
  audit `msg`/recs through `flEsc()` — the obvious stored-XSS vector (a ticket titled
  `<img onerror>` via the knowledge-flag ingest adapter) is closed. ✓ (F5 is the lone exception.)
- `vouch` correctly blocks self-vouch and non-resolved missions; ingest dedup is idempotent
  (`world_store.py:107-126`); Chief Engineer is read-only and recommends, never mutates the box. ✓
- Budget/rewards are `network: regtest` and etch/spend nothing. ✓

## GA gate table

| Finding | Severity | Disposition | Unanimous-vote blocker? |
|---|---|---|---|
| F1 — 32-bit admin token on a network surface | HIGH | must-fix | **yes** |
| F2 — forgeable promotion quorum (client `voter`) | MEDIUM | must-fix | **yes** |
| F3 — human-only gate trusts spoofable header | MEDIUM | must-fix | **yes** |
| F4 — unattributed Fun Budget writes | LOW | accept-with-docs (regtest); GA blocker for real pool | no (now) |
| F5 — unescaped `verdict` in console | LOW | should-fix | no |
| F6 — Postgres fleet methods unimplemented | INFO | deployment-ordering note | no |

**Vote:** `request_changes` — F1, F2, F3 are open blockers. F1 and F3 (identity is asserted, not
proven) share a root cause with F2; a single fix — **bind caller identity server-side and give
bots a distinct credential, on a high-entropy token that fails closed off-loopback** — closes the
security-critical set. Re-audit on the fix diff; `approve` only when F1–F3 are FIXED and F4 is
documented accepted-risk.

## Resolution

Fixes landed 2026-07-08 (Claude Code, at owner's direction) on `feat/fleet-ops`. Verified by
isolated functional tests (store integrity + server principal/rate-limit) and `py_compile`.

| Finding | Disposition | Evidence |
|---|---|---|
| **F1** — low-entropy admin token, no rate-limit, network-exposable | **FIXED** | Default token now `secrets.token_hex(32)` = 256-bit (`server.py` token init). Per-IP failed-auth rate limiter (`_auth_rate_limited/_auth_note_failure`, `_AUTH_MAX_FAILS`/`_AUTH_WINDOW_S`) gates every authed GET/POST via `_auth_or_reject()`. `_start_admin_http` **fails closed** on a non-loopback host when the token was auto-generated. Tested: 256-bit length, limiter trips at threshold and clears on success. |
| **F3** — human-only gate trusts spoofable `X-POKE-Bot` header | **FIXED** | Human/bot is now the **authenticated principal** (`_principal()`): admin token → `human`, distinct `PA_BOT_TOKEN` → `bot`. `/roster/<id>/vouch` checks `_principal() != "human"`. Tested: `admin token + bot header → human` (header can't downgrade), `bot token, no header → bot` (drop can't upgrade). Documented in `docs/BOT-EXTENSION.md`. |
| **F2** — forgeable promotion quorum (client `voter`) | **REDUCED + contained** (full closure DEFERRED) | `vouch()` now rejects any `voter` not in `known_officers()` (can't conjure fresh sockpuppets), records `voter_ip` + `voter_principal` for same-source detection, and only `human`-principal callers reach it. Tested: unknown voter refused, self-vouch refused, served officer allowed, dup refused, audit row written. **Residual:** one *human* operator holding the shared admin token can still cast vouches under multiple *existing* officer names — true one-human-one-vote needs per-operator identity (shared dependency with the agents work). **Containment invariant (documented in `vouch()`):** ranks/commendations are HONOR ONLY and must never authorize spend, so this stays a gamification issue, not a theft primitive. Keep that invariant when the Fun Budget gains real value. |
| **F4** — unattributed Fun Budget writes | **DEFERRED (accepted, regtest)** | Unchanged; still `network: regtest`. GA blocker for a real reward pool — add actor+history before the budget references anything spendable. |
| **F5** — unescaped `verdict` in console | **FIXED** | Chief Engineer `verdict`/`stardate` now escaped via `flEsc`; level/verdict class attrs whitelisted via `flCls` (`[A-Za-z-]`, case-preserved so `.av.RED`/`.fl.red` still match). New BFT stardate render uses `textContent`. |
| **F6** — Postgres fleet methods unimplemented | **NOTED (unchanged)** | Still fail-loud `NotImplementedError`; land DB-2 before any Fleet-Ops node goes Postgres. |

**Net:** F1, F3, F5 closed; F2 reduced to a contained gamification issue behind an honor-only
invariant with an audit trail; F4/F6 unchanged and documented. The one security-critical item
still open in principle (F2's per-human identity) is now non-exploitable for value under the
honor-only invariant. Recommend re-audit of this diff, then the vote can move to `approve` once
peers confirm the invariant holds and accept F2's residual as documented risk.

_Naming note: per owner (2026-07-08) universe/lore naming is on hold; fixes use neutral
technical terms only._
