"""blackboard.py — the swarm's shared memory (DB-2, the Blackboard). 💜

SCAFFOLDING / STUB. Structurally real, but no real DB calls yet — every place that
touches Postgres is marked with a TODO.

The Blackboard is DB-2 (`postgres-gamestate`). Per docs/CONVENTIONS.md §3–§4, the five
runtime agents (oracle, architect, custodian, archivist, warden) coordinate here instead
of relying on their context windows. This module is the thin, shared read/write layer over
the three coordination tables:

    memory_node       — a fact / observation / artifact the swarm remembers
    memory_edge       — a typed relationship between two memory_nodes
    competency_node   — a learner's demonstrated mastery of a topic (Oracle awards these)

Tier: WARM. These are node-local DB-2 reads/writes; keep them fast. Never reach across the
network (COLD) from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# DB-2 connection string. See .env.example / CONVENTIONS §6.
#   postgresql://arcade:…@postgres-gamestate:5432/gamestate
PA_DB2_URL = os.environ.get("PA_DB2_URL", "postgresql://arcade:change-me@postgres-gamestate:5432/gamestate")


# --------------------------------------------------------------------------- #
# Record shapes (mirror the DB-2 schema; the real DDL lives in infra/postgres) #
# --------------------------------------------------------------------------- #

@dataclass
class MemoryNode:
    """A single unit of shared memory on the Blackboard."""
    kind: str                          # e.g. "observation", "room_spec", "quarantine"
    payload: dict[str, Any]            # arbitrary JSON body
    author_agent: str                  # which swarm agent wrote it (oracle, architect, …)
    id: Optional[str] = None           # assigned by DB-2 on insert
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MemoryEdge:
    """A typed relationship between two memory_nodes (a tiny knowledge graph)."""
    src_id: str
    dst_id: str
    relation: str                      # e.g. "targets_gap", "quarantines", "derived_from"
    author_agent: str
    id: Optional[str] = None


@dataclass
class CompetencyNode:
    """A learner's demonstrated mastery of a topic. Only the Oracle should award these."""
    user_id: str
    topic: str                         # e.g. "self-custody", "proof-of-work"
    level: int                         # 0=unseen … higher=mastered
    evidence: dict[str, Any]           # transcript refs / attendance code / interview summary
    awarded_by: str = "oracle"
    id: Optional[str] = None
    awarded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Blackboard client                                                           #
# --------------------------------------------------------------------------- #

class Blackboard:
    """Read/write helper over DB-2's coordination tables.

    Usage (once implemented):
        bb = Blackboard()
        await bb.connect()
        node = await bb.write_memory_node(MemoryNode(kind="observation", payload={...},
                                                     author_agent="architect"))
    """

    def __init__(self, dsn: str = PA_DB2_URL) -> None:
        self.dsn = dsn
        self._pool = None              # TODO: asyncpg / psycopg pool

    async def connect(self) -> None:
        # TODO: open an asyncpg pool to PA_DB2_URL. Fail fast if DB-2 is unreachable —
        #       the Blackboard is HOT-adjacent and must be present for the swarm to run.
        raise NotImplementedError("TODO: connect to DB-2 (postgres-gamestate)")

    # -- memory_node -------------------------------------------------------- #

    async def write_memory_node(self, node: MemoryNode) -> MemoryNode:
        """Insert a memory_node and return it with its DB-assigned id."""
        # TODO: INSERT INTO memory_node (kind, payload, author_agent, created_at)
        #       VALUES (...) RETURNING id;
        raise NotImplementedError("TODO: INSERT into memory_node")

    async def read_memory_nodes(self, kind: Optional[str] = None, limit: int = 100) -> list[MemoryNode]:
        """Read recent memory_nodes, optionally filtered by kind."""
        # TODO: SELECT … FROM memory_node [WHERE kind = $1] ORDER BY created_at DESC LIMIT $2;
        raise NotImplementedError("TODO: SELECT from memory_node")

    # -- memory_edge -------------------------------------------------------- #

    async def write_memory_edge(self, edge: MemoryEdge) -> MemoryEdge:
        """Link two memory_nodes with a typed relation."""
        # TODO: INSERT INTO memory_edge (src_id, dst_id, relation, author_agent)
        #       VALUES (...) RETURNING id;
        raise NotImplementedError("TODO: INSERT into memory_edge")

    async def read_edges_from(self, src_id: str) -> list[MemoryEdge]:
        """All edges originating at a given memory_node."""
        # TODO: SELECT … FROM memory_edge WHERE src_id = $1;
        raise NotImplementedError("TODO: SELECT from memory_edge")

    # -- competency_node ---------------------------------------------------- #

    async def award_competency(self, comp: CompetencyNode) -> CompetencyNode:
        """Award (or upgrade) a learner's competency. Oracle-only in practice."""
        # TODO: UPSERT into competency_node keyed on (user_id, topic); keep the highest level.
        #       This is what the Oracle writes when pacbot confirms demonstrated mastery.
        raise NotImplementedError("TODO: UPSERT competency_node")

    async def read_competencies(self, user_id: str) -> list[CompetencyNode]:
        """A learner's full competency map — the Oracle & Architect both read this."""
        # TODO: SELECT … FROM competency_node WHERE user_id = $1;
        raise NotImplementedError("TODO: SELECT from competency_node")


# --------------------------------------------------------------------------- #
# Convenience singletons the agents import                                    #
# --------------------------------------------------------------------------- #

_blackboard: Optional[Blackboard] = None


def get_blackboard() -> Blackboard:
    """Process-wide Blackboard handle shared by all five agents."""
    global _blackboard
    if _blackboard is None:
        _blackboard = Blackboard()
    return _blackboard
