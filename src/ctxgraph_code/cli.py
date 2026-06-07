from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ctxgraph_code.config.init import init_project
from ctxgraph_code.config.settings import Settings
from ctxgraph_code.graph.builder import build_graph, get_storage
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


SLASH_COMMAND_TEMPLATE = """# ctxgraph-code: Code Relationship Graph

This project has a knowledge graph at `.ctxgraph/graph.db`.
The graph knows about imports, class hierarchies, and function calls.

**Last build:** {build_time}

**Available commands** (run these as shell commands in the terminal):

- `ctxgraph-code query "search terms"` -- Find relevant files, classes, and functions
- `ctxgraph-code deps <path>` -- Show what a file imports and what calls it
- `ctxgraph-code usedby <path>` -- Show what depends on a file
- `ctxgraph-code overview` -- Show the full project structure
- `ctxgraph-code symbols <path>` -- List classes/functions defined in a file
- `ctxgraph-code context "task description"` -- Generate a focused context summary

**When to use:**
- Before modifying code, run `deps` and `usedby` to understand ripple effects.
- When exploring an unfamiliar area, run `query` to find relevant files, then read them.
- When asked about architecture, run `overview` for the big picture.
- For complex tasks, run `context "what I need to do"` for a focused summary.

**Note:** The graph is a static snapshot. If files have changed since the last build,
run `ctxgraph-code build` to refresh it.
"""


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
):
    """Build the knowledge graph from source files."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    settings = Settings(path)
    user_patterns = settings.exclude_patterns
    if exclude:
        user_patterns = list((user_patterns or []) + exclude)

    exts = settings.extensions
    if extensions:
        exts = [e.strip() for e in extensions.split(",") if e.strip()]

    if not (path / ".ctxgraph").exists():
        (path / ".ctxgraph").mkdir(parents=True, exist_ok=True)

    ext_label = ", ".join(exts)
    with console.status(f"Scanning {ext_label} files in {path}..."):
        stats = build_graph(path, exclude_patterns=user_patterns, extensions=exts)

    table = Table(title="Graph Build Complete")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Files Analyzed", str(stats["files_analyzed"]))
    table.add_row("Files Skipped", str(stats.get("files_skipped", 0)))
    table.add_row("Errors", str(stats.get("errors", 0)))
    table.add_row("Total Nodes", str(stats.get("total_nodes", 0)))
    table.add_row("Total Edges", str(stats.get("total_edges", 0)))
    table.add_row("Time", f"{stats.get('elapsed_seconds', 0)}s")

    console.print(table)
    console.print(f"\nGraph stored in: [bold]{path / '.ctxgraph' / 'graph.db'}[/bold]")


@app.command()
def query(
    query: str = typer.Argument(..., help="Search query"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    max_results: int = typer.Option(
        15, "--max", "-m", help="Maximum number of results"
    ),
):
    """Search the knowledge graph for relevant files, classes, and functions."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

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


@app.command()
def deps(
    file_path: str = typer.Argument(..., help="Path to file (relative to repo root)"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """Show imports, dependents, and call relationships for a file."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

    output = render_deps(storage, file_path)
    console.print(output)


@app.command()
def usedby(
    file_path: str = typer.Argument(..., help="Path to file (relative to repo root)"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """Show what files depend on a given file."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

    output = render_usedby(storage, file_path)
    console.print(output)


@app.command()
def overview(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """Show the full project structure from the graph."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

    output = render_overview(storage)
    console.print(output)


@app.command()
def symbols(
    file_path: str = typer.Argument(..., help="Path to file (relative to repo root)"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """List classes and functions defined in a file."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

    output = render_symbols(storage, file_path)
    console.print(output)


@app.command()
def context(
    query: str = typer.Argument(..., help="Task description"),
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
    max_nodes: int = typer.Option(
        15, "--max-nodes", "-n", help="Maximum nodes to include"
    ),
):
    """Generate a focused context summary for a specific task."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

    output = render_context(storage, query, max_nodes=max_nodes)
    console.print(output)


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
):
    """Initialize config, build the graph, and configure Claude Code."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    if non_interactive:
        exts = [".py"]
        excl = []
    elif extensions:
        exts = [e.strip() for e in extensions.split(",") if e.strip()]
        excl = [e.strip() for e in exclude.split(",") if e.strip()] if exclude else []
    else:
        console.print("[bold cyan]ctxgraph-code setup[/bold cyan]")
        console.print("Let's configure your project graph.\n")

        ext_input = typer.prompt(
            "File extensions to scan (comma-separated)",
            default=".py",
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
    console.print(f"[green][OK] Initialized .ctxgraph/[/green]")

    with console.status(f"Scanning {', '.join(exts)} files in {path}..."):
        stats = build_graph(path, exclude_patterns=excl, extensions=exts)

    table = Table(title="Graph Build Complete")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Files Analyzed", str(stats["files_analyzed"]))
    table.add_row("Files Skipped", str(stats.get("files_skipped", 0)))
    table.add_row("Errors", str(stats.get("errors", 0)))
    table.add_row("Total Nodes", str(stats.get("total_nodes", 0)))
    table.add_row("Total Edges", str(stats.get("total_edges", 0)))
    table.add_row("Time", f"{stats.get('elapsed_seconds', 0)}s")
    console.print(table)
    console.print(f"[green][OK] Built graph[/green]")

    claude_dir = path / ".claude" / "commands"
    claude_dir.mkdir(parents=True, exist_ok=True)
    slash_path = claude_dir / "ctxgraph-code.md"

    storage = get_storage(path)
    build_label = _build_time_label(storage) if storage else "unknown"
    content = SLASH_COMMAND_TEMPLATE.format(build_time=build_label)

    if not slash_path.exists():
        slash_path.write_text(content, encoding="utf-8")
        console.print(f"[green][OK] Created {slash_path}[/green]")
    else:
        console.print(f"[yellow]  Skipped (already exists): {slash_path}[/yellow]")

    console.print()
    console.print("[bold green]Setup complete![/bold green]")
    console.print("Open Claude Code in this project and type [bold]/ctxgraph-code[/bold] to get started.")


@app.command()
def info(
    repo_path: Optional[str] = typer.Option(
        None, "--repo", "-r", help="Repository path"
    ),
):
    """Show graph statistics."""
    path = Path(repo_path).resolve() if repo_path else Path.cwd()

    storage = get_storage(path)
    if storage is None:
        console.print("[red]No graph found. Run [bold]ctxgraph-code build[/bold] first.[/red]")
        raise typer.Exit(1)

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


@app.command()
def version():
    """Show the version number."""
    from importlib.metadata import version as _v
    try:
        ver = _v("ctxgraph-code")
    except Exception:
        ver = "0.1.0"
    console.print(f"ctxgraph-code version [bold]{ver}[/bold]")


if __name__ == "__main__":
    app()
