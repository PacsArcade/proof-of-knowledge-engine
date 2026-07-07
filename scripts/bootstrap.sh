#!/usr/bin/env bash
# bootstrap.sh — bring a Pac's Arcade education node up locally, in order.
# Rootless Podman: no daemon, no docker.sock, user-namespaced containers.
# Idempotent-ish: safe to re-run. Reads .env. Regtest by default.
#
# Usage:  ./scripts/bootstrap.sh            # full bring-up
#         ./scripts/bootstrap.sh --check    # just health-check what's running
set -euo pipefail
cd "$(dirname "$0")/.."

say()  { printf '\033[35m▓\033[0m %s\n' "$*"; }         # arcade magenta 💜
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. Preflight ------------------------------------------------------------
command -v podman >/dev/null || die "Podman not found. Run scripts/node-doctor.sh; the node-wizard will help you install it (rootless Podman, no daemon)."

# Compose front-end: prefer the built-in `podman compose` (delegates to the
# Compose provider); fall back to the standalone `podman-compose`. Both accept
# `-f` and `--profile`, so the CO string below is identical either way.
if podman compose version >/dev/null 2>&1; then
  COMPOSE="podman compose"
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE="podman-compose"
else
  die "Neither 'podman compose' nor 'podman-compose' is available. Install one (e.g. 'podman-compose' via pip/pacman)."
fi

[[ -f .env ]] || { warn "No .env — copying from .env.example. Edit it, then re-run."; cp .env.example .env; exit 0; }
# shellcheck disable=SC1091
set -a; . ./.env; set +a
: "${PA_NETWORK:=regtest}"; : "${PA_INFERENCE_BACKEND:=ollama}"

if [[ "$PA_NETWORK" == "mainnet" && "${PA_MAINNET_ACK:-false}" != "true" ]]; then
  die "PA_NETWORK=mainnet but PA_MAINNET_ACK is not true. Read docs/SECURITY.md. Refusing."
fi
say "Runtime: $COMPOSE (rootless)   Network: $PA_NETWORK   Inference: $PA_INFERENCE_BACKEND"

CO="$COMPOSE -f infra/compose.yaml --profile ${PA_INFERENCE_BACKEND}"

# --- 1. Node identity (also the discovery key) -------------------------------
if [[ -z "${PA_NODE_PUBKEY:-}" ]]; then
  say "No node identity yet — minting one."
  ./scripts/issue-cert.sh --keygen-only
  set -a; . ./.env; set +a
fi

# --- health-check mode -------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
  $CO ps
  exit 0
fi

# --- 2. Data tier: the two Postgres brains -----------------------------------
say "Starting DB-2 (game state / Blackboard) and DB-1 (the Source)…"
$CO up -d postgres-gamestate postgres-source
say "Waiting for Postgres health…"
for db in postgres-gamestate postgres-source; do
  for i in $(seq 1 30); do
    [[ "$($CO ps -q $db | xargs -r podman inspect -f '{{.State.Health.Status}}' 2>/dev/null)" == "healthy" ]] && { ok "$db healthy"; break; }
    sleep 2; [[ $i -eq 30 ]] && die "$db never became healthy — check logs: $CO logs $db"
  done
done

# --- 3. Inference (WARM) -----------------------------------------------------
say "Starting inference backend ($PA_INFERENCE_BACKEND)…"
$CO up -d inference
warn "First model pull can take a while. Ensure PA_GEN_MODEL + PA_EMBED_MODEL are set in .env."

# --- 4. Bitcoin (regtest) + Matrix (COLD, async) -----------------------------
say "Starting bitcoin ($PA_NETWORK) and the Matrix homeserver…"
$CO up -d bitcoin matrix

# --- 5. Core services --------------------------------------------------------
say "Starting orchestrator, guardrail, state-sync, corpus, bridges…"
$CO up -d orchestrator guardrail state-sync corpus matrix-bridge bitcoin-bridge

# --- 6. Front-ends (HOT) -----------------------------------------------------
say "Starting the MUD and the Voxel Verse…"
$CO up -d mud luanti

echo
ok "Verse is up. 💜"
echo "  MUD:     telnet localhost 4000"
echo "  Luanti:  connect a Minetest client to localhost:30000"
echo "  Next:    run the node-wizard to load the corpus and earn your certificate."
warn "If corpus is empty, ingest it: see .claude/skills/corpus-ingest (Simple English Wikipedia by default)."
warn "For a stay-up production node, install the Quadlet units instead — see infra/quadlet/README.md."
