from __future__ import annotations

EXTENSION_LANG: dict[str, str] = {
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".pl": "perl",
    ".pm": "perl",
    ".lua": "lua",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".ex": "elixir",
    ".exs": "elixir",
    ".cs": "c_sharp",
    ".zig": "zig",
    ".jl": "julia",
    ".php": "php",
    ".phtml": "php",
    ".bash": "bash",
    ".sh": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".vue": "embedded_template",
    ".erb": "embedded_template",
    ".ejs": "embedded_template",
    ".f": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".m": "objc",
    ".mm": "objc",
    ".v": "verilog",
    ".vh": "verilog",
    ".sv": "verilog",
}

LANG_QUERIES: dict[str, dict[str, str]] = {
    # ── C ──────────────────────────────────────────────────────────
    "c": {
        "imports": r"""
            (preproc_include path: (string_literal) @path)
            (preproc_include path: (system_lib_string) @lib)
        """,
        "functions": r"""
            (function_definition
              declarator: (function_declarator declarator: (identifier) @name)
            ) @func
        """,
        "structs": r"""
            (struct_specifier name: (type_identifier) @name) @struct
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
    # ── C++ ────────────────────────────────────────────────────────
    "cpp": {
        "imports": r"""
            (preproc_include path: (string_literal) @path)
            (preproc_include path: (system_lib_string) @lib)
        """,
        "functions": r"""
            (function_definition
              declarator: (function_declarator declarator: (identifier) @name)
            ) @func
        """,
        "structs": r"""
            (struct_specifier name: (type_identifier) @name) @struct
        """,
        "classes": r"""
            (class_specifier name: (type_identifier) @name) @class
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
    # ── JavaScript ─────────────────────────────────────────────────
    "javascript": {
        "imports": r"""
            (import_statement source: (string) @source)
        """,
        "functions": r"""
            (function_declaration name: (identifier) @name) @func
        """,
        "classes": r"""
            (class_declaration name: (identifier) @name) @class
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
    # ── TypeScript ─────────────────────────────────────────────────
    "typescript": {
        "imports": r"""
            (import_statement source: (string) @source)
        """,
        "functions": r"""
            (function_declaration name: (identifier) @name) @func
        """,
        "classes": r"""
            (class_declaration name: (type_identifier) @name) @class
        """,
        "interfaces": r"""
            (interface_declaration name: (type_identifier) @name) @interface
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
    # ── Go ─────────────────────────────────────────────────────────
    "go": {
        "imports": r"""
            (import_declaration (import_spec) @import_path)
        """,
        "functions": r"""
            (function_declaration name: (identifier) @name) @func
        """,
        "types": r"""
            (type_declaration (type_spec name: (type_identifier) @name)) @type
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
    # ── Rust ───────────────────────────────────────────────────────
    "rust": {
        "imports": r"""
            (use_declaration (scoped_identifier) @path)
        """,
        "functions": r"""
            (function_item name: (identifier) @name) @func
        """,
        "structs": r"""
            (struct_item name: (type_identifier) @name) @struct
        """,
        "traits": r"""
            (trait_item name: (type_identifier) @name) @trait
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
    # ── Java ───────────────────────────────────────────────────────
    "java": {
        "imports": r"""
            (import_declaration scoped_identifier: (scoped_identifier) @path)
        """,
        "classes": r"""
            (class_declaration name: (identifier) @name) @class
        """,
        "interfaces": r"""
            (interface_declaration name: (identifier) @name) @interface
        """,
        "methods": r"""
            (method_declaration name: (identifier) @name) @method
        """,
        "calls": r"""
            (method_invocation name: (identifier) @call_name)
        """,
    },
    # ── Ruby ───────────────────────────────────────────────────────
    "ruby": {
        "imports": r"""
            (call method: (identifier "require") arguments: (argument_list (string) @path))
        """,
        "functions": r"""
            (method name: (identifier) @name) @method
        """,
        "classes": r"""
            (class name: (constant) @name) @class
        """,
        "modules": r"""
            (module name: (constant) @name) @module
        """,
        "calls": r"""
            (call method: (identifier) @call_name)
        """,
    },
    # ── Python (via tree-sitter, for non-ast fallback) ─────────────
    "python": {
        "functions": r"""
            (function_definition name: (identifier) @name) @func
        """,
        "classes": r"""
            (class_definition name: (identifier) @name) @class
        """,
        "calls": r"""
            (call_expression function: (identifier) @call_name)
        """,
    },
}

# Languages that support function calls extraction
CALL_SUPPORT: set[str] = {
    "c", "cpp", "javascript", "typescript", "go", "rust",
    "java", "ruby", "python",
}

# Languages that support class/type extraction
TYPE_SUPPORT: set[str] = {
    "c", "cpp", "javascript", "typescript", "go", "rust",
    "java", "ruby", "python",
}

# Languages that support import extraction
IMPORT_SUPPORT: set[str] = {
    "c", "cpp", "javascript", "typescript", "go", "rust",
    "java", "ruby",
}
