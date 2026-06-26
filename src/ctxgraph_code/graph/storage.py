from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ctxgraph_code.graph.models import Edge, Graph, Node


def _table_schema() -> str:
    return """
    CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        path TEXT,
        parent_id TEXT,
        summary TEXT,
        importance REAL DEFAULT 0.5,
        size_bytes INTEGER DEFAULT 0,
        lineno INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS edges (
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        weight REAL DEFAULT 1.0,
        PRIMARY KEY (source_id, target_id, relation)
    );

    CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
    CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
    CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);

    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript(_table_schema())
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        return self._conn

    def update_node_summary(self, node_id: str, summary: str):
        self.conn.execute(
            "UPDATE nodes SET summary = ? WHERE id = ?", (summary, node_id)
        )
        self.conn.commit()

    def save_graph(self, graph: Graph):
        nodes_data = [
            (n.id, n.type, n.name, n.path, n.parent_id, n.summary,
             n.importance, n.size_bytes, n.lineno)
            for n in graph.nodes.values()
        ]
        if nodes_data:
            self.conn.executemany(
                """INSERT OR REPLACE INTO nodes
                   (id, type, name, path, parent_id, summary, importance, size_bytes, lineno)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                nodes_data,
            )

        edges_data = [
            (e.source_id, e.target_id, e.relation, e.weight)
            for e in graph.edges
        ]
        if edges_data:
            self.conn.executemany(
                """INSERT OR REPLACE INTO edges
                   (source_id, target_id, relation, weight)
                   VALUES (?, ?, ?, ?)""",
                edges_data,
            )
        self.conn.commit()

    def get_node(self, node_id: str) -> Optional[Node]:
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return None
        return Node(
            id=row["id"],
            type=row["type"],
            name=row["name"],
            path=row["path"],
            parent_id=row["parent_id"],
            summary=row["summary"],
            importance=row["importance"],
            size_bytes=row["size_bytes"],
            lineno=row["lineno"],
        )

    def search_nodes(self, text: str) -> list[Node]:
        query = f"%{text}%"
        rows = self.conn.execute(
            """SELECT * FROM nodes WHERE
               name LIKE ? OR summary LIKE ? OR path LIKE ?
               ORDER BY importance DESC
               LIMIT 50""",
            (query, query, query),
        ).fetchall()
        return [
            Node(
                id=r["id"],
                type=r["type"],
                name=r["name"],
                path=r["path"],
                parent_id=r["parent_id"],
                summary=r["summary"],
                importance=r["importance"],
                size_bytes=r["size_bytes"],
                lineno=r["lineno"],
            )
            for r in rows
        ]

    def get_edges_for_nodes(self, node_ids: set[str]) -> list[Edge]:
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM edges WHERE
               source_id IN ({placeholders}) OR target_id IN ({placeholders})""",
            list(node_ids) + list(node_ids),
        ).fetchall()
        return [
            Edge(
                source_id=r["source_id"],
                target_id=r["target_id"],
                relation=r["relation"],
                weight=r["weight"],
            )
            for r in rows
        ]

    def get_all_nodes(self) -> list[Node]:
        rows = self.conn.execute("SELECT * FROM nodes").fetchall()
        return [
            Node(
                id=r["id"],
                type=r["type"],
                name=r["name"],
                path=r["path"],
                parent_id=r["parent_id"],
                summary=r["summary"],
                importance=r["importance"],
                size_bytes=r["size_bytes"],
                lineno=r["lineno"],
            )
            for r in rows
        ]

    def get_all_edges(self) -> list[Edge]:
        rows = self.conn.execute("SELECT * FROM edges").fetchall()
        return [
            Edge(
                source_id=r["source_id"],
                target_id=r["target_id"],
                relation=r["relation"],
                weight=r["weight"],
            )
            for r in rows
        ]

    def stats(self) -> dict:
        node_count = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        type_counts = self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type"
        ).fetchall()
        return {
            "nodes": node_count,
            "edges": edge_count,
            "types": {r["type"]: r["cnt"] for r in type_counts},
        }

    def delete_nodes_for_file(self, file_path: str):
        """Remove all nodes and edges belonging to a file (for incremental rebuild)."""
        cursor = self.conn.execute(
            "SELECT id FROM nodes WHERE path = ?", (file_path,)
        )
        node_ids = [r[0] for r in cursor.fetchall()]
        if not node_ids:
            return
        placeholders = ",".join("?" for _ in node_ids)
        self.conn.execute(
            "DELETE FROM edges WHERE source_id IN ({}) OR target_id IN ({})".format(
                placeholders, placeholders
            ),
            node_ids + node_ids,
        )
        self.conn.execute(
            f"DELETE FROM nodes WHERE id IN ({placeholders})", node_ids
        )
        self.conn.commit()

    def get_nodes_by_file_path(self, file_path: str) -> list[Node]:
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE path = ?", (file_path,)
        ).fetchall()
        return [
            Node(
                id=r["id"],
                type=r["type"],
                name=r["name"],
                path=r["path"],
                parent_id=r["parent_id"],
                summary=r["summary"],
                importance=r["importance"],
                size_bytes=r["size_bytes"],
                lineno=r["lineno"],
            )
            for r in rows
        ]

    def get_file_paths(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT path FROM nodes WHERE type = 'file' AND path IS NOT NULL"
        ).fetchall()
        return [r[0] for r in rows]

    def get_content_hash(self, file_path: str) -> Optional[str]:
        hashes_json = self.get_metadata("content_hashes")
        if not hashes_json:
            return None
        try:
            import json
            stored = json.loads(hashes_json)
            return stored.get(file_path)
        except (json.JSONDecodeError, OSError):
            return None

    def save_metadata(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def get_metadata(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
