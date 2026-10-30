# Luanti joined to the MUD, offline (block 969,188)

Branch `feat/luanti-joined-969188` in the knowledge-engine repo, two commits, not pushed. Everything below ran on the ship on 2026-09-29.

## What runs where

| Piece | How | Address | Owner / id |
|---|---|---|---|
| Luanti server 5.17.0 | rootless podman container `pa-luanti`, host network, `--restart=always` | UDP 30000 on 0.0.0.0 (loopback and the box's LAN address) | `podman ps`, script `infra/luanti/run-dev.sh` |
| Dev state-sync (the real `services/state-sync/app.py`, fastapi + uvicorn in `data/luanti/venv`) | `infra/luanti/run-dev-state-sync.sh` | 127.0.0.1:5212 | PID 1800592 (file `data/luanti/state-sync.pid`) |
| Static server for the browser client (COOP/COEP headers) | `infra/luanti/serve_www.py data/luanti/www 5213` | 127.0.0.1:5213 | PID 1942011 |
| WebSocket to UDP bridge for the browser client | `infra/luanti/wsudp_bridge.py` | 127.0.0.1:5214 | PID 1959115 (file `data/luanti/bridge.pid`) |
| Headless chromium with the debug port, fresh profile | left running | 127.0.0.1:5215 | PID 1944812 (main), listener 1944814 |
| The MUD (untouched, not restarted) | Number One's dev server | 4000, 4001, 4002 | PID 1196620 wrapper, 1196627 python |

Everything else in `data/luanti/` is git-ignored runtime data: `games/minetest_game`, `worlds/pacworld`, `www` (built browser client), `dl/` (downloads and build logs), `venv`.

## Versions, images, licenses

- Server image: `ghcr.io/luanti-org/luanti:5.17.0`, digest `sha256:05941f39414a0f97c72be736790f432c8426a0f2afe3104b72f88b2b44075b4f`, 65 MB, image id `f2f92018a4c4`. The old `registry.gitlab.com/minetest/minetest:latest` in the compose file was replaced with this pin (comment added). Luanti engine: LGPL-2.1-or-later (read from the project; not opened in this sitting, listed on the GitHub repo).
- The image ships NO game. Base game: Minetest Game 5.8.0 (tag from `luanti-org/minetest_game`, tarball sha256 `33a3bb43b08497a0bdb2f49f140a2829e582d5c16c0ad52be1595c803f706912`), unpacked to `data/luanti/games/minetest_game`. License read from its `LICENSE.txt`: code LGPL-2.1, media CC BY-SA 3.0. Minetest Game is in maintenance mode; VoxeLibre (GPLv3, mixed media) was not tried tonight.
- World: `data/luanti/worlds/pacworld` (sqlite backends, creative on, damage off), `world.mt` has `load_mod_pacsarcade = true`. Config: `infra/luanti/minetest.dev.conf` (bind 0.0.0.0, `secure.trusted_mods = secure.http_mods = pacsarcade`, mod settings pointing at 127.0.0.1:5212, `pacsarcade.dev_hooks = true`). The mapgen line `mg_name = flat` did not take effect because the world was created by the first start with the default (v7); the spawn is in a snowy pine forest.
- The container runs with `--userns=keep-id:uid=30000,gid=30000` so the world files stay owned by pac.
- Browser client: `paradust7/luanti-wasm` at commit `bc0a515b743baaf9597e38ed53e2671590db1b42` (2026-09-09). LICENSE read: MIT (c) 2022 paradust7. It builds the fork `paradust7/luanti` at commit `038b341f` which is Luanti 5.17.0, the same version as the server. Its helper repos `webshims` and `lwproxy` are MIT (license shown on GitHub; the lwproxy LICENSE file was read).

## Changes in the repo (small)

- `services/state-sync/app.py`: shared-object alias. Object ids `vault_lever` and `lever` read and write the MUD's own row (`world_features` room `vault`, key `lever`, plus `lever.rev` for the revision). New `GET /state/{world}/{object_id}`. Other object ids behave as before. README table updated.
- `luanti/mods/pacsarcade/init.lua`: URLs, world id, lever object id and dev switch are now `minetest.settings` keys (`pacsarcade.state_sync_url` etc., old hardcoded values remain the defaults); the lever is two nodes (steel = off, gold = on) that follow the returned state and a 1 second poll of `GET /state/...`; dev hook (only when `pacsarcade.dev_hooks = true`) reads a trigger file in the world dir (`pull`, `tp`). Fixed a real bug in the stub: an empty Lua table serializes as `[]`, so the old POST body (`meta = {}`) got HTTP 422 from state-sync.
- `infra/compose.yaml`: luanti image pinned as above.
- New in `infra/luanti/`: `minetest.dev.conf`, `run-dev.sh`, `run-dev-state-sync.sh`, `wsudp_bridge.py`, `Containerfile.wasm`, `luanti-wasm-zstd-static.patch`, `patch_www.py`, `serve_www.py`, `cdp_shot.py`.
- Screenshots in `docs/img/luanti-joined-969188/`.

Important finding: in dev the MUD does not use `data/gamestate.dev.sqlite` in the repo root. `services/mud/server.py` sets `PA_GAMESTATE_SQLITE` to `services/mud/data/gamestate.dev.sqlite`. The dev state-sync must point at that file (the run script does). My first attempt used the wrong file and the MUD saw nothing, which is how I found it.

## The join, proved

State lives in one sqlite row the MUD reads on every `pull lever`. The MUD process was not restarted.

Luanti to MUD (the trigger runs the lever node's real `on_rightclick` handler with a fake player, then HTTP POST to state-sync):

```
MUD db before:        [('lever', 'false')]
Luanti log:           [pacsarcade] dev trigger: pulling selftest lever (was pacsarcade:logic_gate_lever)
                      [pacsarcade] lever vault_lever pulled by selftest-bot -> on
MUD db after:         [('lever', 'true'), ('lever.rev', '1')]
MUD telnet, luanti-bot in the Puzzle Vault, `pull lever`:
                      you return the lever; the chest re-seals with a sigh
```

The MUD's message is the "it was ON, now returning it" branch, so the MUD itself saw the state Luanti wrote. Then the MUD's write is on the way back:

```
MUD db after MUD pull: [('lever', 'false'), ('lever.rev', '1')]
Luanti log (about 12 s later, the poll): [pacsarcade] lever vault_lever followed shared state -> off
```

Earlier in the sitting the other direction was also seen the other way round (MUD `pull lever` said "you heave the lever, the chest clicks open", Luanti log `followed shared state -> on`, then `-> off` after the next MUD pull).

In the browser client (headless chromium, see below) the lever block above the player showed the same flips: `flow1-off.png` (steel), `flow2-on-after-luanti-pull.png` (gold), `flow3-after-mud-pull.png` (steel again), in `docs/img/luanti-joined-969188/`.

What was NOT tested: a human right-click. The headless runs use the dev trigger, which calls the same `on_rightclick`. Also, the alias makes every lever in Luanti one shared object (`vault_lever`); with `pacsarcade.lever_object_id` empty each lever would have its own object and no MUD twin. The mod sends `world = default`; the alias ignores the world id on purpose (the MUD's vault row is not per world).

## Browser play

Proved: the luanti-wasm client (5.17.0 fork) built here, loaded in headless chromium (fresh profile each run; a debug-port instance is left running), joined the local server and spawned in the world.

```
console: LUANTI: ACTION[Main]: Connected to fd00::7 ([fd00::7]:30000)
console: LUANTI: ACTION[Main]: CHAT: # Server: version: 5.17.0 | game: Minetest Game | ... | clients: wasmfren3
console: LUANTI: ACTION[Main]: CHAT: *** wasmfren3 joined the game.
server:  wasmfren3 [127.0.0.1] joins game.
```

Screenshot `wasm-join-first-frame.png`. Sizes: the built `www/` is 19 MB (luanti.wasm 14 MB, base.pack 4.7 MB). The build image layers are 2.6 to 2.9 GB. The build took about 15 minutes on 16 cores after two fixes (below).

How it was made to work, since the two upstream pieces do not connect out of the box:

1. Upstream `Dockerfile` fails: `install_emsdk.sh` needs Node 24 and the Dockerfile has none. `infra/luanti/Containerfile.wasm` adds Node 24.21.0 (checksum pinned) and runs the build by hand.
2. `build_zstd.sh` builds a shared `libzstd.so` under the current emscripten, which broke libarchive's configure test. Fixed with `-DZSTD_BUILD_SHARED=OFF` and friends (`infra/luanti/luanti-wasm-zstd-static.patch`, applied to the clone in `data/luanti/dl/wasm-src`, not to their repo).
3. The current upstream proxy `lwproxy` (MIT, Rust; built here, image `localhost/pa-lwproxy:fc74795`, NOT run) is a private overlay between browsers plus a TCP allowlist (content.luanti.org). I read its source: it cannot forward a browser to a normal dedicated server. The client's socket layer also silently drops UDP to any address outside the proxy's `fd00::/16` network (log: "sendto going nowhere", then "Connection timed out"). So I wrote a small bridge (`wsudp_bridge.py`, about 110 lines, websockets library) that speaks the client's proxy protocol (NEWADDR, BIND, 24-byte framed datagrams) and publishes the server under a virtual address: `--map fd00::7=127.0.0.1:30000`. It refuses every other destination and every TCP `PROXY` request (so the in-game content browser will not work, which is fine offline).
4. `patch_www.py` points the page at `ws://127.0.0.1:5214` and adds `?autolaunch=1` for headless runs.

Open it by hand on the ship: `http://127.0.0.1:5213/?name=pac&address=fd00::7&port=30000&go=1`, then click Launch. Use Chrome or Chromium (needs SharedArrayBuffer and OPFS; Firefox untested). It runs in software GL inside the headless runs; a real GPU browser will be smoother. Not tried: WebGL performance with many players, sound, touch, keyboard and mouse look (the headless run only spawned and looked).

Not exposed to the LAN: the page and bridge are bound to 127.0.0.1. To offer the browser client to the LAN, bind them to 0.0.0.0 and change the PROXIES address in `www/index.html` to the ship's LAN IP; the bridge has no authentication, so only do that on a trusted network.

## Characters (read, not installed)

- How the player model is set: Minetest Game's `mods/player_api/init.lua` registers `character.b3d` (with `character.png`) and `player_api.set_model(player, "character.b3d")` is called on join; animations are frame ranges of that one model. Model and skin license (`player_api/license.txt`): CC BY-SA 3.0 (contributors include MirceaKitsune, Jordach, stujones11, and others). The default figure is the classic blocky humanoid (a small number of box-like parts; the triangle count was not measured).
- More polygons: yes in principle. Luanti 5.17.0's `lua_api.md` (read) lists `.x, .b3d, .obj` and, since 5.10, `.gltf` and `.glb`. glTF supports skeletal animation (multiple tracks, use frame speed 1.0), base-colour textures only, no morph targets, no cubic-spline interpolation, no embedded images or external `.bin`. So a detailed rigged character works, but facial blend shapes do not.
- Lumen's VRM, not attempted (out of scope). It would take: convert VRM to plain `.glb` (VRM is glTF plus extensions), strip or extract embedded textures (`gltfutil.py` from luanti-org/modtools), normalize bone weights, drop the morph-target expressions (unsupported), register a model with `player_api.register_model` mapping stand/walk/mine to glTF animation names in seconds with speed 1.0, and set `visual_size` and `collisionbox`. Check the VRM's own license terms before shipping it.
- Character build screen: not in the engine. Three mods, licenses from ContentDB metadata (not yet checked against each repo's files, so verify before install):
  - `skinsdb` by bell07 (github minetest-mods/skinsdb): a skin manager with an in-inventory skin picker; code GPL-3.0-only, media CC0-1.0; about 105k downloads.
  - `character_creator` by minetest-mods: a in-game creator for custom skins; code MIT, media CC-BY-SA-3.0; about 245 downloads, so lightly used.
  - `wardrobe_ad` by AntumDeluge (codeberg.org/AntumLuanti/mod-wardrobe): a wardrobe node to register and switch skins; code MIT, media CC-BY-SA-3.0; about 11k downloads.
  None of these was downloaded or installed. Note GPL-3.0 code (skinsdb) is compatible with running it on our server but matters if we ever ship a combined distribution; the house mod's own license is not stated in the repo.

## How the Admiral connects from a laptop

1. On the laptop, install Luanti 5.17.0 (same version as the server; a nearby 5.x client should also work but that is untested). Per the AUR-vs-upstream law, check the AUR version against the 5.17.0 GitHub release first.
2. Same network as the ship (find the box's LAN address with `ip -4 addr` on that box; it is DHCP and can change). No firewall (`ufw`, `firewalld`, `nftables`) is active on the ship. This LAN route has NOT been tested from another machine tonight, only that the server listens on 0.0.0.0:30000.
3. Luanti main menu, Join Game, Address `<your box's LAN address>`, Port `30000`, any name, password empty (the first login creates the account). The server needs no mods on the client.
4. In the world: creative inventory, search "Logic Gate", place the lever, right-click it. Its gold state means the MUD's vault lever is on. In the MUD, `pull lever` in the Puzzle Vault flips the same switch (within about one second the block changes in Luanti).
5. Note the running server has `pacsarcade.dev_hooks = true` (file trigger in the world folder, only reachable by someone with file access on the ship). Set it to false in `infra/luanti/minetest.dev.conf` before any exposure beyond the LAN.

## Not done

- Restart persistence: the containers and helper processes were started by hand. The Luanti container has `--restart=always` but that needs the user podman restart service to bring it up at boot; the dev state-sync, static server and bridge have no unit files.
- The compose file's own `luanti` service still needs the mods mount changed to the host-network dev arrangement or `PA_STATE_SYNC_URL` wiring; only the image line was changed. With real Postgres state-sync (not dev) the alias rows need a DB-2 mapping.
- The MUD does not call state-sync in dev mode, so the join is "shared sqlite row", not "both through state-sync". Production wiring (MUD via `/command/mud`) is unchanged and still a TODO in the app.
- Chat forwarding to matrix-bridge is untested (bridge not running).
- No LAN client test, no human right-click test, no sound or input test in the browser, no VoxeLibre test, no skin or character mod installed, no glTF model loaded.
- Only one lever id. Doors, rooms, players and runes are not shared yet.

## Obstacles

- The MUD's dev sqlite is `services/mud/data/gamestate.dev.sqlite`, not `data/gamestate.dev.sqlite`; a state-sync pointed at the latter mutates a different world. Cost one debugging round.
- The stub mod sent `"meta": []` (empty Lua table), rejected by state-sync with 422.
- Luanti's dedicated server has no interactive console in a container, so a headless right-click needed the file trigger hook. An earlier trigger fired while the lever's map block was unloaded and crashed the server (restarted, hardened with `load_area` and a node check).
- No `os.remove` in the mod: the law-guard blocks it, so the trigger file is emptied instead.
- `paradust7/luanti-wasm` has no releases (source build only); its Dockerfile is stale (Node 24); zstd builds shared under emscripten 6.0.8; and the client only speaks UDP to a private `fd00::/16` overlay, so the upstream proxy cannot reach a dedicated server. Solved with the bridge above. This is our own glue code and is small, but it is unreviewed for security beyond the destination allowlist.
- `pgrep -f` style wait loops matched their own shell; used explicit PIDs.
- Left behind (stopped, not deleted, per the never-delete law): containers `pa-luanti-failed-1`, `pa-wasm-build-failed-1`, `pa-wasm-build-2` (holds the full build tree), images `pa-luanti-wasm-mid:1`, `pa-luanti-wasm-base:emsdk`, `pa-lwproxy:fc74795`; a `luanti-bot` player row in the MUD dev database; players `wasmfren`, `wasmfren2` to `wasmfren4` and `selftest-bot` in the Luanti world.
