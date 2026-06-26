from __future__ import annotations

from typing import Optional

from ctxgraph_code.graph.storage import Storage


class MermaidError(Exception):
    pass


def render_mermaid(
    storage: Storage,
    output_type: str = "classDiagram",
    max_nodes: int = 50,
) -> str:
    output_type = output_type or "classDiagram"
    supported = {"classDiagram", "flowchart", "sequence"}
    if output_type not in supported:
        raise MermaidError(
            f"Unsupported diagram type '{output_type}'. "
            f"Choose from: {', '.join(sorted(supported))}"
        )

    all_nodes = storage.get_all_nodes()
    all_edges = storage.get_all_edges()

    if output_type == "classDiagram":
        return _render_class_diagram(all_nodes, all_edges, max_nodes)
    elif output_type == "flowchart":
        return _render_flowchart(all_nodes, all_edges, max_nodes)
    elif output_type == "sequence":
        return _render_sequence(all_nodes, all_edges, max_nodes)
    return ""


def _safe_id(name: str) -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe or "node"


def _render_class_diagram(nodes: list, edges: list, max_nodes: int) -> str:
    lines = ["classDiagram"]
    added = 0

    class_nodes = [n for n in nodes if n.type == "class"]
    file_nodes = [n for n in nodes if n.type == "file"]

    for cls in class_nodes[:max_nodes]:
        nid = _safe_id(cls.name)
        lines.append(f"    class {nid} {{")
        if cls.summary:
            lines.append(f"        +{cls.summary}")
        lines.append("    }")
        added += 1
        if added >= max_nodes:
            break

    if added < max_nodes:
        remaining = max_nodes - added
        for f in file_nodes[:remaining]:
            nid = _safe_id(f.name)
            label = f.path or f.name
            lines.append(f"    class {nid} {{")
            lines.append(f"        +File: {label}")
            if f.summary:
                lines.append(f"        +{f.summary}")
            lines.append("    }")

    inheritance_edges = [e for e in edges if e.relation == "inherits"]
    for e in inheritance_edges:
        src_name = _find_node_name(nodes, e.source_id)
        tgt_name = _find_node_name(nodes, e.target_id)
        if src_name and tgt_name:
            lines.append(f"    {_safe_id(src_name)} --|> {_safe_id(tgt_name)}")

    lines.append("")
    return "\n".join(lines)


def _render_flowchart(nodes: list, edges: list, max_nodes: int) -> str:
    lines = ["flowchart TD"]
    node_map = {n.id: n for n in nodes}
    shown: set[str] = set()

    sorted_edges = sorted(edges, key=lambda e: e.weight or 1.0, reverse=True)
    for e in sorted_edges[:max_nodes * 2]:
        src = node_map.get(e.source_id)
        tgt = node_map.get(e.target_id)
        if not src or not tgt:
            continue
        for n in (src, tgt):
            if n.id not in shown and len(shown) < max_nodes:
                nid = _safe_id(n.name)
                label = n.path or n.name
                lines.append(f"    {nid}[\"{label}\"]")
                shown.add(n.id)
        if src.id in shown and tgt.id in shown:
            src_id = _safe_id(src.name)
            tgt_id = _safe_id(tgt.name)
            rel = e.relation or "link"
            lines.append(f"    {src_id} -->|{rel}| {tgt_id}")

    if not shown and nodes:
        for n in nodes[:max_nodes]:
            nid = _safe_id(n.name)
            label = n.path or n.name
            lines.append(f"    {nid}[\"{label}\"]")

    lines.append("")
    return "\n".join(lines)


def _render_sequence(nodes: list, edges: list, max_nodes: int) -> str:
    lines = ["sequenceDiagram"]
    participants: set[str] = set()
    node_map = {n.id: n for n in nodes}

    sorted_edges = sorted(edges, key=lambda e: e.weight or 1.0, reverse=True)
    for e in sorted_edges[:max_nodes * 2]:
        src = node_map.get(e.source_id)
        tgt = node_map.get(e.target_id)
        if not src or not tgt:
            continue
        for label, n in [("", src), ("", tgt)]:
            if n.id not in participants:
                safe = _safe_id(n.name)
                display = n.path or n.name
                lines.append(f"    participant {safe} as \"{display}\"")
                participants.add(n.id)
        src_safe = _safe_id(src.name)
        tgt_safe = _safe_id(tgt.name)
        rel = e.relation or "calls"
        lines.append(f"    {src_safe}->>+{tgt_safe}: {rel}")

    lines.append("")
    return "\n".join(lines)


def _find_node_name(nodes: list, node_id: str) -> Optional[str]:
    for n in nodes:
        if n.id == node_id:
            return n.name
    return None
