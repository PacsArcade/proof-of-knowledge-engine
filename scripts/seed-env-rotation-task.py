#!/usr/bin/env python3
"""Raise ONE Duty Roster ticket in a POKE node's SCAR board: cycle the env keys
so each Pac's Arcade area has its OWN secrets (Admiral Pac's to action).

Usage:  PA_ADMIN_URL=http://127.0.0.1:4001 PA_ADMIN_TOKEN=... python seed-env-rotation-task.py
Idempotent: carries a dedup_key, so re-running won't duplicate the ticket.
"""
import json, os, urllib.request, urllib.error

BASE = os.environ.get("PA_ADMIN_URL", "http://127.0.0.1:4001").rstrip("/")
TOK = os.environ.get("PA_ADMIN_TOKEN", "fleetdemo")

TITLE = "Cycle env keys — give each area its own secrets"
DETAIL = (
    "For: Admiral Pac.\n\n"
    "During the frens.earth master-repo migration (2026-07-10) the frens-earth Vercel "
    "project was seeded with pacsarcade-org's PRODUCTION secrets AS-IS (same SEAT_SECRET, "
    "BLOB_READ_WRITE_TOKEN, MATRIX_*, OPERATOR_NPUBS) so nobody got logged out during the "
    "cut-over. That means two areas currently SHARE keys.\n\n"
    "Now that frens.earth is its own master project and every other area clones it, each area "
    "(frens / pacsarcade / degen) should hold its OWN independent secrets so a leak in one can't "
    "cascade and sessions stay isolated per-domain.\n\n"
    "Action (Admiral Pac):\n"
    "  1. Generate a fresh SEAT_SECRET per area (and rotate BLOB_READ_WRITE_TOKEN, MATRIX_JWT_SECRET, "
    "MATRIX_REGISTRATION_SECRET, any PA_ADMIN_TOKEN).\n"
    "  2. Set them per-project on Vercel (frens-earth, pacsarcade-org, degen).\n"
    "  3. Redeploy each. Expect a one-time sign-out as SEAT_SECRET changes — announce it.\n"
    "  4. Revoke the old shared values.\n\n"
    "Follow the secrets runbook: values never in chat; verify by observable effect (sign-in still "
    "works per-area, cross-area cookies no longer validate). (ops: env-key-rotation)"
)

def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"X-POKE-Admin-Token": TOK, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

print(f"raising env-rotation ticket -> {BASE}")
st, r = post("/roster", {
    "kind": "change",           # a planned security change, ITIL roster kind
    "title": TITLE,
    "severity": "high",         # security hygiene — surface it
    "detail": DETAIL,
    "source": "ops",
    "dedup_key": "ops:env-key-rotation",
})
tk = (r.get("result") or {})
print(f"  -> {st}  {tk.get('code','')}  {TITLE}")
print("done. open the SCAR Duty Roster / GET /roster to see it, then claim it as Admiral Pac.")
