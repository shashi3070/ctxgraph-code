from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from ctxgraph_code.graph.models import Graph


def analyze_symbols(
    file_path: Path,
    root_path: Path,
    *,
    source: Optional[str] = None,
    tree: Optional[ast.AST] = None,
) -> Graph:
    rel_path = _relative_path(file_path, root_path)
    file_node_id = f"file:{rel_path}"

    if tree is None:
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except SyntaxError:
            return Graph()

    lines = source.split("\n") if source else []
    nodes: list[dict] = []
    edges: list[dict] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            _process_class(node, nodes, edges, file_node_id, rel_path, lines)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _process_function(node, nodes, edges, file_node_id, rel_path, lines)

    _process_calls(tree, nodes, edges, rel_path)

    return Graph.from_batch(nodes, edges)


# ── helpers ─────────────────────────────────────────────────────────────────


def _node_dict(**kw) -> dict:
    return dict(kw)


def _edge_dict(**kw) -> dict:
    return dict(kw)


def _process_class(
    node: ast.ClassDef,
    nodes: list[dict],
    edges: list[dict],
    file_node_id: str,
    rel_path: str,
    lines: list[str],
):
    class_id = f"class:{rel_path}::{node.name}"
    summary = _extract_docstring(node)
    bases = _get_base_names(node)

    nodes.append(_node_dict(
        id=class_id,
        type="class",
        name=node.name,
        path=rel_path,
        parent_id=file_node_id,
        summary=summary,
        importance=0.6,
        lineno=node.lineno,
    ))
    edges.append(_edge_dict(
        source_id=file_node_id,
        target_id=class_id,
        relation="defines",
        weight=1.0,
    ))

    for base in bases:
        edges.append(_edge_dict(
            source_id=class_id,
            target_id=base,
            relation="extends",
            weight=0.8,
        ))

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _process_method(child, nodes, edges, class_id, rel_path, lines)


def _process_function(
    node: (ast.FunctionDef | ast.AsyncFunctionDef),
    nodes: list[dict],
    edges: list[dict],
    file_node_id: str,
    rel_path: str,
    lines: list[str],
):
    func_id = f"func:{rel_path}::{node.name}"
    summary = _extract_docstring(node)

    nodes.append(_node_dict(
        id=func_id,
        type="function",
        name=node.name,
        path=rel_path,
        parent_id=file_node_id,
        summary=summary,
        importance=0.5,
        lineno=node.lineno,
    ))
    edges.append(_edge_dict(
        source_id=file_node_id,
        target_id=func_id,
        relation="defines",
        weight=1.0,
    ))


def _process_method(
    node: (ast.FunctionDef | ast.AsyncFunctionDef),
    nodes: list[dict],
    edges: list[dict],
    class_id: str,
    rel_path: str,
    lines: list[str],
):
    method_id = f"func:{rel_path}::{node.name}"
    summary = _extract_docstring(node)

    nodes.append(_node_dict(
        id=method_id,
        type="function",
        name=node.name,
        path=rel_path,
        parent_id=class_id,
        summary=summary,
        importance=0.5,
        lineno=node.lineno,
    ))
    edges.append(_edge_dict(
        source_id=class_id,
        target_id=method_id,
        relation="defines",
        weight=1.0,
    ))


def _process_calls(tree: ast.AST, nodes: list[dict], edges: list[dict], rel_path: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = _get_call_name(node.func)
            if func_name:
                caller_id = _find_enclosing_symbol(tree, node, rel_path)
                if caller_id:
                    callee_id = _find_target_node(func_name, nodes)
                    if callee_id:
                        edges.append(_edge_dict(
                            source_id=caller_id,
                            target_id=callee_id,
                            relation="calls",
                            weight=0.7,
                        ))


def _get_call_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    return None


def _find_enclosing_symbol(
    tree: ast.AST, target_node: ast.AST, rel_path: str
) -> Optional[str]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _contains_node(node, target_node):
                return f"func:{rel_path}::{node.name}"
        elif isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _contains_node(child, target_node):
                        return f"func:{rel_path}::{child.name}"
    return None


def _contains_node(container: ast.AST, target: ast.AST) -> bool:
    for node in ast.walk(container):
        if node is target:
            return True
    return False


def _find_target_node(name: str, nodes: list[dict]) -> Optional[str]:
    for nd in nodes:
        if nd.get("type") in ("function", "class") and nd["name"] == name:
            return nd["id"]
    return None


def _extract_docstring(node: ast.AST) -> Optional[str]:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        doc = ast.get_docstring(node)
        if doc:
            return doc.split("\n\n")[0][:200]
    return None


def _get_base_names(node: ast.ClassDef) -> list[str]:
    bases = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(f"class:{base.id}")
    return bases


def _relative_path(file_path: Path, root_path: Path) -> str:
    try:
        return str(file_path.relative_to(root_path)).replace("\\", "/")
    except ValueError:
        return file_path.name
