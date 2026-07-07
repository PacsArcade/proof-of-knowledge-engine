#!/usr/bin/env bash
# issue-cert.sh — mint a self-signed "Certified Education Node" credential.
# The node signs its own credential with its own key. No central authority.
# The keypair doubles as the node's discovery identity (PA_NODE_PUBKEY).
#
# Usage:
#   ./scripts/issue-cert.sh --keygen-only   # just create the node identity, write pubkey to .env
#   ./scripts/issue-cert.sh                 # create identity if needed, then issue the certificate
#
# NOTE: this is scaffolding. It uses openssl ed25519 as a stand-in for the node key.
# TODO: unify with the nostr/secp256k1 key the bitcoin-bridge uses for OP_RETURN discovery,
#       so the certificate key == the discovery key == the nostr badge key.
set -euo pipefail
cd "$(dirname "$0")/.."

CERTS=certs; KEYS=node-identity
mkdir -p "$CERTS" "$KEYS"
[[ -f .env ]] || cp .env.example .env
# shellcheck disable=SC1091
set -a; . ./.env; set +a
: "${PA_NODE_NAME:=my-first-verse}"; : "${PA_NETWORK:=regtest}"
: "${PA_CORPUS:=simple-wikipedia}"; : "${PA_MATRIX_SERVER_NAME:=verse.local}"

PRIV="$KEYS/node.ed25519.key"; PUB="$KEYS/node.ed25519.pub"

# --- 1. Ensure identity ------------------------------------------------------
if [[ ! -f "$PRIV" ]]; then
  echo "▓ Minting node identity (ed25519)…"
  openssl genpkey -algorithm ed25519 -out "$PRIV" >/dev/null 2>&1
  openssl pkey -in "$PRIV" -pubout -out "$PUB" >/dev/null 2>&1
  PUBHEX="$(openssl pkey -in "$PRIV" -pubout -outform DER 2>/dev/null | tail -c 32 | xxd -p -c 64)"
  # write the pubkey back to .env (idempotent)
  if grep -q '^PA_NODE_PUBKEY=' .env; then
    sed -i "s|^PA_NODE_PUBKEY=.*|PA_NODE_PUBKEY=$PUBHEX|" .env
  else
    echo "PA_NODE_PUBKEY=$PUBHEX" >> .env
  fi
  echo "✓ Identity created. Pubkey: $PUBHEX"
else
  PUBHEX="$(openssl pkey -in "$PRIV" -pubout -outform DER 2>/dev/null | tail -c 32 | xxd -p -c 64)"
fi

[[ "${1:-}" == "--keygen-only" ]] && exit 0

# --- 2. Assemble the certificate --------------------------------------------
read -rp "What does this Verse teach? " SUBJECT || SUBJECT="general knowledge"
ISSUED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
UNSIGNED="$CERTS/$PA_NODE_NAME.unsigned.json"
cat > "$UNSIGNED" <<EOF
{
  "type": "pacs-arcade/certified-education-node",
  "node_name": "$PA_NODE_NAME",
  "node_pubkey": "$PUBHEX",
  "operator_subject": "$SUBJECT",
  "matrix_server": "$PA_MATRIX_SERVER_NAME",
  "corpus": "$PA_CORPUS",
  "network": "$PA_NETWORK",
  "issued_at": "$ISSUED",
  "issued_by": "self"
}
EOF

# --- 3. Sign it with the node key -------------------------------------------
SIG="$(openssl pkeyutl -sign -inkey "$PRIV" -rawin -in "$UNSIGNED" 2>/dev/null | openssl base64 -A)"
PUBCERT="$CERTS/$PA_NODE_NAME.cert.json"
# shellcheck disable=SC2016
if command -v jq >/dev/null; then
  jq --arg sig "$SIG" '. + {signature: $sig}' "$UNSIGNED" > "$PUBCERT"
else
  sed 's/"issued_by": "self"/"issued_by": "self",\n  "signature": "'"$SIG"'"/' "$UNSIGNED" > "$PUBCERT"
fi
rm -f "$UNSIGNED"

echo
echo "  ┌─────────────────────────────────────────────┐"
echo "  │   🎓  CERTIFIED EDUCATION NODE                │"
printf  "  │   Verse:    %-33s │\n" "$PA_NODE_NAME"
printf  "  │   Teaches:  %-33s │\n" "$SUBJECT"
printf  "  │   Network:  %-14s Corpus: %-9s │\n" "$PA_NETWORK" "${PA_CORPUS%%-*}"
echo "  │   Signed by the node's own key. 💜            │"
echo "  └─────────────────────────────────────────────┘"
echo "✓ Certificate: $PUBCERT"
echo "  Optional: publish as a nostr badge, or OP_RETURN-announce via services/bitcoin-bridge"
echo "  (regtest by default; mainnet obeys docs/SECURITY.md)."
