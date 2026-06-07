from __future__ import annotations

import re
from typing import Optional

from ctxgraph_code.graph.models import Node
from ctxgraph_code.graph.storage import Storage


def search_relevant_nodes(
    storage: Storage,
    query: str,
    max_nodes: int = 15,
    max_depth: int = 2,
) -> list[tuple[Node, float]]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    scored: dict[str, float] = {}
    seen_ids: set[str] = set()

    matched_nodes = storage.search_nodes(query)
    for node in matched_nodes:
        score = _compute_relevance(node, tokens)
        if score > 0:
            scored[node.id] = score
            seen_ids.add(node.id)

    if not scored:
        for token in tokens:
            token_nodes = storage.search_nodes(token)
            for node in token_nodes:
                if node.id not in seen_ids:
                    seen_ids.add(node.id)
                    score = _compute_relevance(node, tokens)
                    if score > 0:
                        scored[node.id] = score

    if not scored:
        return []

    seed_ids = set(scored.keys())
    edge_ids = set()

    for _ in range(max_depth):
        edges = storage.get_edges_for_nodes(seed_ids | edge_ids)
        new_ids = set()
        for e in edges:
            if e.source_id in (seed_ids | edge_ids):
                new_ids.add(e.target_id)
            if e.target_id in (seed_ids | edge_ids):
                new_ids.add(e.source_id)
        edge_ids |= new_ids

    all_ids = seed_ids | edge_ids
    for nid in edge_ids:
        if nid not in scored:
            node = storage.get_node(nid)
            if node:
                neighbors = _count_matched_neighbors(nid, storage, seed_ids)
                scored[nid] = 0.1 * neighbors

    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
    ranked = ranked[:max_nodes]

    result = []
    for nid, score in ranked:
        node = storage.get_node(nid)
        if node:
            result.append((node, round(score, 3)))

    return result


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text)
    stopwords = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "is",
        "fix", "bug", "implement", "add", "change", "update", "remove",
        "need", "want", "please", "can", "how", "what", "where", "why",
        "this", "that", "with", "from", "by", "be", "has", "have", "do",
        "does", "did", "will", "would", "could", "should", "may", "might",
        "file", "function", "class", "code", "issue", "problem", "error",
        "work", "make", "get", "set",
    }
    return [t for t in tokens if t not in stopwords and len(t) > 1]


def _compute_relevance(node: Node, tokens: list[str]) -> float:
    score = 0.0
    text = f"{node.name} {node.summary or ''} {node.path or ''}".lower()

    for token in tokens:
        if token in node.name.lower():
            score += 2.0
        count = text.count(token)
        score += count * 0.5

    if node.importance:
        score *= (0.5 + node.importance)

    return score


def _count_matched_neighbors(
    node_id: str, storage: Storage, matched_ids: set[str]
) -> int:
    edges = storage.get_edges_for_nodes({node_id})
    count = 0
    for e in edges:
        if e.source_id in matched_ids or e.target_id in matched_ids:
            count += 1
    return count
