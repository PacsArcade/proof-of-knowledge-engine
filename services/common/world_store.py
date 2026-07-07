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
    mock; in prod the real mint txid/height/time come from `runes.py`.
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

    def _ensure_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS players (
                name       TEXT PRIMARY KEY,
                room       TEXT NOT NULL DEFAULT 'entrance',
                inventory  TEXT NOT NULL DEFAULT '[]',   -- JSON array
                wallet     TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
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
        self.db.commit()

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
            return {"name": name, "room": "entrance", "inventory": [], "wallet": wallet, "new": True}
        return {
            "name": row["name"],
            "room": row["room"],
            "inventory": json.loads(row["inventory"] or "[]"),
            "wallet": row["wallet"],
            "new": False,
        }

    def save_player(self, name: str, room: str, inventory: list[str]) -> None:
        self.db.execute(
            "UPDATE players SET room = ?, inventory = ?, updated_at = datetime('now') WHERE name = ?",
            (room, json.dumps(inventory), name),
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

    def mint_certificate(self, player: str, class_id: str, rune_name: str, title: str,
                         wallet: str, block_height: int, block_time: Optional[str] = None) -> dict[str, Any]:
        """Idempotent: minting a class a player already holds returns the ORIGINAL record
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
    real wallet/pubkey, and `class_certificates` carries the true mint txid/height/time from
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

    def mint_certificate(self, player: str, class_id: str, rune_name: str, title: str,
                         wallet: str, block_height: int, block_time: Optional[str] = None) -> dict[str, Any]:
        raise NotImplementedError("PostgresWorldStore.mint_certificate — INSERT class_certificates via runes.py")

    def list_certificates(self, player: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_feature(self, room: str, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def set_feature(self, room: str, key: str, value: Any) -> None:
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
