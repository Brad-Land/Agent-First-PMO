"""A small property graph stored in SQLite.

Nodes have a label and JSON properties; edges are typed (src)-[REL]->(dst).
Running on SQLite keeps the proof of concept to one local file with no
server. The GraphStore methods are the seam for a hosted graph database later.

Node labels: Person, Meeting, Segment, Draft, WorkItem
Relationships:
  (Person)-[:ATTENDED]->(Meeting)
  (Segment)-[:PART_OF]->(Meeting)
  (Segment)-[:SPOKEN_BY]->(Person)
  (Draft)-[:DERIVED_FROM]->(Segment)
  (Draft)-[:RAISED_BY]->(Person)
  (Draft)-[:FROM_MEETING]->(Meeting)
  (Draft)-[:BECAME]->(WorkItem)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    props TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_label ON nodes(label);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    props TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (src, rel, dst)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, rel);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'edited', 'rejected')),
    reviewer TEXT,
    reason TEXT,
    original_text TEXT,
    final_text TEXT,
    at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GraphStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # nodes -----------------------------------------------------------------
    def upsert_node(self, node_id: str, label: str, **props: Any) -> None:
        existing = self.get_node(node_id)
        merged = {**(existing["props"] if existing else {}), **props}
        self.conn.execute(
            "INSERT INTO nodes(id, label, props, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET props = excluded.props",
            (node_id, label, json.dumps(merged), now()),
        )

    def get_node(self, node_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return _node(row) if row else None

    def find_nodes(self, label: str, **where: Any) -> list[dict]:
        sql = "SELECT * FROM nodes WHERE label = ?"
        args: list[Any] = [label]
        for key, value in where.items():
            sql += f" AND json_extract(props, '$.{key}') = ?"
            args.append(value)
        sql += " ORDER BY created_at, id"
        return [_node(r) for r in self.conn.execute(sql, args)]

    def delete_node(self, node_id: str) -> None:
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

    # edges -----------------------------------------------------------------
    def add_edge(self, src: str, rel: str, dst: str, **props: Any) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO edges(src, rel, dst, props) VALUES (?, ?, ?, ?)",
            (src, rel, dst, json.dumps(props)),
        )

    def out(self, node_id: str, rel: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT n.* FROM edges e JOIN nodes n ON n.id = e.dst WHERE e.src = ? AND e.rel = ? ORDER BY n.id",
            (node_id, rel),
        )
        return [_node(r) for r in rows]

    def inbound(self, node_id: str, rel: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT n.* FROM edges e JOIN nodes n ON n.id = e.src WHERE e.dst = ? AND e.rel = ? ORDER BY n.id",
            (node_id, rel),
        )
        return [_node(r) for r in rows]

    # transactions ------------------------------------------------------------
    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, exc_type, *_: Any) -> None:
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()


def _node(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "props": json.loads(row["props"]),
        "created_at": row["created_at"],
    }
