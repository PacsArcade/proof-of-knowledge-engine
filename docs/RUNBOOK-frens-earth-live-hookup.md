# RUNBOOK — frens.earth ⇄ POKE node live hookup

*For Pac's hands. Written 2026-07-09 after the merge round (KE #11/#12, org #5, frens #1/#2/#3).
Goal: production frens.earth profiles show live ARCADE STATS, and the eat6 key opens `/admin/brand`.
Every step ends with a check you can SEE — trust because we verify. No secrets in this doc or in chat.*

Part of the fren-node stand-up framework (fleet-ops origin; graduates into the fren-node template).

---

## A. Redeploy the node (puts the `rank` field live)

On the box (`~/pacsarcade/knowledge-engine`):

- [ ] `cd ~/pacsarcade/knowledge-engine && git pull`
  - Expect: fast-forward to a main that contains `153cf1b` or later.
- [ ] `podman compose -f infra/compose.yaml build mud`
- [ ] `systemctl --user restart mud && systemctl --user status mud`
  - Expect: `active (running)`, boot log shows your verse (`verse FRENS Starship` with `PA_VERSE=frens-hub`).
- [ ] **Verify:** `curl -s 127.0.0.1:4001/u/<a-real-fren> | grep rank`
  - Expect: JSON contains `"rank": "..."` (e.g. `"Ensign"`). 404 `no fren by that name` is fine for unknown names.

*Mind the ZAP CPU cap (550% sustained → 1h lock) — build is the heavy step; let it finish before anything else big.*

## B. Expose the public `/u/` hook (so Vercel can reach it)

The hook is public-by-design but lives on the admin port (`:4001`), which stays loopback. Publish **only** `GET /u/*` through your web proxy — never the whole admin surface.

- [ ] Pick the public address: recommended `node.frens.earth` (add the DNS record → the box's IP).
- [ ] Add a proxy rule that forwards **only** `/u/*` to `127.0.0.1:4001`.
  - Caddy example (adapt if the box runs nginx):
    ```
    node.frens.earth {
        @profile {
            method GET
            path /u/*
        }
        reverse_proxy @profile 127.0.0.1:4001
        respond 404
    }
    ```
- [ ] Reload the proxy (Caddy: `sudo systemctl reload caddy`).
- [ ] **Verify from anywhere (e.g. your phone off wifi):**
  - `https://node.frens.earth/u/<a-real-fren>` → the profile JSON.
  - `https://node.frens.earth/stats` → **404/blocked** (admin stays sealed). If this returns JSON, STOP and remove the rule — the proxy is too wide.

## C. Vercel env (frens.earth project)

In Vercel → frens.earth project → Settings → Environment Variables (Production):

- [ ] `OPERATOR_NPUBS` = your **pacster@pacsarcade** npub (the eat6 key). Comma-separate later operators.
- [ ] `POKE_NODE_URL` = `https://node.frens.earth` (from step B).
- [ ] Confirm `SEAT_SECRET` is already set (sessions + the operator cookie sign with it).
- [ ] Redeploy (Deployments → ⋯ → Redeploy) so the env lands.

## D. Prove it end-to-end (the fun part)

- [ ] Open `https://frens.earth` → the site wears the **Digital Renaissance** look and the footer's only link reads *made with love at Pac's Arcade 💜*.
- [ ] Open `https://frens.earth/u/<a-fren-who-plays>` → **ARCADE STATS** card renders: level + rank, XP, runes, online dot, `DEMO — PRACTICE RUNES` while the node runs demo mode.
- [ ] Open `https://frens.earth/admin/brand` → gate says **TRUST, VERIFIED** → press **VERIFY OPERATOR KEY** → sign with the eat6 key → the dressing room opens.
- [ ] Bench test (optional): timeout a test player from the node console → their `/u/` page wears the `⧗ TIMEOUT` chip and counts down honestly.

## Rollback (any step, no drama)

- Node: `systemctl --user restart mud` after `git checkout <previous-sha>` + rebuild — or just leave it; sites degrade gracefully (no card, no error splash).
- Proxy: remove the `node.frens.earth` rule and reload — profiles simply drop the card.
- Vercel: unset the env var and redeploy — same graceful fallback.

*GG's. Tick tock, next block.* 💜
