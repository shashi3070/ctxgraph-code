from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from ctxgraph_code.graph.models import Edge, Graph, Node


def analyze_imports(file_path: Path, root_path: Path) -> Graph:
    graph = Graph()
    rel_path = _relative_path(file_path, root_path)
    file_node_id = f"file:{rel_path}"

    graph.add_node(
        Node(
            id=file_node_id,
            type="file",
            name=file_path.name,
            path=rel_path,
            summary=None,
            importance=0.5,
            size_bytes=file_path.stat().st_size,
        )
    )

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return graph

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_import_target(alias.name, root_path)
                if target:
                    _add_import_edge(graph, rel_path, file_node_id, target, alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.level and node.level > 0:
                target = _resolve_relative_import(
                    node.module, node.level, rel_path, root_path
                )
            else:
                target = _resolve_import_target(node.module, root_path)

            if target:
                for alias in node.names:
                    symbol_name = alias.asname or alias.name
                    edge_label = f"{node.module}.{alias.name}"
                    _add_import_edge(
                        graph, rel_path, file_node_id, target, edge_label
                    )

    return graph


def _add_import_edge(
    graph: Graph,
    source_rel: str,
    source_id: str,
    target_rel: str,
    label: str,
):
    target_id = f"file:{target_rel}"
    if target_id not in graph.nodes:
        graph.add_node(
            Node(
                id=target_id,
                type="file",
                name=Path(target_rel).name,
                path=target_rel,
                summary=None,
                importance=0.3,
                size_bytes=0,
            )
        )
    graph.add_edge(
        Edge(
            source_id=source_id,
            target_id=target_id,
            relation="imports",
            weight=1.0,
        )
    )


def _resolve_import_target(module_name: str, root_path: Path) -> Optional[str]:
    package_path = module_name.replace(".", "/")
    root_name = root_path.name
    extensions = [".py", ".pyw"]

    candidates = [package_path]
    parts = module_name.split(".")
    if len(parts) > 1 and parts[0] == root_name:
        candidates.append("/".join(parts[1:]))

    for base in candidates:
        for ext in extensions:
            candidate = f"{base}{ext}"
            if _exists_in_project(candidate, root_path):
                return candidate
            init_candidate = f"{base}/__init__{ext}"
            if _exists_in_project(init_candidate, root_path):
                return init_candidate
    return None


def _resolve_relative_import(
    module_name: str, level: int, source_rel: str, root_path: Path
) -> Optional[str]:
    parts = Path(source_rel).parts
    if level > len(parts):
        return None
    base = "/".join(parts[: len(parts) - level])
    if module_name:
        base = f"{base}/{module_name.replace('.', '/')}"
    extensions = [".py", ".pyw"]
    for ext in extensions:
        candidate = f"{base}{ext}"
        if _exists_in_project(candidate, root_path):
            return candidate
        init_candidate = f"{base}/__init__{ext}"
        if _exists_in_project(init_candidate, root_path):
            return init_candidate
    return None


def _exists_in_project(candidate_path: str, root_path: Path) -> bool:
    full = root_path / candidate_path
    return full.exists()


def _relative_path(file_path: Path, root_path: Path) -> str:
    try:
        return str(file_path.relative_to(root_path)).replace("\\", "/")
    except ValueError:
        return file_path.name
