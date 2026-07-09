"""world_store.py — the persistence substrate shared by the MUD and state-sync. 💜

One contract, two backends:

  • SqliteWorldStore  — stdlib `sqlite3`, zero setup. The DEV default: run the MUD with nothing
    installed and your progress (room, inventory, earned runes, competency) survives a reconnect.
  • PostgresWorldStore — the PRODUCTION backend, mapping the same operations onto the real DB-2
    schema (`infra/postgres/02-db2-gamestate.sql` + `03-class-runes.sql`). Validated when the
    Podman stack is up; lazy-imports its driver so dev never needs it.

Pick a backend with `open_store()` (reads env). Both expose the identical, domain-level API so
the MUD and the state-sync translation API mutate one world through one seam.

Design notes:
  - The MUD is HOT-tier: these calls must stay fast and node-local. SQLite/Postgres on the same
    box is fine; callers wrap them in `asyncio.to_thread(...)` so the event loop never blocks.
  - Money/credential safety lives in `services/bitcoin-bridge` — this store only RECORDS the
    ledger of what was earned (schema-aligned with `class_certificates`). In dev the rune is a
    mock; in prod the real etch txid/height/time come from `runes.py`.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def mock_wallet_for(name: str) -> str:
    """Deterministic regtest-style wallet per player name, so a player's 'original wallet' is
    stable across sessions in dev. Production uses the player's real wallet, not this."""
    h = sha256(("pacs-arcade:" + name).encode()).hexdigest()
    return "bcrt1q" + h[:32]


# Fleet Ops (docs/FLEET-OPS.md): ITIL-shaped ticket kinds → a human code prefix.
_TICKET_PREFIX = {
    "incident": "INC", "problem": "PRB", "change": "CHG", "request": "REQ",
    "anomaly": "ANM", "tribunal": "TRB", "peer-review": "REV",
}


def ticket_code(kind: str, tid: int) -> str:
    """Human-facing away-mission code, e.g. INC-0007, REV-0012."""
    return f"{_TICKET_PREFIX.get(kind, 'MSN')}-{int(tid):04d}"


# --------------------------------------------------------------------------- #
# SQLite backend — the dev default (stdlib, zero setup)
# --------------------------------------------------------------------------- #
class SqliteWorldStore:
    """File-backed world state. Schema mirrors DB-2 loosely (denormalized: topic/class as text)
    so the leap to Postgres later is a backend swap, not a redesign."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        # check_same_thread=False so asyncio.to_thread workers can share the connection;
        # every method takes the lock via the connection's implicit serialization.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()
        self._ensure_fleet_schema()

    def _ensure_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                name       TEXT PRIMARY KEY,
                room       TEXT NOT NULL DEFAULT 'entrance',
                inventory  TEXT NOT NULL DEFAULT '[]',   -- JSON array
                wallet     TEXT,
                nostr      TEXT,                          -- linked nostr npub
                space      TEXT,                          -- linked spaces @name
                fren_tag   TEXT,                          -- the @fren handle
                xp         INTEGER NOT NULL DEFAULT 0,    -- knowledge points
                energy     INTEGER NOT NULL DEFAULT 100,  -- spent/regained in boss fights
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS player_memory (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                player     TEXT NOT NULL,
                role       TEXT NOT NULL,                 -- 'player' | 'game'
                text       TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_player_memory ON player_memory(player, id);
            CREATE TABLE IF NOT EXISTS competency_node (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                player            TEXT NOT NULL,
                topic             TEXT NOT NULL,
                mastery_score     REAL NOT NULL,
                transcript_summary TEXT,
                created_at        TEXT DEFAULT (datetime('now')),
                UNIQUE(player, topic)
            );
            CREATE TABLE IF NOT EXISTS class_certificates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                player          TEXT NOT NULL,
                class_id        TEXT NOT NULL,
                rune_name       TEXT NOT NULL,
                title           TEXT NOT NULL,
                original_wallet TEXT NOT NULL,
                block_height    INTEGER,
                block_time      TEXT,
                soulbound       INTEGER NOT NULL DEFAULT 1,
                network         TEXT NOT NULL DEFAULT 'regtest',
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(player, class_id)
            );
            CREATE TABLE IF NOT EXISTS world_features (
                room  TEXT NOT NULL,
                key   TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (room, key)
            );
            """
        )
        # Additive migrations so older dev DBs pick up new columns without a wipe.
        for col in ("nostr", "space", "fren_tag"):
            try:
                self.db.execute(f"ALTER TABLE players ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        for col, ddl in (("xp", "INTEGER NOT NULL DEFAULT 0"), ("energy", "INTEGER NOT NULL DEFAULT 100")):
            try:
                self.db.execute(f"ALTER TABLE players ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        self.db.commit()

    @staticmethod
    def level_for_xp(xp: int) -> int:
        """Simple, legible curve: level = 1 + floor(xp / 100). Level 1 at 0, level 2 at 100…"""
        return 1 + int(xp) // 100

    # --- players -----------------------------------------------------------
    def get_or_create_player(self, name: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
        if row is None:
            wallet = mock_wallet_for(name)
            self.db.execute(
                "INSERT INTO players(name, room, inventory, wallet) VALUES (?, 'entrance', '[]', ?)",
                (name, wallet),
            )
            self.db.commit()
            return {"name": name, "room": "entrance", "inventory": [], "wallet": wallet,
                    "nostr": None, "space": None, "fren_tag": None, "xp": 0, "level": 1,
                    "energy": 100, "new": True}
        xp = row["xp"] if "xp" in row.keys() else 0
        return {
            "name": row["name"],
            "room": row["room"],
            "inventory": json.loads(row["inventory"] or "[]"),
            "wallet": row["wallet"],
            "nostr": row["nostr"],
            "space": row["space"],
            "fren_tag": row["fren_tag"],
            "xp": xp,
            "level": self.level_for_xp(xp),
            "energy": row["energy"] if "energy" in row.keys() else 100,
            "new": False,
        }

    # --- attributes (XP / level / energy) ----------------------------------
    def add_xp(self, name: str, amount: int) -> dict[str, int]:
        self.db.execute("UPDATE players SET xp = xp + ?, updated_at = datetime('now') WHERE name = ?", (int(amount), name))
        self.db.commit()
        xp = self.db.execute("SELECT xp FROM players WHERE name = ?", (name,)).fetchone()["xp"]
        return {"xp": xp, "level": self.level_for_xp(xp)}

    def adjust_energy(self, name: str, delta: int) -> int:
        self.db.execute("UPDATE players SET energy = MAX(0, MIN(100, energy + ?)) WHERE name = ?", (int(delta), name))
        self.db.commit()
        return self.db.execute("SELECT energy FROM players WHERE name = ?", (name,)).fetchone()["energy"]

    def public_attributes(self, name: str) -> Optional[dict[str, Any]]:
        """What another player sees when they `examine` you — public stats only, no wallet/keys."""
        row = self.db.execute("SELECT * FROM players WHERE name = ? OR fren_tag = ?", (name, name.lstrip("@"))).fetchone()
        if not row:
            return None
        xp = row["xp"] if "xp" in row.keys() else 0
        runes = self.db.execute("SELECT COUNT(*) n FROM class_certificates WHERE player = ?", (row["name"],)).fetchone()["n"]
        return {"name": row["name"], "fren_tag": row["fren_tag"], "room": row["room"],
                "xp": xp, "level": self.level_for_xp(xp), "energy": row["energy"] if "energy" in row.keys() else 100,
                "runes": runes}

    # --- per-player memory (small, capped — feeds the LLM a tiny context) ---
    def add_memory(self, player: str, role: str, text: str, cap: int = 40) -> None:
        self.db.execute("INSERT INTO player_memory(player, role, text) VALUES (?, ?, ?)", (player, role, text[:500]))
        # keep only the most recent `cap` rows per player, so context stays cheap
        self.db.execute(
            "DELETE FROM player_memory WHERE player = ? AND id NOT IN "
            "(SELECT id FROM player_memory WHERE player = ? ORDER BY id DESC LIMIT ?)",
            (player, player, cap),
        )
        self.db.commit()

    def recent_memory(self, player: str, limit: int = 6) -> list[dict[str, str]]:
        rows = self.db.execute(
            "SELECT role, text FROM player_memory WHERE player = ? ORDER BY id DESC LIMIT ?", (player, limit)
        ).fetchall()
        return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]

    def save_player(self, name: str, room: str, inventory: list[str]) -> None:
        self.db.execute(
            "UPDATE players SET room = ?, inventory = ?, updated_at = datetime('now') WHERE name = ?",
            (room, json.dumps(inventory), name),
        )
        self.db.commit()

    def set_identity(self, name: str, field: str, value: str) -> None:
        """Link a MUD character to their external identity (nostr npub, spaces @name, @fren tag)."""
        if field not in ("nostr", "space", "fren_tag"):
            raise ValueError(f"unknown identity field: {field}")
        self.db.execute(
            f"UPDATE players SET {field} = ?, updated_at = datetime('now') WHERE name = ?",
            (value, name),
        )
        self.db.commit()

    # --- competency --------------------------------------------------------
    def has_competency(self, player: str, topic: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM competency_node WHERE player = ? AND topic = ?", (player, topic)
        ).fetchone() is not None

    def record_competency(self, player: str, topic: str, mastery: float, summary: str = "") -> None:
        self.db.execute(
            "INSERT INTO competency_node(player, topic, mastery_score, transcript_summary) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(player, topic) DO UPDATE SET "
            "mastery_score = excluded.mastery_score, transcript_summary = excluded.transcript_summary",
            (player, topic, mastery, summary),
        )
        self.db.commit()

    # --- class certificates (the soulbound rune ledger) --------------------
    def has_certificate(self, player: str, class_id: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM class_certificates WHERE player = ? AND class_id = ?", (player, class_id)
        ).fetchone() is not None

    def etch_certificate(self, player: str, class_id: str, rune_name: str, title: str,
                         wallet: str, block_height: int, block_time: Optional[str] = None) -> dict[str, Any]:
        """Idempotent: etching a class a player already holds returns the ORIGINAL record
        (original block_time + wallet preserved) — that's the provenance guarantee, in miniature."""
        existing = self.db.execute(
            "SELECT * FROM class_certificates WHERE player = ? AND class_id = ?", (player, class_id)
        ).fetchone()
        if existing:
            return dict(existing)
        block_time = block_time or _now()
        self.db.execute(
            "INSERT INTO class_certificates(player, class_id, rune_name, title, original_wallet, "
            "block_height, block_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (player, class_id, rune_name, title, wallet, block_height, block_time),
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT * FROM class_certificates WHERE player = ? AND class_id = ?", (player, class_id)
        ).fetchone()
        return dict(row)

    def list_certificates(self, player: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM class_certificates WHERE player = ? ORDER BY id", (player,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- shared world features (e.g. the vault lever) ----------------------
    def get_feature(self, room: str, key: str, default: Any = None) -> Any:
        row = self.db.execute(
            "SELECT value FROM world_features WHERE room = ? AND key = ?", (room, key)
        ).fetchone()
        return json.loads(row["value"]) if row and row["value"] is not None else default

    def set_feature(self, room: str, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO world_features(room, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(room, key) DO UPDATE SET value = excluded.value",
            (room, key, json.dumps(value)),
        )
        self.db.commit()

    # --- Fleet Ops: Duty Roster · commendations · ranks · review boards ----
    # Real admin work as a Starfleet rank climb — proof of work. See docs/FLEET-OPS.md.
    def _ensure_fleet_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT,                          -- INC-0007, REV-0012 …
                kind        TEXT NOT NULL,                 -- incident|problem|change|request|anomaly|tribunal|peer-review
                title       TEXT NOT NULL,
                detail      TEXT NOT NULL DEFAULT '',
                source      TEXT NOT NULL DEFAULT 'manual',-- manual|knowledge-flag|system|engineer|guardrail
                severity    TEXT NOT NULL DEFAULT 'normal',-- low|normal|high|critical
                status      TEXT NOT NULL DEFAULT 'open',  -- open|claimed|resolved
                verse       TEXT,
                dedup_key   TEXT,                          -- one OPEN ticket per key (ingest idempotency)
                claimed_by  TEXT,
                disposition TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now')),
                resolved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_dedup_open
                ON tickets(dedup_key) WHERE dedup_key IS NOT NULL AND status != 'resolved';
            CREATE TABLE IF NOT EXISTS ticket_events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                at        TEXT DEFAULT (datetime('now')),
                actor     TEXT NOT NULL,
                action    TEXT NOT NULL,                   -- raised|claimed|resolved|vouched|note
                note      TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_events ON ticket_events(ticket_id, id);
            CREATE TABLE IF NOT EXISTS commendations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient  TEXT NOT NULL,
                points     INTEGER NOT NULL DEFAULT 0,
                reason     TEXT NOT NULL DEFAULT '',
                ticket_id  INTEGER,
                verse      TEXT,
                awarded_by TEXT NOT NULL DEFAULT 'system',
                at         TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_commend_recipient ON commendations(recipient);
            CREATE TABLE IF NOT EXISTS rank_state (
                officer    TEXT PRIMARY KEY,
                rank_index INTEGER NOT NULL DEFAULT 0,
                verse      TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS board_votes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id  INTEGER NOT NULL,               -- the resolved mission being endorsed
                candidate  TEXT NOT NULL,                  -- the resolver vouched for
                voter      TEXT NOT NULL,
                voter_ip   TEXT,                           -- audit trail: where the vouch came from (F2)
                voter_principal TEXT,                      -- 'human' — bots are refused server-side (F3)
                note       TEXT DEFAULT '',
                at         TEXT DEFAULT (datetime('now')),
                UNIQUE(ticket_id, voter)                   -- one vouch per voter per mission
            );
            CREATE INDEX IF NOT EXISTS idx_board_candidate ON board_votes(candidate);
            CREATE INDEX IF NOT EXISTS idx_board_voter_ip ON board_votes(voter_ip);
            """
        )
        # Idempotent migration for DBs created before the audit-trail columns landed (F2).
        for col, decl in (("voter_ip", "TEXT"), ("voter_principal", "TEXT")):
            try:
                self.db.execute(f"ALTER TABLE board_votes ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # column already exists
        self.db.commit()

    _SEVERITY_POINTS = {"low": 1, "normal": 2, "high": 3, "critical": 5}

    # -- tickets (the Duty Roster) --
    def raise_ticket(self, kind: str, title: str, detail: str = "", source: str = "manual",
                     severity: str = "normal", dedup_key: Optional[str] = None,
                     verse: Optional[str] = None) -> dict[str, Any]:
        """Open a Duty Roster ticket. Idempotent on dedup_key: if an OPEN ticket with that key
        already exists, return it rather than raising a duplicate — that's the ingest guarantee."""
        if dedup_key:
            row = self.db.execute(
                "SELECT * FROM tickets WHERE dedup_key = ? AND status != 'resolved' ORDER BY id LIMIT 1",
                (dedup_key,)).fetchone()
            if row:
                return dict(row)
        try:
            cur = self.db.execute(
                "INSERT INTO tickets(kind, title, detail, source, severity, verse, dedup_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, title, detail, source, severity, verse, dedup_key))
        except sqlite3.IntegrityError:
            row = self.db.execute(
                "SELECT * FROM tickets WHERE dedup_key = ? AND status != 'resolved' ORDER BY id LIMIT 1",
                (dedup_key,)).fetchone()
            if row:
                return dict(row)
            raise
        tid = cur.lastrowid
        self.db.execute("UPDATE tickets SET code = ? WHERE id = ?", (ticket_code(kind, tid), tid))
        self.db.execute(
            "INSERT INTO ticket_events(ticket_id, actor, action, note) VALUES (?, ?, 'raised', ?)",
            (tid, source, title))
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone())

    def get_ticket(self, ticket_id: int) -> Optional[dict[str, Any]]:
        row = self.db.execute("SELECT * FROM tickets WHERE id = ?", (int(ticket_id),)).fetchone()
        return dict(row) if row else None

    def list_tickets(self, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        order = "CASE status WHEN 'open' THEN 0 WHEN 'claimed' THEN 1 ELSE 2 END, id DESC"
        if status:
            rows = self.db.execute(
                f"SELECT * FROM tickets WHERE status = ? ORDER BY {order} LIMIT ?",
                (status, int(limit))).fetchall()
        else:
            rows = self.db.execute(
                f"SELECT * FROM tickets ORDER BY {order} LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def ticket_timeline(self, ticket_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT at, actor, action, note FROM ticket_events WHERE ticket_id = ? ORDER BY id",
            (int(ticket_id),)).fetchall()
        return [dict(r) for r in rows]

    def open_ticket_count(self) -> int:
        return int(self.db.execute(
            "SELECT COUNT(*) n FROM tickets WHERE status != 'resolved'").fetchone()["n"])

    def claim_ticket(self, ticket_id: int, officer: str) -> dict[str, Any]:
        row = self.get_ticket(ticket_id)
        if not row:
            raise KeyError("no such ticket")
        if row["status"] == "resolved":
            raise ValueError("that mission is already resolved")
        self.db.execute(
            "UPDATE tickets SET status = 'claimed', claimed_by = ?, updated_at = datetime('now') WHERE id = ?",
            (officer, int(ticket_id)))
        self.db.execute(
            "INSERT INTO ticket_events(ticket_id, actor, action) VALUES (?, ?, 'claimed')",
            (int(ticket_id), officer))
        self.db.commit()
        return self.get_ticket(ticket_id)

    def resolve_ticket(self, ticket_id: int, officer: str, disposition: str = "") -> dict[str, Any]:
        row = self.get_ticket(ticket_id)
        if not row:
            raise KeyError("no such ticket")
        if row["status"] == "resolved":
            return row  # idempotent
        resolver = row["claimed_by"] or officer
        self.db.execute(
            "UPDATE tickets SET status = 'resolved', disposition = ?, claimed_by = ?, "
            "resolved_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (disposition, resolver, int(ticket_id)))
        self.db.execute(
            "INSERT INTO ticket_events(ticket_id, actor, action, note) VALUES (?, ?, 'resolved', ?)",
            (int(ticket_id), officer, disposition))
        pts = self._SEVERITY_POINTS.get(row["severity"], 2)
        self._award(resolver, pts, f"resolved {row['code'] or ticket_id}", int(ticket_id), row["verse"], "system")
        self.db.commit()
        return self.get_ticket(ticket_id)

    # -- commendations (service done — the proof of work; distinct from soulbound runes) --
    def _award(self, recipient: str, points: int, reason: str, ticket_id: Optional[int] = None,
               verse: Optional[str] = None, awarded_by: str = "system") -> None:
        self.db.execute(
            "INSERT INTO commendations(recipient, points, reason, ticket_id, verse, awarded_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (recipient, int(points), reason, ticket_id, verse, awarded_by))

    def award_commendation(self, recipient: str, points: int, reason: str = "",
                           awarded_by: str = "owner", verse: Optional[str] = None) -> dict[str, Any]:
        self._award(recipient, int(points), reason, None, verse, awarded_by)
        self.db.commit()
        return {"recipient": recipient, "points": int(points), "total": self.commendation_total(recipient)}

    def commendation_total(self, name: str) -> int:
        return int(self.db.execute(
            "SELECT COALESCE(SUM(points), 0) t FROM commendations WHERE recipient = ?", (name,)).fetchone()["t"])

    def leaderboard(self, verse: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
        if verse:
            rows = self.db.execute(
                "SELECT recipient, SUM(points) pts, COUNT(*) n FROM commendations WHERE verse = ? "
                "GROUP BY recipient ORDER BY pts DESC, recipient LIMIT ?", (verse, int(limit))).fetchall()
        else:
            rows = self.db.execute(
                "SELECT recipient, SUM(points) pts, COUNT(*) n FROM commendations "
                "GROUP BY recipient ORDER BY pts DESC, recipient LIMIT ?", (int(limit),)).fetchall()
        return [{"name": r["recipient"], "points": int(r["pts"]), "awards": int(r["n"])} for r in rows]

    # -- ranks + review boards (promotion = points earned AND witnessed) --
    def get_rank_index(self, officer: str) -> int:
        r = self.db.execute("SELECT rank_index FROM rank_state WHERE officer = ?", (officer,)).fetchone()
        return int(r["rank_index"]) if r else 0

    def set_rank_index(self, officer: str, rank_index: int, verse: Optional[str] = None) -> None:
        self.db.execute(
            "INSERT INTO rank_state(officer, rank_index, verse) VALUES (?, ?, ?) "
            "ON CONFLICT(officer) DO UPDATE SET rank_index = excluded.rank_index, "
            "verse = COALESCE(excluded.verse, rank_state.verse), updated_at = datetime('now')",
            (officer, int(rank_index), verse))
        self.db.commit()

    def known_officers(self) -> list[str]:
        """Everyone who has served: earned a commendation, holds a rank, or claimed a mission."""
        rows = self.db.execute(
            "SELECT recipient AS name FROM commendations "
            "UNION SELECT officer AS name FROM rank_state "
            "UNION SELECT claimed_by AS name FROM tickets WHERE claimed_by IS NOT NULL").fetchall()
        return sorted({r["name"] for r in rows if r["name"]})

    def vouch(self, ticket_id: int, voter: str, note: str = "",
              voter_ip: Optional[str] = None, voter_principal: str = "human") -> dict[str, Any]:
        """Endorse a resolved mission for its resolver. Integrity guards (see the Fleet Ops audit):
        - only a resolved mission with a resolver can be vouched;
        - a voter can't vouch their own work, and can't vouch the same mission twice (UNIQUE);
        - the voter must be a **known officer** who has themselves served — you can't conjure a
          fresh sockpuppet name to manufacture a promotion quorum (F2 mitigation);
        - `voter_ip` / `voter_principal` are recorded so same-source sockpuppets are auditable.
        Full closure of F2 (one *human* = one vouch) needs per-operator identity — tracked as a
        dependency. Until then, ranks are HONOR ONLY and must never authorize spend."""
        row = self.get_ticket(ticket_id)
        if not row:
            raise KeyError("no such ticket")
        if row["status"] != "resolved":
            raise ValueError("a review board only vouches resolved missions")
        candidate = row["claimed_by"]
        if not candidate:
            raise ValueError("that mission has no resolver to vouch for")
        if voter == candidate:
            raise ValueError("you can't vouch for your own work — that's the whole point")
        if voter not in set(self.known_officers()):
            raise ValueError("only an officer who has served can vouch — do a mission first, then vote")
        try:
            self.db.execute(
                "INSERT INTO board_votes(ticket_id, candidate, voter, note, voter_ip, voter_principal) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (int(ticket_id), candidate, voter, note, voter_ip, voter_principal))
        except sqlite3.IntegrityError:
            raise ValueError("you've already vouched this mission")
        self.db.execute(
            "INSERT INTO ticket_events(ticket_id, actor, action, note) VALUES (?, ?, 'vouched', ?)",
            (int(ticket_id), voter, note))
        self.db.commit()
        return {"ticket_id": int(ticket_id), "candidate": candidate, "vouches": self.vouch_count(candidate)}

    def vouch_count(self, candidate: str) -> int:
        return int(self.db.execute(
            "SELECT COUNT(DISTINCT voter) n FROM board_votes WHERE candidate = ?", (candidate,)).fetchone()["n"])

    def close(self) -> None:
        self.db.close()


# --------------------------------------------------------------------------- #
# Postgres backend — the production path onto the real DB-2 schema
# --------------------------------------------------------------------------- #
class PostgresWorldStore:
    """Maps the same operations onto DB-2 (02-db2-gamestate.sql + 03-class-runes.sql).

    SCAFFOLDING: the SQL shape is real and schema-aligned, but this path is validated only when
    the Podman stack + Postgres are up. It lazy-imports `psycopg` so dev never needs the driver.
    Identity: dev keys players by name; in production `players.name` maps to a `users` row and the
    real wallet/pubkey, and `class_certificates` carries the true etch txid/height/time from
    `services/bitcoin-bridge/runes.py`. Wire that mapping here when the stack lands.
    """

    def __init__(self, dsn: str):
        try:
            import psycopg  # noqa: F401  (prod-only dependency)
        except Exception as e:  # pragma: no cover - dev never hits this
            raise RuntimeError(
                "PostgresWorldStore needs `psycopg` (production only). Use the SQLite dev backend, "
                "or install the driver inside the stack."
            ) from e
        self._psycopg = __import__("psycopg")
        self.dsn = dsn
        # TODO(prod): connection pool; ensure a `users` row per player; resolve topic_id/class_id
        # against `topics`/`class_catalog`; write competency_node + class_certificates with the
        # real on-chain provenance from runes.py. Method signatures match SqliteWorldStore exactly.

    def _conn(self):
        return self._psycopg.connect(self.dsn)

    # The methods below mirror SqliteWorldStore's signatures 1:1 so callers are backend-agnostic.
    # Left as clearly-marked TODOs until the stack is up to validate the SQL against live DB-2.
    def get_or_create_player(self, name: str) -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.get_or_create_player — wire against DB-2 users/players")

    def save_player(self, name: str, room: str, inventory: list[str]) -> None:
        raise NotImplementedError("PostgresWorldStore.save_player — wire against DB-2")

    def has_competency(self, player: str, topic: str) -> bool:
        raise NotImplementedError

    def record_competency(self, player: str, topic: str, mastery: float, summary: str = "") -> None:
        raise NotImplementedError("PostgresWorldStore.record_competency — INSERT competency_node")

    def has_certificate(self, player: str, class_id: str) -> bool:
        raise NotImplementedError

    def etch_certificate(self, player: str, class_id: str, rune_name: str, title: str,
                         wallet: str, block_height: int, block_time: Optional[str] = None) -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.etch_certificate — INSERT class_certificates via runes.py")

    def list_certificates(self, player: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_feature(self, room: str, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def set_feature(self, room: str, key: str, value: Any) -> None:
        raise NotImplementedError

    @staticmethod
    def level_for_xp(xp: int) -> int:
        return 1 + int(xp) // 100

    def add_xp(self, name: str, amount: int) -> dict[str, int]:
        raise NotImplementedError("PostgresWorldStore.add_xp — UPDATE players SET xp")

    def adjust_energy(self, name: str, delta: int) -> int:
        raise NotImplementedError

    def public_attributes(self, name: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def add_memory(self, player: str, role: str, text: str, cap: int = 40) -> None:
        raise NotImplementedError("PostgresWorldStore.add_memory — INSERT player_memory (or memory_node)")

    def recent_memory(self, player: str, limit: int = 6) -> list[dict[str, str]]:
        raise NotImplementedError

    # --- Fleet Ops (docs/FLEET-OPS.md) — mirror SqliteWorldStore 1:1 ---------
    # DB-2 lands these as first-class tables (infra/postgres/04-db2-fleet-ops.sql, TODO); until the
    # stack is up to validate the SQL, these raise so a mis-set backend fails loud, never silently.
    def raise_ticket(self, kind: str, title: str, detail: str = "", source: str = "manual",
                     severity: str = "normal", dedup_key: Optional[str] = None,
                     verse: Optional[str] = None) -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.raise_ticket — INSERT tickets (DB-2 fleet-ops)")

    def get_ticket(self, ticket_id: int) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def list_tickets(self, status: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError

    def ticket_timeline(self, ticket_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    def open_ticket_count(self) -> int:
        raise NotImplementedError

    def claim_ticket(self, ticket_id: int, officer: str) -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.claim_ticket — UPDATE tickets")

    def resolve_ticket(self, ticket_id: int, officer: str, disposition: str = "") -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.resolve_ticket — UPDATE tickets + award commendation")

    def award_commendation(self, recipient: str, points: int, reason: str = "",
                           awarded_by: str = "owner", verse: Optional[str] = None) -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.award_commendation — INSERT commendations")

    def commendation_total(self, name: str) -> int:
        raise NotImplementedError

    def leaderboard(self, verse: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_rank_index(self, officer: str) -> int:
        raise NotImplementedError

    def set_rank_index(self, officer: str, rank_index: int, verse: Optional[str] = None) -> None:
        raise NotImplementedError

    def known_officers(self) -> list[str]:
        raise NotImplementedError

    def vouch(self, ticket_id: int, voter: str, note: str = "",
              voter_ip: Optional[str] = None, voter_principal: str = "human") -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.vouch — INSERT board_votes")

    def vouch_count(self, candidate: str) -> int:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def open_store() -> Any:
    """Return the right backend for the environment.

    Production: set `PA_GAMESTATE_BACKEND=postgres` (uses `PA_DB2_URL`).
    Dev (default): SQLite at `PA_GAMESTATE_SQLITE` or `data/gamestate.dev.sqlite`.
    """
    backend = os.environ.get("PA_GAMESTATE_BACKEND", "sqlite").strip().lower()
    if backend == "postgres":
        dsn = os.environ.get("PA_DB2_URL", "")
        if not dsn:
            raise RuntimeError("PA_GAMESTATE_BACKEND=postgres but PA_DB2_URL is empty.")
        return PostgresWorldStore(dsn)
    path = os.environ.get("PA_GAMESTATE_SQLITE", os.path.join("data", "gamestate.dev.sqlite"))
    return SqliteWorldStore(path)
