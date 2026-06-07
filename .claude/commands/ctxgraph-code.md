# ctxgraph-code: Code Relationship Graph

This project has a knowledge graph at `.ctxgraph/graph.db`.
The graph knows about imports, class hierarchies, and function calls.

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
