from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from ctxgraph_code.analyzers.python.importer import analyze_imports
from ctxgraph_code.analyzers.python.semantic import enrich_node_summary
from ctxgraph_code.analyzers.python.symbols import analyze_symbols
from ctxgraph_code.exclude.patterns import should_exclude
from ctxgraph_code.graph.models import Graph
from ctxgraph_code.graph.storage import Storage


def build_graph(
    repo_path: str | Path,
    db_path: Optional[str | Path] = None,
    exclude_patterns: Optional[list[str]] = None,
    extensions: Optional[list[str]] = None,
) -> dict:
    repo_path = Path(repo_path).resolve()
    if db_path is None:
        db_path = repo_path / ".ctxgraph" / "graph.db"

    db_path = Path(db_path)
    start = time.time()

    storage = Storage(db_path)
    storage.connect()
    combined = Graph()
    stats = {"files_analyzed": 0, "files_skipped": 0, "errors": 0}

    exts = set(extensions or [".py"])
    scan_files = [f for f in repo_path.rglob("*") if f.suffix in exts and f.is_file()]
    for file_path in scan_files:
        if should_exclude(file_path, repo_path, exclude_patterns):
            stats["files_skipped"] += 1
            continue

        try:
            import_graph = analyze_imports(file_path, repo_path)
            combined.merge(import_graph)

            symbol_graph = analyze_symbols(file_path, repo_path)
            combined.merge(symbol_graph)

            for node in combined.nodes.values():
                if node.path and node.path in str(file_path):
                    if not node.summary:
                        summary = enrich_node_summary(node, file_path)
                        if summary:
                            node.summary = summary

            stats["files_analyzed"] += 1
        except Exception:
            stats["errors"] += 1

    storage.save_graph(combined)
    storage.save_metadata("build_time", str(time.time()))
    storage.save_metadata("repo_path", str(repo_path))
    storage.save_metadata("file_count", str(stats["files_analyzed"]))
    storage.close()

    elapsed = time.time() - start
    stats["elapsed_seconds"] = round(elapsed, 2)
    stats["total_nodes"] = len(combined.nodes)
    stats["total_edges"] = len(combined.edges)

    return stats


def get_storage(repo_path: str | Path) -> Optional[Storage]:
    db_path = Path(repo_path) / ".ctxgraph" / "graph.db"
    if not db_path.exists():
        return None
    storage = Storage(db_path)
    storage.connect()
    return storage
