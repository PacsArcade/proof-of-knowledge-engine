#!/usr/bin/env python3
"""mock_admin.py — stdlib-only mock of the POKE node admin API (:4001).

Lets the SCAR portal team develop and demo against the §3a/§3b contract in
ADMIN-PORTAL-INTEGRATION.md without a running knowledge-engine node.

    python3 mock_admin.py                # serves http://127.0.0.1:4001
    python3 mock_admin.py --port 4101 --token frens

Auth mirrors the real node: every route except /config and /u/<handle>
requires  X-POKE-Admin-Token: <token>  (default token: "frens").
Wrong/missing token -> 401, same as production, so the portal's token gate
and re-prompt path can be exercised.

No real assets, no real network: budget.network is "regtest" (play money).
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

START = time.time()
EVENT_KINDS = ["admin", "qa", "audit", "etch", "sys"]

STATE = {
    "events": [],
    "next_event_id": 1,
    "tickets": [
        {"id": "T-0001", "code": "INC-0001", "kind": "incident",
         "title": "Federation relay down — matrix bridge 8448 CLOSED",
         "detail": "Raised from the Academy escalation loop.",
         "source": "academy", "severity": "high", "status": "open",
         "claimed_by": None, "disposition": None, "created_at": START - 3600},
        {"id": "T-0002", "code": "CHG-0002", "kind": "change",
         "title": "Rotate node certificate before stardate rollover",
         "detail": "Scheduled change window, regtest only.",
         "source": "operator", "severity": "med", "status": "claimed",
         "claimed_by": "@pacsarcade-ops", "disposition": None,
         "created_at": START - 7200},
        {"id": "T-0003", "code": "REV-0003", "kind": "peer-review",
         "title": "Knowledge flag: 'lightning channels are custodial'",
         "detail": "Guardrail quarantine — needs a human fren.",
         "source": "knowledge-flag", "severity": "low", "status": "resolved",
         "claimed_by": "@frenboffin", "disposition": "corrected",
         "created_at": START - 9000},
    ],
    "budget": {"allocated_sats": 250000, "spent_sats": 66500,
               "remaining_sats": 183500, "pct_spent": 26.6, "network": "regtest"},
    "extensions": {
        "pacbot":        {"enabled": False, "desc": "ops/tutor — sentiment + curtness sliders"},
        "poke-engineer": {"enabled": False, "desc": "Chief Engineer — don't trust, verify"},
        "poke-counsel":  {"enabled": False, "desc": "Ship's Counsel — compliance / banned verbiage"},
        "architect":     {"enabled": False, "desc": "proposes training module slots"},
    },
    "leaderboard": [
        {"name": "@frenboffin", "points": 14, "awards": 3, "is_bot": False},
        {"name": "@pacsarcade-ops", "points": 11, "awards": 2, "is_bot": False},
        {"name": "@nodesmith", "points": 6, "awards": 1, "is_bot": False},
        {"name": "poke-engineer", "points": 3, "awards": 0, "is_bot": True},
    ],
}


def push_event(kind, msg):
    ev = {"id": STATE["next_event_id"], "at": time.time(), "kind": kind, "msg": msg}
    STATE["next_event_id"] += 1
    STATE["events"].append(ev)
    STATE["events"] = STATE["events"][-500:]
    return ev


for i, (k, m) in enumerate([
    ("sys",   "verse FRENS Starship online — SqliteWorldStore (mock)"),
    ("admin", "operator @pacsarcade-ops opened the admin surface"),
    ("qa",    "guardrail: 1 claim quarantined for review"),
    ("audit", "chief engineer verdict: AMBER — 0 tickets opened"),
    ("etch",  "class rune PACS•ITIL•FOUNDATION etched for fren @nodesmith"),
]):
    push_event(k, m)


def rolling(n, base, spread):
    import math
    return [round(base + spread * math.sin((time.time() + i * 7) / 13.0), 1)
            for i in range(n)]


def ticket_counts():
    c = {"open": 0, "claimed": 0, "resolved": 0}
    for t in STATE["tickets"]:
        c[t["status"]] = c.get(t["status"], 0) + 1
    return c


class Handler(BaseHTTPRequestHandler):
    server_version = "POKEMockAdmin/0.1"
    TOKEN = "frens"

    # ── plumbing ─────────────────────────────────────────────────────────
    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "X-POKE-Admin-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def _authed(self):
        return self.headers.get("X-POKE-Admin-Token", "") == self.TOKEN

    def _path_query(self):
        path, _, qs = self.path.partition("?")
        q = {}
        for pair in qs.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                q[k] = v
        return path.rstrip("/") or "/", q

    def log_message(self, fmt, *args):  # quiet
        pass

    # ── GET (§3a) ────────────────────────────────────────────────────────
    def do_GET(self):
        path, q = self._path_query()
        if path == "/config":
            return self._send(200, {"ws_url": "ws://127.0.0.1:4002", "play": "/play",
                                    "verse": "frens-hub", "mock": True})
        if path.startswith("/u/"):
            return self._send(200, {"handle": path[3:], "rank": "FREN",
                                    "runes": ["PACS•ARCADE•BTC101"], "mock": True})
        if not self._authed():
            return self._send(401, {"error": "admin token required"})

        if path == "/stats":
            return self._send(200, {
                "uptime_s": int(time.time() - START), "player_count": 3,
                "world": "POKEMUD", "verse": "frens-hub",
                "players": [{"name": "@frenboffin", "room": "Oracle's Alcove"},
                            {"name": "@nodesmith", "room": "Training Deck"},
                            {"name": "@wanderingfren", "room": "Puzzle Vault"}],
                "bans": [], "matrix_bridge": False, "game_chat": True,
                "chat_matrix": False, "demo_mode": True,
                "qa": {"flagged": 1, "in_review": 1, "corrected": 4,
                       "latest": "lightning channels claim corrected"}})
        if path == "/system/history":
            n = min(int(q.get("window", 60)), 240)
            return self._send(200, {"cpu": rolling(n, 22, 9), "mem": rolling(n, 41, 4),
                                    "net": rolling(n, 8, 6)})
        if path == "/events":
            since = int(q.get("since", 0))
            evs = [e for e in STATE["events"] if e["id"] > since]
            return self._send(200, {"events": evs, "next": STATE["next_event_id"] - 1})
        if path == "/fleet":
            return self._send(200, {
                "stardate": 903211, "verse": "frens-hub",
                "tickets": STATE["tickets"], "counts": ticket_counts(),
                "kinds": ["incident", "problem", "change", "request",
                          "anomaly", "tribunal", "peer-review"],
                "ladder": ["FREN", "STUDENT", "GRADUATE"],
                "officers": ["@pacsarcade-ops", "@frenboffin"],
                "leaderboard": STATE["leaderboard"], "budget": STATE["budget"],
                "engineer_enabled": STATE["extensions"]["poke-engineer"]["enabled"],
                "promotion_vouches": 2})
        if path == "/roster":
            status = q.get("status", "")
            ts = [t for t in STATE["tickets"] if not status or t["status"] == status]
            return self._send(200, {"tickets": ts,
                                    "kinds": ["incident", "problem", "change", "request",
                                              "anomaly", "tribunal", "peer-review"]})
        if path.startswith("/roster/") and path.endswith("/timeline"):
            return self._send(200, {"events": [
                {"at": START - 3000, "what": "raised", "by": "academy"},
                {"at": START - 2000, "what": "claimed", "by": "@pacsarcade-ops"}]})
        if path == "/ranks":
            return self._send(200, {"ladder": ["FREN", "STUDENT", "GRADUATE"],
                                    "threshold_points": 10, "vouches_needed": 2})
        if path == "/leaderboard":
            return self._send(200, {"leaderboard": STATE["leaderboard"]})
        if path == "/budget":
            return self._send(200, STATE["budget"])
        if path == "/nodes":
            return self._send(200, {"online": False, "reason": "knowledge swarm OFFLINE (mock)"})
        if path in ("/health", "/system"):
            return self._send(200, {"ok": True, "cpu_pct": 23.5, "vram_pct": 61.0,
                                    "store": "SqliteWorldStore(mock)"})
        if path == "/extensions":
            return self._send(200, {"extensions": STATE["extensions"]})
        if path == "/modules":
            return self._send(200, {"modules": [
                {"lvl": 1, "code": "BTC101", "name": "Self-Custody Basics (practice)",
                 "path": "arcade", "prereq": None, "rune": "PACS•ARCADE•BTC101", "access": "OPEN"},
                {"lvl": 2, "code": "ITIL-F", "name": "ITIL Foundation (unofficial)",
                 "path": "itil", "prereq": "BTC101", "rune": "PACS•ITIL•FOUNDATION",
                 "access": "AFTER-BTC101"}]})
        if path in ("/relays", "/torrent", "/sitelink", "/games", "/block", "/bans"):
            return self._send(200, {"mock": True, "items": []})
        if path.startswith("/players/") and path.endswith("/history"):
            return self._send(200, {"history": [], "runes": ["PACS•ARCADE•BTC101"]})
        return self._send(404, {"error": "unknown endpoint " + path})

    # ── POST (§3b) ───────────────────────────────────────────────────────
    def do_POST(self):
        path, _ = self._path_query()
        if not self._authed():
            return self._send(401, {"error": "admin token required"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})

        def find(tid):
            return next((t for t in STATE["tickets"] if t["id"] == tid), None)

        if path == "/roster":
            tid = "T-%04d" % (len(STATE["tickets"]) + 1)
            t = {"id": tid, "code": body.get("code", "REQ-%04d" % (len(STATE["tickets"]) + 1)),
                 "kind": body.get("kind", "request"), "title": body.get("title", "(untitled)"),
                 "detail": body.get("detail", ""), "source": body.get("source", "operator"),
                 "severity": body.get("severity", "low"), "status": "open",
                 "claimed_by": None, "disposition": None, "created_at": time.time()}
            STATE["tickets"].append(t)
            push_event("admin", "mission %s raised: %s" % (t["code"], t["title"]))
            return self._send(200, t)
        if path.startswith("/roster/"):
            parts = path.split("/")
            t, verb = find(parts[2]), (parts[3] if len(parts) > 3 else "")
            if not t:
                return self._send(404, {"error": "no such ticket"})
            if verb == "claim":
                t["status"], t["claimed_by"] = "claimed", body.get("officer")
                push_event("admin", "%s claimed by %s" % (t["code"], t["claimed_by"]))
            elif verb == "resolve":
                t["status"], t["disposition"] = "resolved", body.get("disposition", "fixed")
                push_event("admin", "%s resolved (%s) — vouches pending" % (t["code"], t["disposition"]))
            elif verb == "vouch":
                push_event("admin", "%s vouched by %s (human-only)" % (t["code"], body.get("voter")))
            else:
                return self._send(404, {"error": "unknown roster verb"})
            return self._send(200, t)
        if path == "/commend":
            push_event("admin", "commendation → %s (+%s): %s" %
                       (body.get("recipient"), body.get("points"), body.get("reason")))
            return self._send(200, {"ok": True})
        if path == "/budget":
            STATE["budget"].update({k: body[k] for k in ("allocated_sats", "spent_sats") if k in body})
            b = STATE["budget"]
            b["remaining_sats"] = b["allocated_sats"] - b["spent_sats"]
            b["pct_spent"] = round(100.0 * b["spent_sats"] / max(b["allocated_sats"], 1), 1)
            return self._send(200, b)
        if path == "/engineer/audit":
            push_event("audit", "chief engineer verdict: GREEN — all systems nominal (mock)")
            return self._send(200, {"verdict": "GREEN", "findings": [],
                                    "recommendations": ["keep having fun"], "opened": []})
        if path == "/knowledge/flag":
            push_event("qa", "knowledge flagged: %s" % body.get("topic"))
            return self._send(200, {"ok": True, "raised": "peer-review"})
        if path == "/extensions":
            ext = STATE["extensions"].get(body.get("id", ""))
            if not ext:
                return self._send(404, {"error": "unknown extension"})
            ext["enabled"] = bool(body.get("enabled"))
            push_event("admin", "extension %s → %s" %
                       (body["id"], "ON" if ext["enabled"] else "OFF"))
            return self._send(200, {"extensions": STATE["extensions"]})
        if path in ("/broadcast", "/kick", "/mute", "/timeout", "/ban", "/unban",
                    "/watch", "/social", "/gamechat", "/chat/restrict", "/art",
                    "/torrent", "/sitelink", "/reboot", "/shutdown"):
            push_event("admin", "%s %s (mock no-op)" % (path, json.dumps(body)))
            return self._send(200, {"ok": True, "mock": True})
        return self._send(404, {"error": "unknown endpoint " + path})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=4001)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", default="frens")
    args = ap.parse_args()
    Handler.TOKEN = args.token
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("POKE mock admin API on http://%s:%d  (token: %s)" % (args.host, args.port, args.token))
    print("Try: curl -H 'X-POKE-Admin-Token: %s' http://%s:%d/fleet" % (args.token, args.host, args.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
