from __future__ import annotations

import ast
import hashlib
import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ctxgraph_code.analyzers.python.importer import analyze_imports
from ctxgraph_code.analyzers.python.semantic import enrich_node_summary
from ctxgraph_code.analyzers.python.symbols import analyze_symbols
from ctxgraph_code.exclude.patterns import should_exclude
from ctxgraph_code.graph.models import Graph
from ctxgraph_code.graph.storage import Storage

MTIMES_FILE = "file_mtimes.json"


def _mtimes_path(repo_path: Path) -> Path:
    return repo_path / ".ctxgraph" / MTIMES_FILE


def _load_mtimes(repo_path: Path) -> dict[str, float]:
    p = _mtimes_path(repo_path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_mtimes(repo_path: Path, mtimes: dict[str, float]):
    p = _mtimes_path(repo_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mtimes, indent=1), encoding="utf-8")


def build_graph(
    repo_path: str | Path,
    db_path: Optional[str | Path] = None,
    exclude_patterns: Optional[list[str]] = None,
    extensions: Optional[list[str]] = None,
    jobs: int = 0,
    incremental: bool = False,
    verbose: bool = False,
    no_summary: bool = False,
) -> dict:
    repo_path = Path(repo_path).resolve()
    if db_path is None:
        db_path = repo_path / ".ctxgraph" / "graph.db"
    db_path = Path(db_path)
    start = time.time()
    exts = set(extensions or [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".kt", ".swift", ".scala", ".lua", ".cs", ".zig"])

    if jobs <= 0:
        jobs = (os.cpu_count() or 1)

    from ctxgraph_code.config.settings import Settings
    _settings = Settings(repo_path)
    follow_symlinks = _settings.follow_symlinks
    max_bytes = _settings.max_file_size_mb * 1024 * 1024

    @lru_cache(maxsize=None)
    def _should_exclude(path: Path) -> bool:
        return should_exclude(path, repo_path, exclude_patterns)

    # ── walk files + collect mtimes ────────────────────────────────────────
    path_index: set[str] = set()
    scan_files: list[Path] = []
    current_mtimes: dict[str, float] = {}

    for dirpath, dirnames, filenames in os.walk(repo_path, followlinks=follow_symlinks):
        dirnames[:] = [
            d for d in dirnames
            if not _should_exclude(repo_path / d)
        ]
        for fn in filenames:
            if Path(fn).suffix not in exts:
                continue
            fp = Path(dirpath) / fn
            rp = str(fp.relative_to(repo_path)).replace("\\", "/")
            if not _should_exclude(fp):
                path_index.add(rp)
                scan_files.append(fp)
                try:
                    current_mtimes[rp] = os.path.getmtime(fp)
                except OSError:
                    current_mtimes[rp] = 0.0

    if not scan_files:
        elapsed = time.time() - start
        return {
            "files_analyzed": 0, "files_skipped": 0, "errors": 0,
            "elapsed_seconds": round(elapsed, 2),
            "total_nodes": 0, "total_edges": 0,
        }

    # ── incremental: filter to changed files only ─────────────────────────
    changed_files: list[Path] = list(scan_files)
    old_mtimes: dict[str, float] = {}

    if incremental:
        old_mtimes = _load_mtimes(repo_path)
        filtered: list[Path] = []
        for fp in scan_files:
            rp = str(fp.relative_to(repo_path)).replace("\\", "/")
            old_mtime = old_mtimes.get(rp)
            current_mtime = current_mtimes.get(rp, 0)
            if old_mtime is None or old_mtime != current_mtime:
                filtered.append(fp)
        changed_files = filtered

        removed_paths = old_mtimes.keys() - current_mtimes.keys()

        if not changed_files:
            elapsed = time.time() - start
            return {
                "files_analyzed": 0, "files_skipped": len(scan_files), "errors": 0,
                "elapsed_seconds": round(elapsed, 2),
                "total_nodes": 0, "total_edges": 0,
            }

    stats: dict = {"files_analyzed": 0, "errors": 0}
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    file_hashes: dict[str, str] = {}

    n_total = len(changed_files)
    use_mp = jobs > 1 and n_total > 10

    if verbose:
        from rich.console import Console
        vconsole = Console()
        vconsole.log(f"Processing {n_total} files ({len(scan_files)} total) with {jobs} workers...")

    # ── process files ─────────────────────────────────────────────────────
    if use_mp:
        import multiprocessing as mp
        chunk_size = max(1, n_total // jobs)
        chunks = [changed_files[i:i + chunk_size] for i in range(0, n_total, chunk_size)]

        with mp.Pool(jobs) as pool:
            results = [
                pool.apply_async(_worker_batch, (chunk, repo_path, path_index, no_summary, max_bytes))
                for chunk in chunks
            ]
            for i, r in enumerate(results):
                try:
                    nds, eds, ok, err, fh = r.get(timeout=600)
                    all_nodes.extend(nds)
                    all_edges.extend(eds)
                    file_hashes.update(fh)
                    stats["files_analyzed"] += ok
                    stats["errors"] += err
                    if verbose:
                        done = min((i + 1) * chunk_size, n_total)
                        vconsole.log(f"  [{done}/{n_total}] files done...")
                except Exception:
                    stats["errors"] += chunk_size
    else:
        for i, file_path in enumerate(changed_files):
            try:
                nds, eds, fh = _process_file(file_path, repo_path, path_index, no_summary, max_bytes)
                all_nodes.extend(nds)
                all_edges.extend(eds)
                file_hashes.update(fh)
                stats["files_analyzed"] += 1
            except Exception:
                stats["errors"] += 1
            if verbose and (i + 1) % 50 == 0:
                from rich.console import Console
                vconsole = Console()
                vconsole.log(f"  [{i + 1}/{n_total}] files done...")

    # ── save to DB ────────────────────────────────────────────────────────
    graph = Graph.from_batch(all_nodes, all_edges)
    storage = Storage(db_path)
    storage.connect()

    if incremental:
        for fp in changed_files:
            rp = str(fp.relative_to(repo_path)).replace("\\", "/")
            storage.delete_nodes_for_file(rp)
        for rp in removed_paths:
            storage.delete_nodes_for_file(rp)

    storage.save_graph(graph)
    storage.save_metadata("build_time", str(time.time()))
    storage.save_metadata("repo_path", str(repo_path))
    storage.save_metadata("file_count", str(stats["files_analyzed"]))
    storage.save_metadata("content_hashes", json.dumps(file_hashes))
    storage.close()

    # ── save mtimes for incremental ───────────────────────────────────────
    if incremental:
        _save_mtimes(repo_path, current_mtimes)

    elapsed = time.time() - start
    stats["elapsed_seconds"] = round(elapsed, 2)
    stats["total_nodes"] = len(graph.nodes)
    stats["total_edges"] = len(graph.edges)

    if verbose:
        from rich.console import Console
        vconsole = Console()
        vconsole.log(
            f"Done: {stats['files_analyzed']} files, {stats['total_nodes']} nodes, "
            f"{stats['total_edges']} edges in {elapsed:.1f}s"
        )

    return stats


# ── worker helpers ───────────────────────────────────────────────────────────


def _quick_scan(source: str, is_python: bool = True) -> bool:
    """Quick pre-check: does this file have meaningful code?
    Returns True if full parsing is needed."""
    for line in source.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//", "/*", "*", "--", ";")) and is_python:
            continue
        if not line:
            continue
        if is_python:
            if any(line.startswith(kw) for kw in ("import ", "from ", "class ", "def ", "@")):
                return True
        else:
            if any(kw in line for kw in ("function", "class", "struct", "trait", "interface", "import ", "include ", "fn ", "def ", "pub ", "export ", "impl ")):
                return True
        if any(c in line for c in ("{", "(", "=", ";")):
            return True
    return False


def _file_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _process_file(
    file_path: Path,
    root_path: Path,
    path_index: set[str],
    no_summary: bool = False,
    max_bytes: int = 0,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    rel = str(file_path.relative_to(root_path)).replace("\\", "/")

    if max_bytes > 0:
        try:
            if file_path.stat().st_size > max_bytes:
                return [], [], {}
        except OSError:
            pass

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], [], {}

    fhash = {rel: _file_hash(source)}

    if file_path.suffix == ".py":
        return _process_python(file_path, root_path, rel, source, path_index, no_summary, fhash)

    return _process_treesitter(file_path, root_path, rel, source, fhash)


def _process_python(
    file_path: Path,
    root_path: Path,
    rel: str,
    source: str,
    path_index: set[str],
    no_summary: bool = False,
    fhash: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    fhash = fhash or {}

    if not _quick_scan(source, is_python=True):
        return [{
            "id": f"{root_path}:{rel}",
            "type": "file",
            "name": file_path.name,
            "path": rel,
            "parent_id": None,
            "summary": None,
            "importance": 0.5,
            "size_bytes": len(source),
            "lineno": 0,
        }], [], fhash

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], [], fhash

    nodes: list[dict] = []
    edges: list[dict] = []

    ig = analyze_imports(file_path, root_path, tree=tree, path_index=path_index)
    for nd in ig.nodes.values():
        nodes.append(nd.to_dict())
    for ed in ig.edges:
        edges.append(ed.to_dict())

    sg = analyze_symbols(file_path, root_path, source=source, tree=tree)
    for nd in sg.nodes.values():
        nodes.append(nd.to_dict())
    for ed in sg.edges:
        edges.append(ed.to_dict())

    if not no_summary:
        for nd in sg.nodes.values():
            if nd.summary is None:
                enriched = enrich_node_summary(nd, file_path, source=source, tree=tree)
                if enriched:
                    nd.summary = enriched
                    nodes.append(nd.to_dict())

        file_node = next((nd for nd in ig.nodes.values() if nd.type == "file"), None)
        if file_node and file_node.summary is None:
            enriched = enrich_node_summary(file_node, file_path, source=source, tree=tree)
            if enriched:
                file_node.summary = enriched
                nodes.append(file_node.to_dict())

    return nodes, edges, fhash


def _process_treesitter(
    file_path: Path,
    root_path: Path,
    rel: str,
    source: str,
    fhash: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    fhash = fhash or {}

    if not _quick_scan(source, is_python=False):
        return [{
            "id": f"{root_path}:{rel}",
            "type": "file",
            "name": file_path.name,
            "path": rel,
            "parent_id": None,
            "summary": None,
            "importance": 0.5,
            "size_bytes": len(source),
            "lineno": 0,
        }], [], fhash

    from ctxgraph_code.analyzers.treesitter import TSAnalyzer

    analyzer = TSAnalyzer(file_path, root_path)
    if not analyzer.can_handle():
        return [], [], fhash

    import warnings
    try:
        result = analyzer.analyze(source)
    except ImportError:
        warnings.warn(
            f"tree-sitter not installed — skipping {rel}. "
            "Install with: pip install 'ctxgraph-code[full]'"
        )
        return [], [], fhash

    return result.nodes, result.edges, fhash


def _worker_batch(
    file_paths: list[Path],
    root_path: Path,
    path_index: set[str],
    no_summary: bool = False,
    max_bytes: int = 0,
) -> tuple[list[dict], list[dict], int, int, dict[str, str]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    hashes: dict[str, str] = {}
    ok = 0
    err = 0
    for fp in file_paths:
        try:
            nds, eds, fh = _process_file(fp, root_path, path_index, no_summary, max_bytes)
            nodes.extend(nds)
            edges.extend(eds)
            hashes.update(fh)
            ok += 1
        except Exception:
            err += 1
    return nodes, edges, ok, err, hashes


# ── storage helpers ──────────────────────────────────────────────────────────


def get_storage(repo_path: str | Path, dir_name: Optional[str] = None) -> Optional[Storage]:
    base = Path(repo_path) / ".ctxgraph"
    if dir_name:
        db_path = base / "graphs" / f"{dir_name}.db"
    else:
        db_path = base / "graph.db"
    if not db_path.exists():
        return None
    storage = Storage(db_path)
    storage.connect()
    return storage


def get_graph_dirs(repo_path: str | Path) -> list[str]:
    graphs_dir = Path(repo_path) / ".ctxgraph" / "graphs"
    if not graphs_dir.is_dir():
        return []
    return sorted(f.stem for f in graphs_dir.iterdir() if f.suffix == ".db")


def get_available_graphs(repo_path: str | Path) -> dict:
    base = Path(repo_path) / ".ctxgraph"
    return {"_combined": (base / "graph.db").exists(), "dirs": get_graph_dirs(repo_path)}
