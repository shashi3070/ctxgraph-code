from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ctxgraph_code.config.build_status import (
    get_build_status,
    get_status_message,
    mark_build_complete,
    mark_build_started,
)
from ctxgraph_code.config.global_paths import get_global_claude_commands_dir
from ctxgraph_code.config.hooks import (
    HOOKS_CONFIG,
    compute_hint_summary,
    install_hooks,
    uninstall_hooks,
)
from ctxgraph_code.config.init import init_project
from ctxgraph_code.config.settings import Settings
from ctxgraph_code.graph.builder import (
    build_graph,
    get_available_graphs,
    get_graph_dirs,
    get_storage,
)
from ctxgraph_code.graph.query import search_relevant_nodes
from ctxgraph_code.render import (
    render_context,
    render_deps,
    render_overview,
    render_symbols,
    render_usedby,
)

app = typer.Typer(name="ctxgraph-code", help="Code knowledge graph for Claude Code")
console = Console()


# ── helpers ──────────────────────────────────────────────────────────────────


def _build_time_label(storage) -> str:
    ts = storage.get_metadata("build_time")
    if ts:
        try:
            from datetime import datetime
            dt = datetime.fromtimestamp(float(ts))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ts
    return "unknown"


def _resolve_dir(path: Path, file_arg: Optional[str]) -> Optional[str]:
    """Auto-detect graph dir from file path (first path segment)."""
    if not file_arg:
        return None
    p = file_arg.replace("\\", "/").lstrip("/")
    parts = p.split("/")
    if parts:
        return parts[0]
    return None


def _resolve_storage(
    path: Path,
    dir_name: Optional[str] = None,
    file_arg: Optional[str] = None,
) -> Optional[object]:
    """Get storage, trying: explicit dir → combined → auto-detect → list."""
    avail = get_available_graphs(path)

    if dir_name:
        s = get_storage(path, dir_name=dir_name)
        if s:
            msg = get_status_message(path)
            if msg:
                console.print(msg)
            return s
        console.print("[red]Error: No graph found for directory '[bold]{dir_name}[/bold]'.[/red]")
        _print_avail(avail)
        raise typer.Exit(1)

    if avail["_combined"]:
        s = get_storage(path)
        if s:
            msg = get_status_message(path)
            if msg:
                console.print(msg)
            return s

    if file_arg:
        d = _resolve_dir(path, file_arg)
        if d and d in avail["dirs"]:
            s = get_storage(path, dir_name=d)
            if s:
                msg = get_status_message(path)
                if msg:
                    console.print(msg)
                return s

    if avail["dirs"]:
        console.print(
            "[red]Error: Multiple per-directory graphs available.[/red]"
            " Use [bold]--dir[/bold] to select one."
        )
        _print_avail(avail)
        raise typer.Exit(1)

    ctx_dir = path / ".ctxgraph"
    if not ctx_dir.is_dir():
        console.print(
            "[red]Error: This project has not been set up.[/red]\n"
            "Run [bold]ctxgraph-code setup[/bold] to initialize "
            "and build the graph."
        )
    else:
        console.print(
            "[red]Error: Graph has not been built.[/red]\n"
            "Run [bold]ctxgraph-code build[/bold] to scan files "
            "and create the graph."
        )
    raise typer.Exit(1)


def _print_avail(avail: dict):
    if avail["dirs"]:
        console.print("\n[yellow]Available graphs: " + ", ".join(avail["dirs"]) + "[/yellow]")
        console.print("[yellow]Usage: ctxgraph-code <command> --dir <name>[/yellow]")


def _is_graph_stale(storage, path: Path) -> Optional[str]:
    """Return a stale hint if source files changed since last build, else None.

    Combines two checks:
    1. mtime-based quick scan (fast)
    2. Content hash verification if available (tamper detection)
    """
    import hashlib
    from datetime import datetime

    build_time_str = storage.get_metadata("build_time")
    if not build_time_str:
        return None
    try:
        build_time = float(build_time_str)
    except ValueError:
        return None

    # ── Content hash verification (tamper detection) ──────────────
    hashes_json = storage.get_metadata("content_hashes")
    tampered: list[str] = []
    if hashes_json:
        try:
            import json as j
            stored_hashes = j.loads(hashes_json)
            for rel_path, stored_hash in stored_hashes.items():
                fp = path / rel_path
                if fp.is_file():
                    try:
                        actual = hashlib.sha256(
                            fp.read_text(encoding="utf-8", errors="replace")
                            .encode("utf-8")
                        ).hexdigest()
                        if actual != stored_hash:
                            tampered.append(rel_path)
                    except OSError:
                        tampered.append(rel_path)
                else:
                    tampered.append(rel_path)
        except (j.JSONDecodeError, OSError):
            pass

    if tampered:
        parts = [f"[red]Tamper detected:[/red] {len(tampered)} file(s) changed since build."]
        for t in tampered[:5]:
            parts.append(f"  - {t}")
        if len(tampered) > 5:
            parts.append(f"  ... and {len(tampered) - 5} more")
        parts.append("Run [bold]ctxgraph-code build --incremental[/bold] to update.")
        return "\n".join(parts)

    # ── mtime-based scan (fallback when hashes unavailable) ───────
    latest_src_mtime = 0.0
    checked = 0
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d
                not in (
                    "node_modules",
                    "venv",
                    ".venv",
                    "env",
                    "dist",
                    "build",
                    "__pycache__",
                )
            ]
            for f in files:
                if f.endswith(".py"):
                    try:
                        mtime = os.path.getmtime(os.path.join(root, f))
                        if mtime > latest_src_mtime:
                            latest_src_mtime = mtime
                    except OSError:
                        pass
                    checked += 1
            if checked > 500 or latest_src_mtime > build_time:
                break
    except OSError:
        return None

    if latest_src_mtime > build_time:
        built_at = datetime.fromtimestamp(build_time).strftime("%Y-%m-%d %H:%M")
        return (
            f"Note: Files may have changed since last build ({built_at}). "
            f"Run [bold]ctxgraph-code build[/bold] to refresh."
        )
    return None


def _print_stale_hint(storage, path: Path):
    hint = _is_graph_stale(storage, path)
    if hint:
        console.print(f"\n[yellow]{hint}[/yellow]")


def _write_slash_command(slash_path: Path, path: Path):
    """Write the ctxgraph-code slash command markdown file."""
    avail = get_available_graphs(path)
    avail_str = ", ".join(avail["dirs"]) if avail["dirs"] else "combined"
    fallback = get_storage(path, dir_name=avail["dirs"][0]) if avail["dirs"] else None
    storage = get_storage(path) or fallback
    build_label = _build_time_label(storage) if storage else "unknown"
    content = SLASH_COMMAND_TEMPLATE.format(build_time=build_label, available=avail_str)

    slash_path.parent.mkdir(parents=True, exist_ok=True)
    slash_path.write_text(content, encoding="utf-8")
    console.print(f"[green][OK] {'Updated' if slash_path.exists() else 'Created'} [bold]{slash_path}[/bold][/green]")


# ── slash command template ───────────────────────────────────────────────────


SLASH_COMMAND_TEMPLATE = """# ctxgraph-code: Code Relationship Graph

**Available graphs:** {available}

**Commands:**
- `ctxgraph-code query "terms"` -- Files, classes, functions
- `ctxgraph-code probe "question"` -- Search + read source inline
- `ctxgraph-code deps <path>` -- Dependencies of a file
- `ctxgraph-code usedby <path>` -- What depends on a file
- `ctxgraph-code overview --dir <name>` -- Project structure
- `ctxgraph-code symbols <path>` -- Classes/functions in a file
- `ctxgraph-code context "task"` -- Focused context summary
- `ctxgraph-code subgraph "task"` -- Focused subgraph with source
- `ctxgraph-code diff` -- Files changed since build
- `ctxgraph-code mermaid --type classDiagram` -- Mermaid diagram
- `ctxgraph-code view --dir <name>` -- Interactive D3.js graph

Use `--dir <name>` to scope queries. File paths auto-detect the graph dir.
"""


# ── commands ─────────────────────────────────────────────────────────────────


@app.callback()
def callback():
    pass


@app.command()
def init(
    repo_path: Optional[str] = typer.Argument(
        None, help="Path to repository (default: current directory)"
    ),
):
    """Scaffold .ctxgraph directory with default config."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    result = init_project(path)
    config_path = result / "config.toml"
    console.print(f"[green]Created {config_path}[/green]")
    console.print(f"[green]Initialized .ctxgraph in: {result}[/green]")
    _print_build_hint(path)


def _print_build_hint(path: Path):
    console.print(
        "\n[yellow]Run [bold]ctxgraph-code build[/bold]"
        " to scan files and build the graph.[/yellow]"
    )


def _build_single_graph(path, exts, user_patterns, db_path, label,
                         incremental=False, verbose=False, no_summary=False):
    mark_build_started(path, os.getpid())
    start = time.time()
    with console.status(f"Scanning {', '.join(exts)} files for '{label}'..."):
        stats = build_graph(
            path,
            db_path=db_path,
            exclude_patterns=user_patterns,
            extensions=exts,
            incremental=incremental,
            verbose=verbose,
            no_summary=no_summary,
        )
    mark_build_complete(path, time.time() - start)

    table = Table(title=f"Graph Build: {label}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Files Analyzed", str(stats["files_analyzed"]))
    table.add_row("Errors", str(stats.get("errors", 0)))
    table.add_row("Total Nodes", str(stats.get("total_nodes", 0)))
    table.add_row("Total Edges", str(stats.get("total_edges", 0)))
    table.add_row("Time", f"{stats.get('elapsed_seconds', 0)}s")
    console.print(table)
    return stats


def _build_dir_worker(path, exts, user_patterns, db_path, label,
                       incremental=False, verbose=False, no_summary=False):
    """Silent build worker for parallel execution. No console output."""
    mark_build_started(path, os.getpid())
    start = time.time()
    stats = build_graph(
        path,
        db_path=db_path,
        exclude_patterns=user_patterns,
        extensions=exts,
        incremental=incremental,
        verbose=verbose,
        no_summary=no_summary,
    )
    mark_build_complete(path, time.time() - start)
    return label, stats


def _build_dirs_parallel(path, exts, user_patterns, top_dirs, graphs_dir, jobs,
                          incremental=False, verbose=False, no_summary=False):
    """Build per-directory graphs in parallel using a thread pool."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    n_workers = max(1, jobs) if jobs > 0 else os.cpu_count() or 1
    total = len(top_dirs)
    console.print(f"[bold]Building {total} graphs with {n_workers} workers...[/bold]")

    futures = {}
    _build_progress_start = time.time()
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for d in top_dirs:
            db_path = graphs_dir / f"{d.name}.db"
            fut = pool.submit(
                _build_dir_worker, path, exts, user_patterns, db_path, d.name,
                incremental, verbose, no_summary,
            )
            futures[fut] = d.name

        results = []
        completed = 0
        err_count = 0

        for f in as_completed(futures):
            label = futures[f]
            completed += 1
            try:
                lbl, stats = f.result()
                results.append((lbl, stats))
                files = stats.get("files_analyzed", 0)
                nodes = stats.get("total_nodes", 0)
                edges = stats.get("total_edges", 0)
                t = stats.get("elapsed_seconds", 0)
                console.print(
                    f"  [green]OK[/green] {label}/ "
                    f"({files} files, {nodes} nodes, {edges} edges, {t}s)"
                )
            except Exception as e:
                results.append((label, str(e)))
                err_count += 1
                console.print(f"  [red]FAIL[/red] {label}/ ([red]{e}[/red])")

        elapsed_total = time.time() - _build_progress_start
        if err_count:
            console.print(f"\n[yellow]Built {total - err_count}/{total} graphs"
                          f" ({err_count} failed) in {elapsed_total:.1f}s[/yellow]")
        else:
            console.print(f"\n[green]Built all {total} graphs in {elapsed_total:.1f}s[/green]")

    results.sort(key=lambda x: x[0] if isinstance(x[0], str) else "")

    summary = Table(title="Build Summary")
    summary.add_column("Directory", style="cyan")
    summary.add_column("Files", style="green")
    summary.add_column("Nodes", style="blue")
    summary.add_column("Edges", style="yellow")
    summary.add_column("Time", style="magenta")

    total_files = 0
    total_nodes = 0
    total_edges = 0
    total_time = 0.0

    for label, stats in results:
        if isinstance(stats, str):
            summary.add_row(f"{label}/", "[red]ERROR[/red]", stats, "", "")
        else:
            files = stats.get("files_analyzed", 0)
            nodes = stats.get("total_nodes", 0)
            edges = stats.get("total_edges", 0)
            t = stats.get("elapsed_seconds", 0)
            summary.add_row(f"{label}/", str(files), str(nodes), str(edges), f"{t}s")
            total_files += files
            total_nodes += nodes
            total_edges += edges
            total_time = max(total_time, t)

    console.print(summary)
    console.print(
        f"[green]Total: {total_files} files, {total_nodes} nodes, {total_edges} edges "
        f"in {elapsed_total:.1f}s[/green]"
    )
    return results


@app.command()
def build(
    repo_path: Optional[str] = typer.Argument(
        None, help="Path to repository (default: current directory)"
    ),
    extensions: Optional[str] = typer.Option(
        None, "--extensions", help="File extensions to scan, e.g. .py,.js,.ts"
    ),
    exclude: Optional[list[str]] = typer.Option(
        None, "--exclude", "-e", help="Additional exclude patterns"
    ),
    all_graph: bool = typer.Option(
        False, "--all", "-a", help="Build a single combined graph instead of per-directory"
    ),
    jobs: int = typer.Option(
        0, "--jobs", "-j", help="Number of parallel workers (0 = auto, default: CPU count)"
    ),
    incremental: bool = typer.Option(
        False, "--incremental", "-i", help="Only rebuild files that changed since last build"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-file progress"
    ),
    no_summary: bool = typer.Option(
        False, "--no-summary", help="Skip docstring extraction for faster builds"
    ),
):
    """Build the knowledge graph from source files.

    Default: builds a separate graph per top-level directory in parallel.
    Use --all to build one combined graph instead.
    """
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    settings = Settings(path)
    user_patterns = settings.exclude_patterns
    if exclude:
        user_patterns = list((user_patterns or []) + exclude)

    exts = settings.extensions
    if extensions:
        exts = [e.strip() for e in extensions.split(",") if e.strip()]

    ctx_dir = path / ".ctxgraph"
    ctx_dir.mkdir(parents=True, exist_ok=True)

    if all_graph:
        db_path = ctx_dir / "graph.db"
        _build_single_graph(path, exts, user_patterns, db_path, "combined",
                            incremental, verbose, no_summary)
    else:
        from ctxgraph_code.exclude.patterns import should_exclude
        top_dirs = sorted([
            d for d in path.iterdir()
            if d.is_dir() and not d.name.startswith(".")
               and not should_exclude(d, path, user_patterns)
        ])

        if not top_dirs:
            console.print(
                "[yellow]No top-level source directories found."
                " Building combined graph.[/yellow]"
            )
            db_path = ctx_dir / "graph.db"
            _build_single_graph(path, exts, user_patterns, db_path, "combined",
                                incremental, verbose, no_summary)
        else:
            graphs_dir = ctx_dir / "graphs"
            graphs_dir.mkdir(parents=True, exist_ok=True)
            _build_dirs_parallel(path, exts, user_patterns, top_dirs, graphs_dir, jobs,
                                 incremental, verbose, no_summary)


@app.command()
def query(
    query: str = typer.Argument(..., help="Search query"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    max_results: int = typer.Option(
        15, "--max", "-m", help="Maximum number of results"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to query (e.g. 'auth')"
    ),
):
    """Search the knowledge graph for relevant files, classes, and functions."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    results = search_relevant_nodes(storage, query, max_nodes=max_results)

    if not results:
        console.print("[yellow]No matches found.[/yellow]")
        return

    table = Table(title=f"Search Results: {query}")
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Path", style="blue")
    table.add_column("Score", style="yellow")

    for node, score in results:
        type_tag = {"file": "F", "class": "C", "function": "M"}
        table.add_row(
            type_tag.get(node.type, "?"),
            node.name,
            node.path or "-",
            str(score),
        )

    console.print(table)
    _print_stale_hint(storage, path)


@app.command()
def deps(
    file_path: str = typer.Argument(..., help="Path to file (relative to repo root)"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph (auto-detected from path)"
    ),
):
    """Show imports, dependents, and call relationships for a file."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name, file_arg=file_path)
    output = render_deps(storage, file_path)
    console.print(output)
    _print_stale_hint(storage, path)


@app.command()
def usedby(
    file_path: str = typer.Argument(..., help="Path to file (relative to repo root)"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph (auto-detected from path)"
    ),
):
    """Show what files depend on a given file."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name, file_arg=file_path)
    output = render_usedby(storage, file_path)
    console.print(output)
    _print_stale_hint(storage, path)


@app.command()
def overview(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to show"
    ),
):
    """Show the full project structure from the graph."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)
    output = render_overview(storage)
    console.print(output)
    _print_stale_hint(storage, path)


@app.command()
def symbols(
    file_path: str = typer.Argument(..., help="Path to file (relative to repo root)"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph (auto-detected from path)"
    ),
):
    """List classes and functions defined in a file."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name, file_arg=file_path)
    output = render_symbols(storage, file_path)
    console.print(output)
    _print_stale_hint(storage, path)


@app.command()
def context(
    query: str = typer.Argument(..., help="Task description"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    max_nodes: int = typer.Option(
        15, "--max-nodes", "-n", help="Maximum nodes to include"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to query"
    ),
):
    """Generate a focused context summary for a specific task."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)
    output = render_context(storage, query, max_nodes=max_nodes)
    console.print(output)
    _print_stale_hint(storage, path)


@app.command()
def setup(
    repo_path: Optional[str] = typer.Argument(
        None, help="Path to repository (default: current directory)"
    ),
    extensions: Optional[str] = typer.Option(
        None, "--extensions", help="File extensions to scan, e.g. .py,.js,.ts"
    ),
    exclude: Optional[str] = typer.Option(
        None, "--exclude", help="Exclude patterns, e.g. tests/,examples/"
    ),
    non_interactive: bool = typer.Option(
        False, "--yes", "-y", help="Skip prompts, use defaults"
    ),
    project_slash: bool = typer.Option(
        False, "--project-slash",
        help="Install slash command in project .claude/ instead of globally",
    ),
    jobs: int = typer.Option(
        0, "--jobs", "-j", help="Number of parallel workers (0 = auto, default: CPU count)"
    ),
    incremental: bool = typer.Option(
        False, "--incremental", "-i", help="Only rebuild files that changed since last build"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show per-file progress"
    ),
    no_summary: bool = typer.Option(
        False, "--no-summary", help="Skip docstring extraction for faster builds"
    ),
    background: bool = typer.Option(
        False, "--background", "-b", help="Launch build in background and exit immediately"
    ),
):
    """Initialize config, build the graph, and install the Claude Code slash command.

    By default the slash command (/ctxgraph-code) is installed globally so it
    works in every Claude Code session. Use --project-slash for project-local.
    """
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    if non_interactive:
        exts = [".py", ".js", ".ts", ".tsx", ".go", ".rs", ".c", ".h", ".cpp", ".java", ".rb"]
        excl = []
    elif extensions:
        exts = [e.strip() for e in extensions.split(",") if e.strip()]
        excl = [e.strip() for e in exclude.split(",") if e.strip()] if exclude else []
    else:
        console.print("[bold cyan]ctxgraph-code setup[/bold cyan]")
        console.print("Let's configure your project graph.\n")

        ext_input = typer.prompt(
            "File extensions to scan (comma-separated)",
            default=".py,.js,.ts,.go,.rs,.c,.cpp,.java,.rb",
            prompt_suffix=": ",
        )
        exts = [e.strip() for e in ext_input.split(",") if e.strip()]
        if not exts:
            exts = [".py"]

        excl_input = typer.prompt(
            "Exclude patterns (comma-separated, e.g. tests/,examples/)",
            default="",
            prompt_suffix=": ",
        )
        excl = [e.strip() for e in excl_input.split(",") if e.strip()] if excl_input.strip() else []

        console.print()

    init_project(path, extensions=exts, exclude_patterns=excl)
    console.print("[green][OK] Initialized .ctxgraph/[/green]")

    # Install slash command FIRST (immediate)
    if project_slash:
        claude_dir = path / ".claude" / "commands"
    else:
        claude_dir = get_global_claude_commands_dir()
    slash_path = claude_dir / "ctxgraph-code.md"
    _write_slash_command(slash_path, path)

    # Build in background via detached subprocess
    if background:
        import subprocess
        import sys

        build_args = [sys.executable, "-m", "ctxgraph_code", "build"]
        if repo_path:
            build_args.append(repo_path)
        if extensions:
            build_args.extend(["--extensions", extensions])
        if exclude:
            build_args.extend(["--exclude", exclude])
        if jobs:
            build_args.extend(["--jobs", str(jobs)])
        if incremental:
            build_args.append("--incremental")
        if verbose:
            build_args.append("--verbose")
        if no_summary:
            build_args.append("--no-summary")

        subprocess.Popen(
            build_args,
            creationflags=subprocess.DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if non_interactive:
            install_hooks(path)
            console.print("[green][OK] PreToolUse hooks installed[/green]")
        else:
            hook_ans = typer.confirm(
                "Install PreToolUse hooks for auto graph context injection in Claude Code?",
                default=True,
            )
            if hook_ans:
                install_hooks(path)
                console.print("[green][OK] PreToolUse hooks installed[/green]")
            else:
                console.print("[dim]Hooks skipped.[/dim]")

        console.print()
        console.print("[bold green]Setup complete! Slash command installed.[/bold green]")
        console.print(
            "Open any Claude Code project and type [bold]/ctxgraph-code[/bold] to get started."
        )
        return

    # Build (synchronous)
    ctx_dir = path / ".ctxgraph"
    graphs_dir = ctx_dir / "graphs"
    graphs_dir.mkdir(parents=True, exist_ok=True)
    top_dirs = sorted([
        d for d in path.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])

    if top_dirs:
        _build_dirs_parallel(path, exts, excl, top_dirs, graphs_dir, jobs,
                             incremental, verbose, no_summary)
    else:
        db_path = ctx_dir / "graph.db"
        _build_single_graph(path, exts, excl, db_path, "combined",
                            incremental, verbose, no_summary)
        console.print("[green][OK] Built combined graph[/green]")

    # Install hooks
    if non_interactive:
        install_hooks(path)
        console.print("[green][OK] PreToolUse hooks installed[/green]")
    else:
        hook_ans = typer.confirm(
            "Install PreToolUse hooks for auto graph context injection in Claude Code?",
            default=True,
        )
        if hook_ans:
            local_ans = typer.confirm(
                "Install in project-local settings.local.json?",
                default=False,
            )
            result = install_hooks(path, local=local_ans)
            if result:
                console.print(f"[green][OK] PreToolUse hooks installed in {result}[/green]")
            else:
                console.print("[red][FAIL] Could not install hooks[/red]")
        else:
            console.print("[dim]Hooks skipped. Run [bold]ctxgraph-code install-hooks[/bold] later.[/dim]")

    console.print()
    console.print("[bold green]Setup complete![/bold green]")
    console.print(
        "Open any Claude Code project and type [bold]/ctxgraph-code[/bold] to get started."
    )


@app.command(name="build-status")
def build_status(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """Show the status of the last or current graph build."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    msg = get_status_message(path)
    if msg:
        console.print(msg)
    else:
        status = get_build_status(path)
        if not status:
            console.print("[yellow]No build history found.[/yellow]")
            console.print("Run [bold]ctxgraph-code build[/bold] to start one.")
        elif status["status"] == "complete":
            dur = status.get("duration_s", "?")
            console.print(f"[green]Last build completed[/green] (duration: {dur}s)")
        elif status["status"] == "failed":
            err = status.get("error", "unknown")
            console.print(f"[red]Last build failed: {err}[/red]")


@app.command(name="hook-check", hidden=True)
def hook_check(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """Internal: PreToolUse hook. Outputs JSON for Claude Code context injection."""
    import json

    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    hint = compute_hint_summary(path)
    if not hint:
        raise typer.Exit(code=0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": hint,
        }
    }
    console.print(json.dumps(output, ensure_ascii=False))


@app.command(name="install-hooks")
def install_hooks_cmd(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    local: bool = typer.Option(
        False, "--local", "-l", help="Install in project-local settings.local.json"
    ),
):
    """Install PreToolUse hook for auto graph context injection in Claude Code."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    result = install_hooks(path, local=local)
    if result:
        console.print(f"[green]Hooks installed in [bold]{result}[/bold][/green]")
        console.print("Claude Code will now auto-inject graph context before searches.")
    else:
        console.print("[red]Failed to install hooks.[/red]")


@app.command(name="uninstall-hooks")
def uninstall_hooks_cmd(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    local: bool = typer.Option(
        False, "--local", "-l", help="Uninstall from project-local settings.local.json"
    ),
):
    """Remove PreToolUse hooks for ctxgraph-code."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    if uninstall_hooks(path, local=local):
        console.print("[green]Hooks removed.[/green]")
    else:
        console.print("[yellow]No hooks found to remove.[/yellow]")


@app.command(name="install-slash")
def install_slash(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    project_slash: bool = typer.Option(
        False, "--project-slash",
        help="Install in project .claude/commands/ instead of globally",
    ),
):
    """Install the /ctxgraph-code slash command for Claude Code.

    Defaults to global installation (~/.claude/commands/) so it
    works in every project. Use --project-slash for project-local.
    """
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    if project_slash:
        claude_dir = path / ".claude" / "commands"
    else:
        claude_dir = get_global_claude_commands_dir()
    _write_slash_command(claude_dir / "ctxgraph-code.md", path)
    console.print(
        "Open Claude Code and type [bold]/ctxgraph-code[/bold] to get started."
    )


@app.command()
def probe(
    query: str = typer.Argument(..., help="Search query"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    max_results: int = typer.Option(
        5, "--max", "-m", help="Maximum files to probe"
    ),
    context_lines: int = typer.Option(
        40, "--context", "-c", help="Number of lines to show per file"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to query"
    ),
):
    """Search the graph and return matching source code inline.

    Combines graph search with file reading — Claude gets paths + code
    in one command, saving 1-2 tool calls.
    """
    import ast

    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    results = search_relevant_nodes(storage, query, max_nodes=max_results)
    if not results:
        console.print("[yellow]No matches found.[/yellow]")
        raise typer.Exit()

    from rich.syntax import Syntax
    from rich.panel import Panel

    for node, score in results:
        type_tag = {"file": "F", "class": "C", "function": "M"}
        tag = type_tag.get(node.type, "?")
        header = f"[bold cyan]{tag}[/bold cyan] [bold green]{node.name}[/bold green] [blue]{node.path or '-'}[/blue] [yellow](score: {score})[/yellow]"

        code = None
        if node.path and node.type == "file":
            fp = path / node.path
            if fp.is_file():
                try:
                    code = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass

        if not code and node.path:
            for ext in ("", ".py"):
                fp = path / f"{node.path}{ext}"
                if fp.is_file():
                    try:
                        code = fp.read_text(encoding="utf-8", errors="replace")
                        break
                    except OSError:
                        pass

        if code:
            lines = code.splitlines()
            n = context_lines if context_lines > 0 else len(lines)
            snippet_lines = lines[:n]
            snippet = "\n".join(snippet_lines)
            extra = f"\n... ({len(lines) - n} more lines)" if len(lines) > n else ""
            lang = "python"
            if node.path:
                ext = Path(node.path).suffix.lower()
                lang_map = {".js": "javascript", ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "cpp", ".java": "java", ".rb": "ruby", ".kt": "kotlin", ".swift": "swift", ".cs": "csharp", ".scala": "scala", ".lua": "lua", ".zig": "zig", ".php": "php", ".sh": "bash", ".ps1": "powershell", ".json": "json", ".yaml": "yaml", ".yml": "yaml"}
                lang = lang_map.get(ext, "python")
            syntax = Syntax(snippet + extra, lang, theme="monokai", line_numbers=True)
            panel = Panel(syntax, title=header, border_style="dim")
            console.print(panel)
        else:
            summary = node.summary or "(no description)"
            console.print(f"{header}\n  {summary}\n")

    _print_stale_hint(storage, path)


@app.command()
def view(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Save graph HTML to file"
    ),
    no_open: bool = typer.Option(
        False, "--no-open", help="Generate HTML but don't open browser"
    ),
    tree: bool = typer.Option(
        False, "--tree", help="Show text tree instead of interactive graph"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to visualize"
    ),
):
    """Open an interactive D3.js graph in the browser."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    if tree:
        from ctxgraph_code.render import render_treeview
        text = render_treeview(storage)
        if output:
            out_path = Path(output)
            out_path.write_text(text, encoding="utf-8")
            console.print(f"Saved tree to [bold]{out_path}[/bold]")
        else:
            console.print(text)
        _print_stale_hint(storage, path)
        return

    from ctxgraph_code.view.visualizer import render_view
    html = render_view(storage)

    graph_dir = path / ".ctxgraph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(output) if output else (graph_dir / "graph.html")
    out_path.write_text(html, encoding="utf-8")

    console.print(f"Graph saved to [bold]{out_path}[/bold]")

    if not no_open:
        import webbrowser
        webbrowser.open(str(out_path.resolve()))
        console.print("[green]Opened in browser.[/green]")
    else:
        console.print(f"Open {out_path} in a browser to view.")
    _print_stale_hint(storage, path)


@app.command()
def info(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to inspect"
    ),
):
    """Show graph statistics."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    stats = storage.stats()
    build_time = storage.get_metadata("build_time")
    file_count = storage.get_metadata("file_count")

    table = Table(title="Graph Info")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Nodes", str(stats["nodes"]))
    table.add_row("Total Edges", str(stats["edges"]))

    plural_map = {"file": "files", "class": "classes", "function": "functions", "module": "modules"}
    for t, cnt in stats.get("types", {}).items():
        label = plural_map.get(t, t + "s")
        table.add_row(f"  {label}", str(cnt))

    if file_count:
        table.add_row("Files Analyzed", file_count)
    if build_time:
        table.add_row("Last Build", build_time)

    console.print(table)
    _print_stale_hint(storage, path)


@app.command()
def version():
    """Show the version number."""
    from importlib.metadata import version as _v
    try:
        ver = _v("ctxgraph-code")
    except Exception:
        ver = "0.6.2"
    console.print(f"ctxgraph-code version [bold]{ver}[/bold]")


@app.command()
def mermaid(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Save Mermaid output to file"
    ),
    max_nodes: int = typer.Option(
        50, "--max-nodes", "-n", help="Maximum nodes in diagram"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to use"
    ),
    diagram_type: str = typer.Argument(
        "classDiagram", help="Diagram type: classDiagram, flowchart, sequence"
    ),
):
    """Export the graph as a Mermaid diagram.

    Supported diagram types: classDiagram, flowchart, sequence.
    Outputs to console by default, or to a file with --output.
    """
    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    from ctxgraph_code.render.mermaid import MermaidError, render_mermaid

    try:
        result = render_mermaid(
            storage,
            output_type=diagram_type,
            max_nodes=max_nodes,
        )
    except MermaidError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if output:
        out_path = Path(output)
        out_path.write_text(result, encoding="utf-8")
        console.print(f"[green]Mermaid diagram saved to [bold]{out_path}[/bold][/green]")
    else:
        console.print(result)


@app.command()
def subgraph(
    query: str = typer.Argument(..., help="Task description"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    max_nodes: int = typer.Option(
        10, "--max-nodes", "-n", help="Maximum nodes in subgraph"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to query"
    ),
):
    """Extract a focused subgraph relevant to a task description.

    Returns matching nodes, their relationships, and inline source code
    for a compact context window.
    """
    import hashlib

    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    results = search_relevant_nodes(storage, query, max_nodes=max_nodes)
    if not results:
        console.print("[yellow]No relevant nodes found for subgraph.[/yellow]")
        raise typer.Exit()

    matched_ids = {n.id for n, _ in results}
    edge_ids: set[str] = set()
    edges = storage.get_edges_for_nodes(matched_ids)
    for e in edges:
        if e.source_id in matched_ids:
            edge_ids.add(e.target_id)
        if e.target_id in matched_ids:
            edge_ids.add(e.source_id)

    all_ids = matched_ids | edge_ids
    node_map: dict[str, object] = {}
    for nid in all_ids:
        n = storage.get_node(nid)
        if n:
            node_map[nid] = n

    file_nodes_in_subgraph = {
        n for n in node_map.values()
        if hasattr(n, 'type') and n.type == "file"
    }

    lines = [
        f"Subgraph for: {query}",
        f"Nodes: {len(matched_ids)} seed + {len(edge_ids)} related = {len(all_ids)} total",
        "",
    ]

    # Group by file
    file_groups: dict[str, list] = {}
    for n in sorted(node_map.values(), key=lambda x: x.path or ""):
        fp = getattr(n, 'path', None) or ""
        file_groups.setdefault(fp, []).append(n)

    for fp, nodes in sorted(file_groups.items()):
        file_node = next((n for n in nodes if n.type == "file"), None)
        if file_node:
            tag = "F"
            lines.append(f"  [{tag}] [bold]{file_node.name}[/bold] [blue]{file_node.path or '-'}[/blue]")
            if file_node.summary:
                lines.append(f"      {file_node.summary}")
        symbols = [n for n in nodes if n.type in ("class", "function")]
        if symbols:
            for s in symbols:
                tag = "C" if s.type == "class" else "M"
                lines.append(f"      [{tag}] {s.name} (line {s.lineno})")
                if s.summary:
                    lines.append(f"          {s.summary}")

    if edges:
        lines.append("")
        lines.append("  Relationships:")
        for e in edges[:15]:
            src = node_map.get(e.source_id)
            tgt = node_map.get(e.target_id)
            src_name = src.name if src else e.source_id
            tgt_name = tgt.name if tgt else e.target_id
            lines.append(f"    {src_name} --[{e.relation}]--> {tgt_name}")

    # Inline source for each file node
    lines.append("")
    for n in sorted(file_nodes_in_subgraph, key=lambda x: x.path or ""):
        fp = path / n.path if n.path else None
        if fp and fp.is_file():
            try:
                code = fp.read_text(encoding="utf-8", errors="replace")
                lines.append(f"  === {n.path} ===")
                snippet = code.splitlines()[:60]
                lines.extend(snippet)
                if len(code.splitlines()) > 60:
                    lines.append(f"... ({len(code.splitlines()) - 60} more lines)")
                lines.append("")
            except OSError:
                pass

    console.print("\n".join(lines))


@app.command()
def diff(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    dir_name: Optional[str] = typer.Option(
        None, "--dir", "-d", help="Directory graph to compare"
    ),
    ref_branch: Optional[str] = typer.Option(
        None, "--ref", help="Git reference/branch to diff against (requires git)"
    ),
):
    """Compare the graph with the filesystem.

    Shows files that have been added, removed, or changed since the
    graph was built. Use --ref for a git-aware diff against a branch.
    """
    import hashlib
    import json as j

    path = Path(repo_path).resolve() if repo_path else Path.cwd()
    storage = _resolve_storage(path, dir_name=dir_name)

    new_files: list[str] = []
    removed_files: list[str] = []
    changed_files: list[str] = []

    graph_paths = set(storage.get_file_paths())
    hashes_json = storage.get_metadata("content_hashes")
    stored_hashes: dict[str, str] = {}
    if hashes_json:
        try:
            stored_hashes = j.loads(hashes_json)
        except (j.JSONDecodeError, OSError):
            pass

    if ref_branch:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "diff", "--name-only", ref_branch],
                capture_output=True, text=True, check=False, cwd=str(path),
            )
            if result.returncode == 0:
                git_files = set(result.stdout.strip().splitlines()) if result.stdout.strip() else set()
                for gf in git_files:
                    if gf not in graph_paths:
                        new_files.append(gf)
                for gp in graph_paths:
                    if gp not in git_files:
                        removed_files.append(gp)
                # Changed files = git diff --name-only from HEAD
                head_result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD"],
                    capture_output=True, text=True, check=False, cwd=str(path),
                )
                if head_result.returncode == 0:
                    changed_files = [f for f in head_result.stdout.strip().splitlines() if f in graph_paths]
            else:
                console.print(f"[red]git diff failed: {result.stderr.strip()}[/red]")
                console.print("[yellow]Falling back to filesystem comparison...[/yellow]")
                ref_branch = None
        except FileNotFoundError:
            console.print("[yellow]Git not found. Falling back to filesystem comparison...[/yellow]")
            ref_branch = None

    if not ref_branch:
        for gp in graph_paths:
            fp = path / gp
            if not fp.is_file():
                removed_files.append(gp)

        src_extensions = {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".c", ".h", ".cpp", ".java", ".rb", ".kt", ".swift"}
        for root, _dirs, files in os.walk(path):
            _dirs[:] = [d for d in _dirs if not d.startswith(".") and d not in ("node_modules", "venv", ".venv", "env", "dist", "build", "__pycache__")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in src_extensions:
                    continue
                rel_path = os.path.relpath(os.path.join(root, f), path).replace("\\", "/")
                if rel_path not in graph_paths:
                    new_files.append(rel_path)

        # Content hash comparison for changed detection
        if stored_hashes:
            for rel_path, stored_hash in stored_hashes.items():
                fp = path / rel_path
                if fp.is_file():
                    try:
                        actual = hashlib.sha256(
                            fp.read_text(encoding="utf-8", errors="replace")
                            .encode("utf-8")
                        ).hexdigest()
                        if actual != stored_hash:
                            changed_files.append(rel_path)
                    except OSError:
                        changed_files.append(rel_path)

    lines = ["Graph vs Filesystem Diff", ""]
    if new_files:
        lines.append(f"  [green]+ {len(new_files)} new file(s):[/green]")
        for f in sorted(new_files)[:10]:
            lines.append(f"    + {f}")
        if len(new_files) > 10:
            lines.append(f"    ... and {len(new_files) - 10} more")
    else:
        lines.append("  [green]+ No new files[/green]")

    if removed_files:
        lines.append(f"")
        lines.append(f"  [red]- {len(removed_files)} removed file(s):[/red]")
        for f in sorted(removed_files)[:10]:
            lines.append(f"    - {f}")
        if len(removed_files) > 10:
            lines.append(f"    ... and {len(removed_files) - 10} more")
    else:
        lines.append(f"")
        lines.append("  [red]- No removed files[/red]")

    if changed_files:
        lines.append(f"")
        lines.append(f"  [yellow]~ {len(changed_files)} changed file(s):[/yellow]")
        for f in sorted(changed_files)[:10]:
            lines.append(f"    ~ {f}")
        if len(changed_files) > 10:
            lines.append(f"    ... and {len(changed_files) - 10} more")
    else:
        lines.append(f"")
        lines.append("  [yellow]~ No changed files[/yellow]")

    lines.append("")
    if new_files or removed_files or changed_files:
        lines.append("[yellow]Run [bold]ctxgraph-code build --incremental[/bold] to update the graph.[/yellow]")
    else:
        lines.append("[green]Graph is up to date with the filesystem.[/green]")

    console.print("\n".join(lines))


if __name__ == "__main__":
    app()

