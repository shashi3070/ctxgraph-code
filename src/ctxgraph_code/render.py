from __future__ import annotations

from collections import defaultdict
from typing import Optional

from ctxgraph_code.graph.models import Node
from ctxgraph_code.graph.storage import Storage


def render_overview(storage: Storage, max_files: int = 30) -> str:
    all_nodes = storage.get_all_nodes()
    file_nodes = [n for n in all_nodes if n.type == "file"][:max_files]

    lines = ["Project Overview", ""]
    for node in file_nodes:
        summary = node.summary or ""
        lines.append(f"  [F] {node.path or node.name}")
        if summary:
            lines.append(f"      {summary}")

        children = [
            n for n in all_nodes
            if n.parent_id == node.id and n.type in ("class", "function")
        ]
        if children:
            names = [c.name for c in children[:8]]
            lines.append(f"      Symbols: {', '.join(names)}")

    lines.append("")
    return "\n".join(lines)


def render_deps(storage: Storage, file_path: str) -> str:
    all_nodes = storage.get_all_nodes()
    all_edges = storage.get_all_edges()
    node_id = f"file:{file_path}"

    node = storage.get_node(node_id)
    if not node:
        return f"File not found in graph: {file_path}"

    imports = []
    imported_by = []
    for e in all_edges:
        if e.source_id == node_id and e.relation == "imports":
            target = storage.get_node(e.target_id)
            if target:
                imports.append(target.path or target.name)
        if e.target_id == node_id and e.relation == "imports":
            source = storage.get_node(e.source_id)
            if source:
                imported_by.append(source.path or source.name)

    lines = [f"Dependencies for: {file_path}", ""]

    symbols = [n for n in all_nodes if n.parent_id == node_id]
    if symbols:
        class_names = [n.name for n in symbols if n.type == "class"]
        func_names = [n.name for n in symbols if n.type == "function"]
        if class_names:
            lines.append(f"  Classes: {', '.join(class_names)}")
        if func_names:
            lines.append(f"  Functions: {', '.join(func_names)}")
        lines.append("")

    if imports:
        lines.append("  Imports:")
        for imp in sorted(imports):
            lines.append(f"    -> {imp}")
    else:
        lines.append("  Imports: (none)")

    if imported_by:
        lines.append("")
        lines.append("  Imported by:")
        for imp in sorted(imported_by):
            lines.append(f"    <- {imp}")

    calls_made = []
    called_by = []
    for e in all_edges:
        if e.source_id == node_id and e.relation == "calls":
            target = storage.get_node(e.target_id)
            if target:
                calls_made.append(f"{target.name} ({target.path})")
        if e.target_id == node_id and e.relation == "calls":
            source = storage.get_node(e.source_id)
            if source:
                called_by.append(f"{source.name} ({source.path})")

    if calls_made:
        lines.append("")
        lines.append("  Calls:")
        for c in sorted(calls_made):
            lines.append(f"    -> {c}")

    if called_by:
        lines.append("")
        lines.append("  Called by:")
        for c in sorted(called_by):
            lines.append(f"    <- {c}")

    return "\n".join(lines)


def render_usedby(storage: Storage, file_path: str) -> str:
    node_id = f"file:{file_path}"
    node = storage.get_node(node_id)
    if not node:
        return f"File not found in graph: {file_path}"

    all_edges = storage.get_all_edges()

    imported_by = []
    called_by = []
    for e in all_edges:
        if e.target_id == node_id and e.relation == "imports":
            source = storage.get_node(e.source_id)
            if source:
                imported_by.append(source.path or source.name)
        if e.target_id == node_id and e.relation == "calls":
            source = storage.get_node(e.source_id)
            if source:
                called_by.append(f"{source.name} ({source.path})")

    lines = [f"References to: {file_path}", ""]
    if imported_by:
        lines.append(f"  Imported by ({len(imported_by)}):")
        for ref in sorted(imported_by):
            lines.append(f"    {ref}")
    else:
        lines.append("  Imported by: (none)")

    if called_by:
        lines.append("")
        lines.append(f"  Called by ({len(called_by)}):")
        for ref in sorted(called_by):
            lines.append(f"    {ref}")

    return "\n".join(lines)


def render_symbols(storage: Storage, file_path: str) -> str:
    node_id = f"file:{file_path}"
    node = storage.get_node(node_id)
    if not node:
        return f"File not found in graph: {file_path}"

    all_nodes = storage.get_all_nodes()
    symbols = [n for n in all_nodes if n.parent_id == node_id]

    if not symbols:
        return f"No symbols found in: {file_path}"

    lines = [f"Symbols in: {file_path}", ""]
    for s in symbols:
        tag = "[C]" if s.type == "class" else "[M]"
        summary = f" - {s.summary}" if s.summary else ""
        lines.append(f"  {tag} {s.name} (line {s.lineno}){summary}")
        if s.type == "class":
            methods = [n for n in all_nodes if n.parent_id == s.id]
            if methods:
                for m in methods:
                    ms = f" - {m.summary}" if m.summary else ""
                    lines.append(f"      [M] {m.name} (line {m.lineno}){ms}")

    return "\n".join(lines)


def render_context(storage: Storage, query: str, max_nodes: int = 15) -> str:
    from ctxgraph_code.graph.query import search_relevant_nodes

    ranked = search_relevant_nodes(storage, query, max_nodes)
    if not ranked:
        return f"No context found for: {query}"

    all_nodes = storage.get_all_nodes()
    all_edges = storage.get_all_edges()

    node_ids = {n.id for n, _ in ranked}
    relevant_edges = [
        e for e in all_edges
        if e.source_id in node_ids and e.target_id in node_ids
    ]

    lines = [f"Context: {query}", ""]

    file_nodes = [n for n, _ in ranked if n.type == "file"]
    symbol_nodes = [n for n, _ in ranked if n.type != "file"]

    for node in file_nodes:
        lines.append(f"  [F] {node.path or node.name}")
        if node.summary:
            lines.append(f"      {node.summary}")
        children = [
            n for n in all_nodes
            if n.parent_id == node.id and n.type in ("class", "function")
        ]
        if children:
            child_names = [c.name for c in children[:10]]
            lines.append(f"      Symbols: {', '.join(child_names)}")

    if symbol_nodes:
        lines.append("")
        for node in symbol_nodes:
            tag = "[C]" if node.type == "class" else "[M]"
            name = node.name
            if node.parent_id and "::" not in node.parent_id:
                parent_short = node.parent_id.split(":")[-1] if ":" in node.parent_id else node.parent_id
                name = f"{parent_short}.{node.name}"
            lines.append(f"  {tag} {name}")
            if node.summary:
                lines.append(f"      {node.summary}")

    import_edges = [(s, t) for s, t, r in [(e.source_id, e.target_id, e.relation) for e in relevant_edges] if r == "imports"]
    call_edges = [(s, t) for s, t, r in [(e.source_id, e.target_id, e.relation) for e in relevant_edges] if r == "calls"]

    if import_edges or call_edges:
        lines.append("")
        if import_edges:
            lines.append("  Dependencies:")
            for src, tgt in import_edges[:10]:
                src_name = _short_name(src, {n.id: n for n in all_nodes})
                tgt_name = _short_name(tgt, {n.id: n for n in all_nodes})
                if src_name and tgt_name:
                    lines.append(f"    {src_name} -> {tgt_name}")
        if call_edges:
            lines.append("  Calls:")
            for src, tgt in call_edges[:10]:
                src_name = _short_name(src, {n.id: n for n in all_nodes})
                tgt_name = _short_name(tgt, {n.id: n for n in all_nodes})
                if src_name and tgt_name:
                    lines.append(f"    {src_name} -> {tgt_name}")

    return "\n".join(lines)


def _short_name(node_id: str, node_map: dict[str, Node]) -> Optional[str]:
    if node_id in node_map:
        n = node_map[node_id]
        if n.type == "file":
            return n.path or n.name
        return f"{n.path}:{n.name}" if n.path else n.name
    return node_id.split(":")[-1] if ":" in node_id else node_id
