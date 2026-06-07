# ctxgraph-code

**Code knowledge graph for Claude Code.** Build a relationship graph of your Python codebase so Claude Code understands imports, class hierarchies, function calls, and cross-file dependencies without reading every file.

```bash
pip install ctxgraph-code
cd my-project
ctxgraph-code setup
```

Then in Claude Code, type `/ctxgraph-code` and Claude will use the graph.

---

## Why?

Claude Code already reads files, searches code, and understands syntax. But it can't see **relationships** between files without manual exploration:

- *What does this file import?*
- *What depends on this function?*
- *Where is this class defined?*
- *What calls this API endpoint?*

These questions require running multiple `grep` commands or reading dependency chains file by file. `ctxgraph-code` pre-computes all of this via static AST analysis and stores it in a queryable SQLite graph — so Claude can answer relationship questions in one command.

## Quick Start

```bash
# Install
pip install ctxgraph-code

# Navigate to your Python project
cd my-project

# One-command setup: init + build + configure Claude Code
ctxgraph-code setup

# Open Claude Code and type:
#   /ctxgraph-code
```

## Commands

### `setup` (recommended)

```bash
ctxgraph-code setup
```

Interactive walkthrough — prompts for:
- **File extensions** to scan (`.py`, `.js`, `.ts`, etc.)
- **Exclude patterns** (folders like `tests/`, globs like `*.generated.py`)

Does everything in one step:
1. Creates `.ctxgraph/config.toml` with your chosen extensions and excludes
2. Builds the knowledge graph from all matching files
3. Creates `.claude/commands/ctxgraph-code.md` with instructions for Claude Code

Non-interactive mode (skip prompts):
```bash
ctxgraph-code setup --extensions .py,.js,.ts --exclude tests/,examples/
ctxgraph-code setup -y                                 # all defaults
```

### `init`

```bash
ctxgraph-code init
```

Creates the `.ctxgraph/` directory with a default `config.toml`.

### `build`

```bash
ctxgraph-code build
ctxgraph-code build --extensions .py,.js,.ts
ctxgraph-code build --exclude tests/ --exclude *.generated.py
```

Scans all matching files in the project, runs AST analysis. Extensions are read from config (`.py` by default, or whatever was set in `setup`).

- **Imports**: which files import other files
- **Class definitions**: class names, base classes, methods
- **Function definitions**: function names, arguments
- **Function calls**: which functions call which (within the project)
- **Docstrings**: extracted as node summaries

Stores the result in `.ctxgraph/graph.db`.

> The graph is a **static snapshot**. If code changes, run `ctxgraph-code build` again to refresh. Claude Code will also rebuild when it detects the graph is stale.

### `query`

```bash
ctxgraph-code query "user authentication"
ctxgraph-code query "database connection" --max 20
```

Searches the graph by relevance scoring (name matches > summary matches > path matches) and expands to neighboring nodes via BFS up to depth 2.

### `deps`

```bash
ctxgraph-code deps src/api/routes.py
```

Shows all relationships for a file: imports, imported-by, function calls, class definitions.

### `usedby`

```bash
ctxgraph-code usedby src/utils/helpers.py
```

Shows every file that imports or calls something in the given file. Useful to understand **ripple effects** before making changes.

### `overview`

```bash
ctxgraph-code overview
```

Prints the project structure: every file with its summary and top-level symbols.

### `symbols`

```bash
ctxgraph-code symbols src/main.py
```

Lists all classes and functions defined in a file, with line numbers and docstring summaries.

### `context`

```bash
ctxgraph-code context "add pagination to the users endpoint"
```

Generates a focused context summary: relevant files, their symbols, and dependency/call edges between them. This is the closest equivalent to `ctxgraph`'s capsule format.

### `info`

```bash
ctxgraph-code info
```

Shows graph statistics: node/edge counts, type distribution, build time.

---

## How It Works

```
Python files  ──AST──>  Import/Symbol/Call analysis  ──>  SQLite graph.db
                                                               │
Claude Code  ──/ctxgraph-code──>  CLI query/deps/overview  <────┘
```

1. **Build phase**: `ctxgraph-code build` parses every `.py` file with Python's `ast` module. It extracts imports, class/function definitions, function calls, and docstrings. The result is a graph of **nodes** (files, classes, functions) and **edges** (imports, defines, extends, calls) stored in SQLite.

2. **Query phase**: In Claude Code, the `/ctxgraph-code` slash command injects instructions into the conversation. Claude then runs `ctxgraph-code` commands as shell commands to query the graph. Claude reads the text output and reasons about it alongside its own file-reading capabilities.

### What's in the graph

| Node type | Example ID | Stored |
|-----------|-----------|--------|
| `file` | `file:src/api/routes.py` | Name, path, size, summary |
| `class` | `class:src/api/routes.py::UserAPI` | Name, path, parent file, docstring, line number |
| `function` | `func:src/models.py::get_user` | Name, path, parent, docstring, line number |

| Edge relation | Meaning |
|--------------|---------|
| `imports` | File A imports file B (or a symbol from it) |
| `defines` | A file/class defines a class/function |
| `extends` | Class A extends class B |
| `calls` | Function A calls function B |

Edge weights: `imports=1.0`, `defines=1.0`, `extends=0.8`, `calls=0.7`

### Query relevance scoring

1. Tokenize query (lowercase, split on word boundaries, remove stopwords)
2. For each matching node: name match → +2.0 per token, text match → +0.5 per occurrence
3. Multiply by `0.5 + importance` (files=0.5, classes=0.6, functions=0.5)
4. BFS expansion: neighbor nodes get `0.1 × number_of_matched_neighbors`
5. Return top-N results sorted by score

---

## Using with Claude Code

After `ctxgraph-code setup`, Claude Code in the project directory will have the `/ctxgraph-code` slash command available.

When you type `/ctxgraph-code`, Claude sees:

```
# ctxgraph-code: Code Relationship Graph

This project has a knowledge graph at `.ctxgraph/graph.db`.
The graph knows about imports, class hierarchies, and function calls.

Available commands:
- ctxgraph-code query "search terms"  -- Find relevant files, classes, and functions
- ctxgraph-code deps <path>           -- Show what a file imports and what calls it
- ctxgraph-code usedby <path>         -- Show what depends on a file
- ctxgraph-code overview              -- Show the full project structure
- ctxgraph-code symbols <path>        -- List classes/functions defined in a file
- ctxgraph-code context "task"        -- Generate a focused context summary
```

Claude then uses these commands as needed during the conversation.

### Example workflow

**You:** "Add rate limiting to the user API endpoints"

**Claude does:**
1. `ctxgraph-code query "user api endpoint rate limit"` → finds relevant files
2. `ctxgraph-code deps src/api/users.py` → sees what it imports and what calls it
3. Reads actual source via built-in `read` tool
4. Writes the rate-limiting code, knowing the full dependency context

---

## Configuration

Configure via `.ctxgraph/config.toml` (created interactively by `setup` or manually):

```toml
[graph]
# File extensions to scan
extensions = [".py", ".js", ".ts"]
# Exclude patterns beyond built-in defaults
exclude = ["tests/", "examples/"]
# Follow symlinks when scanning
follow_symlinks = false
# Skip files larger than this (MB)
max_file_size_mb = 5
```

Built-in default exclusion patterns (always applied): `__pycache__`, `*.pyc`, `.git`, `node_modules`, `venv`, `.venv`, `dist`, `build`, `*.egg-info`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.tox`, `migrations`, `*.min.js`, `*.min.css`.

---

## Differences from `ctxgraph`

`ctxgraph-code` is a **focused subset** of [ctxgraph](https://github.com/shashi3070/ctxgraph) designed specifically for Claude Code.

| Feature | ctxgraph | ctxgraph-code |
|---------|----------|---------------|
| CLI commands | 9 (build, capsule, query, view, serve, info, init, ask, chat, history, skill) | 8 (init, build, query, deps, usedby, overview, symbols, context, setup, info) |
| LLM integration | Built-in (Ollama, Claude, OpenAI, Azure) | None (delegates to Claude Code) |
| Chat sessions | Yes | No |
| Visualizer | D3.js HTML + SVG | No |
| Skills system | Yes (customizable skill TOML files) | No |
| MCP server | Yes | No |
| Token savings | Yes (capsule DSL compression) | No |
| Dependency | `mcp` optional, `anyio` optional | `typer`, `rich` only |
| Claude integration | MCP protocol (Claude Desktop) | Slash command (Claude Code) |
| Windows compatibility | Blocked by `pywintypes.dll` with mcp≥1.27.2 | No issues |

## Requirements

- Python 3.10+
- A Claude Code subscription (for the `/ctxgraph-code` slash command — the graph itself works standalone)

---

## License

MIT
