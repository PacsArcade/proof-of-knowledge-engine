#!/usr/bin/env bash
# Start the offline dev Luanti server (rootless podman, host network, UDP 30000).
# Pinned image: ghcr.io/luanti-org/luanti:5.17.0  digest sha256:05941f39414a0f97c72be736790f432c8426a0f2afe3104b72f88b2b44075b4f
# Game: Minetest Game 5.8.0 unpacked in data/luanti/games/minetest_game (LGPL-2.1 code, CC BY-SA 3.0 media).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
D="$ROOT/data/luanti"
exec podman run -d --name pa-luanti --network host --userns=keep-id:uid=30000,gid=30000 --restart=always \
  -v "$D:/var/lib/minetest/.minetest" \
  -v "$ROOT/luanti/mods/pacsarcade:/var/lib/minetest/.minetest/mods/pacsarcade:ro" \
  -v "$ROOT/infra/luanti/minetest.dev.conf:/etc/minetest/minetest.conf:ro" \
  ghcr.io/luanti-org/luanti:5.17.0@sha256:05941f39414a0f97c72be736790f432c8426a0f2afe3104b72f88b2b44075b4f \
  --config /etc/minetest/minetest.conf --world /var/lib/minetest/.minetest/worlds/pacworld --gameid minetest_game
