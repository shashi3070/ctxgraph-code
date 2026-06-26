from __future__ import annotations

from typing import Optional

from ctxgraph_code.analyzers.treesitter.languages import (
    EXTENSION_LANG,
    LANG_QUERIES,
)


class TSAnalyzerResult:
    nodes: list[dict]
    edges: list[dict]

    def __init__(self, nodes: Optional[list[dict]] = None, edges: Optional[list[dict]] = None):
        self.nodes = nodes or []
        self.edges = edges or []

    def to_dict(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges}


class TSAnalyzer:
    _parser_cache: dict[str, object] = {}
    _lang_cache: dict[str, object] = {}

    def __init__(self, file_path, root_path):
        self.file_path = file_path
        self.root_path = root_path
        self.rel = str(file_path.relative_to(root_path)).replace("\\", "/")
        self.ext = file_path.suffix.lower()
        self.lang_name = EXTENSION_LANG.get(self.ext, "")

    def can_handle(self) -> bool:
        return self.lang_name in LANG_QUERIES

    def analyze(self, source: str) -> TSAnalyzerResult:
        if not self.can_handle():
            return TSAnalyzerResult()

        try:
            import tree_sitter as ts
            from tree_sitter_language_pack import get_language
        except ImportError:
            import warnings
            warnings.warn(
                f"Missing tree-sitter dependency for {self.lang_name} files. "
                "Install with: pip install 'ctxgraph-code[full]'"
            )
            raise

        lang = self._get_lang(self.lang_name)
        if not lang:
            return TSAnalyzerResult()

        parser = self._get_parser(self.lang_name)
        if not parser:
            return TSAnalyzerResult()

        tree = parser.parse(source.encode("utf-8"))
        if not tree or not tree.root_node:
            return TSAnalyzerResult()

        queries = LANG_QUERIES[self.lang_name]
        result = TSAnalyzerResult()

        # File node
        file_id = f"{self.root_path}:{self.rel}"
        result.nodes.append({
            "id": file_id,
            "type": "file",
            "name": self.file_path.name,
            "path": self.rel,
            "parent_id": None,
            "summary": None,
            "importance": 0.5,
            "size_bytes": len(source),
            "lineno": 0,
        })

        # Extract definitions (functions, classes, structs, etc.)
        self._extract_defs(lang, parser, tree, queries, file_id, result)

        # Extract imports
        self._extract_imports(lang, tree, queries, file_id, result)

        # Extract calls
        self._extract_calls(lang, tree, queries, file_id, result)

        return result

    def _get_lang(self, name: str):
        if name not in self._lang_cache:
            try:
                from tree_sitter_language_pack import get_language
                self._lang_cache[name] = get_language(name)
            except Exception:
                self._lang_cache[name] = None
        return self._lang_cache[name]

    def _get_parser(self, name: str):
        if name not in self._parser_cache:
            try:
                import tree_sitter as ts
                from tree_sitter_language_pack import get_parser
                parser = get_parser(name)
                self._parser_cache[name] = parser
            except Exception:
                self._parser_cache[name] = None
        return self._parser_cache[name]

    def _run_query(self, lang, query_str, node):
        import tree_sitter as ts
        try:
            q = ts.Query(lang, query_str)
            cur = ts.QueryCursor(q)
            return cur.captures(node)
        except Exception:
            return {}

    def _extract_defs(self, lang, parser, tree, queries, file_id, result):
        defs_seen: set[str] = set()
        lineno_offsets = self._line_offsets(tree.root_node)

        for tag_name, sym_type in [
            ("functions", "function"),
            ("methods", "method"),
            ("classes", "class"),
            ("structs", "struct"),
            ("interfaces", "interface"),
            ("traits", "trait"),
            ("types", "type"),
            ("modules", "module"),
        ]:
            qs = queries.get(tag_name)
            if not qs:
                continue

            caps = self._run_query(lang, qs, tree.root_node)
            if not caps:
                continue

            names = caps.get("name", [])
            containers = caps.get(tag_name, [])

            for i, n in enumerate(names):
                name = n.text.decode("utf-8", errors="replace")
                if name in defs_seen:
                    continue
                defs_seen.add(name)

                lineno = n.start_point[0] + 1 if n.start_point else 0
                node_id = f"{file_id}::{name}"

                result.nodes.append({
                    "id": node_id,
                    "type": sym_type,
                    "name": name,
                    "path": self.rel,
                    "parent_id": file_id,
                    "summary": None,
                    "importance": 0.6 if sym_type in ("class", "struct", "interface") else 0.5,
                    "size_bytes": 0,
                    "lineno": lineno,
                })

                result.edges.append({
                    "source_id": file_id,
                    "target_id": node_id,
                    "relation": "defines",
                    "weight": 1.0,
                })

    def _extract_imports(self, lang, tree, queries, file_id, result):
        qs = queries.get("imports")
        if not qs:
            return

        caps = self._run_query(lang, qs, tree.root_node)
        if not caps:
            return

        seen: set[str] = set()
        for sources in caps.values():
            for s in sources:
                path = s.text.decode("utf-8", errors="replace").strip("\"'<>")
                if path in seen:
                    continue
                seen.add(path)

                import_id = f"{file_id}:import:{path}"
                result.nodes.append({
                    "id": import_id,
                    "type": "import",
                    "name": path,
                    "path": self.rel,
                    "parent_id": file_id,
                    "summary": None,
                    "importance": 0.3,
                    "size_bytes": 0,
                    "lineno": 0,
                })

                result.edges.append({
                    "source_id": file_id,
                    "target_id": import_id,
                    "relation": "imports",
                    "weight": 1.0,
                })

    def _extract_calls(self, lang, tree, queries, file_id, result):
        qs = queries.get("calls")
        if not qs:
            return

        caps = self._run_query(lang, qs, tree.root_node)
        if not caps:
            return

        call_names = caps.get("call_name", [])
        seen: set[str] = set()
        for c in call_names:
            name = c.text.decode("utf-8", errors="replace")
            if name in seen:
                continue
            seen.add(name)

            call_id = f"{file_id}:call:{name}"
            result.nodes.append({
                "id": call_id,
                "type": "call",
                "name": name,
                "path": self.rel,
                "parent_id": file_id,
                "summary": None,
                "importance": 0.3,
                "size_bytes": 0,
                "lineno": c.start_point[0] + 1 if c.start_point else 0,
            })

            result.edges.append({
                "source_id": file_id,
                "target_id": call_id,
                "relation": "calls",
                "weight": 0.7,
            })

    def _line_offsets(self, root_node):
        offsets = {}
        stack = [root_node]
        while stack:
            node = stack.pop()
            if node.start_point and node.start_point[0] != node.end_point[0]:
                offsets[node.start_point[0]] = node.start_point[1]
            for c in node.children:
                stack.append(c)
        return offsets
