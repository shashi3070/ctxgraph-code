from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from ctxgraph_code.graph.models import Node


def enrich_node_summary(
    node: Node,
    file_path: Path,
    *,
    source: Optional[str] = None,
    tree: Optional[ast.AST] = None,
) -> str:
    if node.summary:
        return node.summary

    if tree is None:
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, FileNotFoundError):
            return node.summary or ""

    if node.type == "file":
        return _summarize_file(tree, file_path)
    elif node.type == "class":
        return _summarize_class(tree, node.name)
    elif node.type == "function":
        return _summarize_function(tree, node.name)

    return node.summary or ""


def _summarize_file(tree: ast.AST, file_path: Path) -> str:
    doc = ast.get_docstring(tree)
    if doc:
        return doc.split("\n\n")[0][:200]

    classes = []
    funcs = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node.name)

    parts = []
    if classes:
        parts.append(f"Defines classes: {', '.join(classes)}")
    if funcs:
        parts.append(f"Defines functions: {', '.join(funcs)}")
    return "; ".join(parts) if parts else ""


def _summarize_class(tree: ast.AST, class_name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            doc = ast.get_docstring(node)
            if doc:
                return doc.split("\n\n")[0][:200]
            methods = [
                c.name
                for c in ast.iter_child_nodes(node)
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if methods:
                return f"Methods: {', '.join(methods)}"
    return ""


def _summarize_function(tree: ast.AST, func_name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            doc = ast.get_docstring(node)
            if doc:
                return doc.split("\n\n")[0][:200]
            args = [a.arg for a in node.args.args]
            if args:
                return f"Args: {', '.join(args)}"
    return ""
