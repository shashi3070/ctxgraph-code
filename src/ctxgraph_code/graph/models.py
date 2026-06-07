from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    id: str
    type: str
    name: str
    path: Optional[str] = None
    parent_id: Optional[str] = None
    summary: Optional[str] = None
    importance: float = 0.5
    size_bytes: int = 0
    lineno: int = 0

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, Node) and self.id == other.id


@dataclass
class Edge:
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0

    def __hash__(self):
        return hash((self.source_id, self.target_id, self.relation))

    def __eq__(self, other):
        return (
            isinstance(other, Edge)
            and self.source_id == other.source_id
            and self.target_id == other.target_id
            and self.relation == other.relation
        )


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node: Node):
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge):
        self.edges.append(edge)

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def get_edges_from(self, source_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source_id == source_id]

    def get_edges_to(self, target_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target_id == target_id]

    def get_neighbors(self, node_id: str) -> list[str]:
        result = set()
        for e in self.edges:
            if e.source_id == node_id:
                result.add(e.target_id)
            if e.target_id == node_id:
                result.add(e.source_id)
        return list(result)

    def merge(self, other: Graph):
        for node_id, node in other.nodes.items():
            if node_id not in self.nodes:
                self.nodes[node_id] = node
        existing = {(e.source_id, e.target_id, e.relation) for e in self.edges}
        for e in other.edges:
            key = (e.source_id, e.target_id, e.relation)
            if key not in existing:
                self.edges.append(e)
                existing.add(key)
