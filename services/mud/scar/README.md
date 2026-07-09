# scar-mud-link — hook the SCAR dashboard into the POKEMUD node

A drop-in bundle for the **knowledge-engine MUD package** (`services/mud/`) that links the
new **SCAR — Sovereign Corps Access Relay** operator console to the node's admin HTTP API,
per the design team's contract in [`docs/ADMIN-PORTAL-INTEGRATION.md`](../../../docs/ADMIN-PORTAL-INTEGRATION.md).

The node already computes everything; SCAR just renders. This bundle is the glue.

## What's inside

| File | What it is |
|---|---|
| [`docs/ADMIN-PORTAL-INTEGRATION.md`](../../../docs/ADMIN-PORTAL-INTEGRATION.md) | The integration spec — one canonical copy at repo `docs/` (committed 2026-07-09; supersedes the recovered artifact transcription this bundle shipped with). |
| `scar-adapter.js` | Zero-dependency JS client for the contract: token auth + 401 re-gate, §3a panel/endpoint map, §3b actions, 5s/2s polling with event cursor, optimistic-UI helper, network safety badge (mainnet confirm guard). |
| `scar-linkcheck.html` | Standalone, offline-first console that proves the link: runs every §3a GET against a node, shows per-panel status + latency, and streams the live event tail. Pac's Arcade themed via `--pa-*` tokens (LCARS switchable). |
| `mock/mock_admin.py` | Stdlib-Python mock of the admin API (`:4001`, token `frens`) so the portal team can build and demo with no node running. Honors the 401 gate, event cursor, and §3b actions. |

## Try it in 30 seconds (no node needed)

```bash
python3 mock/mock_admin.py            # mock admin API on 127.0.0.1:4001, token: frens
python3 -m http.server 8080           # serve this folder (same dir as the two files)
# open http://127.0.0.1:8080/scar-linkcheck.html → paste token "frens" → RUN CHECK → START LIVE TAIL
```

## Against a real node

Same steps, but point the host field at the node's admin port (loopback, or behind your
authenticated proxy — the node fails closed off-loopback unless `PA_ADMIN_TOKEN` is pinned,
spec §2/§9) and paste the real operator token. **Never the bot token.**

## Wiring the SCAR v2 prototype

`SCAR Console v2.dc.html` currently renders simulated data. To go live, replace its data
layer with the adapter:

```html
<script src="scar-adapter.js"></script>
<script>
  const scar = new PokeAdminClient({
    baseUrl: nodeUrl,
    onAuthFail: () => showTokenGate(),           // §10.1
    confirmMainnet: (path) => showFullPageMainnetModal(path),  // brief §1; Ensign: () => false
  });
  scar.setToken(operatorToken);

  scar.startPolling({
    onFleet:  f  => { renderDutyRoster(f); renderBadge(scar.networkBadge()); },  // ~5s
    onEvents: p  => appendLiveTail(p.events),                                    // ~2s
    onStats:  s  => renderBridge(s),
    onHistory: h => renderTelemetry(h),
  });

  // actions with optimistic UI (§10.4)
  scar.optimistic({
    apply:    () => paintClaimed(id),
    action:   () => scar.actions.claim(id, '@pacsarcade-ops'),
    refetch:  () => scar.fleet().then(renderDutyRoster),
    rollback: () => unpaintClaimed(id),
  });
</script>
```

Panel → endpoint map is exported as `PokeAdminClient.PANEL_ENDPOINTS` (matches §10.3):
BRIDGE = `/stats` + `/events` + `/system/history` · DUTY ROSTER = `/fleet` + `/roster` ·
BOT DECK = `/extensions` · FLEET MAP = `/nodes` · SIMULATOR = `/modules` + the academy
escalation loop (§5 — escalations arrive as roster missions with `source:"academy"`).

## Where it lands in the repo

Suggested placement in `knowledge-engine`:

```
services/mud/
├── admin.html            # existing reference console (the contract in code)
├── scar/                 # ← this bundle
│   ├── scar-adapter.js
│   ├── scar-linkcheck.html
│   └── mock/mock_admin.py
```

## House rules honored

Missions not tickets (API says tickets — map at the render layer) · runes are **etched**,
never minted · runes ≠ commendations · ranks are honor-only, never authorize spend ·
coin gold = money only, neon = live/success, ghost = danger, cyan = info, pink = flair ·
budget is play-money (regtest) and labeled so · "fren" never "friend" ·
mainnet = blinking red badge + full-page confirm; Ensigns blocked outright.

## Open items for the two teams

- The spec's §3b `/modules` CRUD is a stub ("the Architect wires this next") — flag if the
  SIMULATOR tab needs live module editing.
- Real payloads win: the single source of truth is the running node + `admin.html` (§3).
  If a SCAR panel needs a missing field, request a backend change — don't scrape.
- Login/SSO is the design team's surface (§9): game entry is open-by-name today;
  `verify_code()` is a mock until the frens.earth login integrates.
