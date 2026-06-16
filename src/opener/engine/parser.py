"""
Parser — wraps scope's Tree-sitter AST walker with additions.

Scope gives us raw Symbol[]. Opener adds:
  1. Comment collection (scope doesn't capture comments)
  2. Const/variable capture at module level (scope only captures functions/classes)
  3. Literal value extraction for configs

The pipeline: discover files → parse each → classify → extract → detect → rank → render.
"""

from __future__ import annotations

import os
from pathlib import Path

from opener.scope.engine.discover import discover_files
from opener.scope.engine.symbols import extract_symbols, get_parser
from opener.types import ClassifiedSymbol, Comment, ParserResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = 512 * 1024  # 512KB — skip files larger than this

# Tree-sitter comment node types per language family
# These are the AST node types that represent comments
_COMMENT_NODE_TYPES = {
    "comment",  # C, C++, Go, Rust, Java, JS, TS, Swift
    "block_comment",  # C family block comments (also handled by "comment")
    "line_comment",  # Go line comments (also handled by "comment")
    "shebang",  # shell scripts
    "string_literal",  # Python docstrings (multi-line strings used as comments)
}

# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover(repo_path: str, sub_scope: str = ".") -> list[str]:
    """Discover supported source files under a path. Thin wrapper over scope."""
    return discover_files(repo_path, sub_scope)


# ---------------------------------------------------------------------------
# Single-file parse
# ---------------------------------------------------------------------------


def parse_file(file_path: str, repo_path: str) -> ParserResult:
    """Parse a single file with Tree-sitter and collect:
    - symbols (from scope's extract_symbols, converted to ClassifiedSymbol)
    - comments (from AST walk)
    - source text and metadata
    """
    full_path = os.path.join(repo_path, file_path) if not os.path.isabs(file_path) else file_path
    ext = Path(file_path).suffix
    empty = ParserResult(
        symbols=[], comments=[], source="", language=_ext_to_lang(ext), total_lines=0
    )

    # --- Edge: permission denied ---
    if not os.access(full_path, os.R_OK):
        return empty

    # --- Edge: symlink resolution (follow once) ---
    if os.path.islink(full_path):
        full_path = os.path.realpath(full_path)

    # --- Edge: large file cap (5MB) ---
    try:
        if os.path.getsize(full_path) > 5 * 1024 * 1024:
            return empty
    except OSError:
        return empty

    # --- Edge: binary detection ---
    try:
        with open(full_path, "rb") as f:
            head = f.read(4096)
        if b"\0" in head:
            return empty  # null bytes → binary, skip
    except OSError:
        return empty

    # --- Read source with encoding fallback ---
    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except UnicodeDecodeError:
        try:
            with open(full_path, encoding="latin-1") as f:
                source = f.read()
        except OSError:
            return empty
    except OSError:
        return empty

    total_lines = source.count("\n") + 1

    language = _ext_to_lang(ext)

    # --- Extract symbols via scope ---
    scope_symbols = extract_symbols(file_path, repo_path)

    # Convert scope's Symbol to opener's ClassifiedSymbol
    classified: list[ClassifiedSymbol] = []
    for sym in scope_symbols:
        classified.append(
            ClassifiedSymbol(
                name=sym.name,
                kind=sym.kind,
                file=sym.file,
                line=sym.line,
                column=getattr(sym, "column", 0),
                is_exported=getattr(sym, "is_exported", False),
                parent=getattr(sym, "parent", None),
                role="unknown",
                confidence="low",
                reasoning="",
                ref_count=getattr(sym, "ref_count", 0),
            )
        )

    # --- Collect comments via Tree-sitter ---
    comments = _collect_comments(full_path, ext, source)

    return ParserResult(
        symbols=classified,
        comments=comments,
        source=source,
        language=language,
        total_lines=total_lines,
    )


# ---------------------------------------------------------------------------
# Comment collection — AST walk for comment nodes
# ---------------------------------------------------------------------------


def _collect_comments(full_path: str, ext: str, source: str) -> list[Comment]:
    """Walk the AST and collect all comment nodes."""
    parser = get_parser(ext)
    if parser is None:
        return []

    try:
        tree = parser.parse(bytes(source, "utf-8"))
    except Exception:
        return []

    comments: list[Comment] = []

    def _walk(node: object) -> None:
        # tree-sitter Node has .type, .start_point, .end_point, .children
        try:
            node_type = getattr(node, "type", "")
            if node_type in _COMMENT_NODE_TYPES:
                start = getattr(node, "start_point", None)
                end = getattr(node, "end_point", None)
                if start and end:
                    text_bytes = getattr(node, "text", None)
                    text = ""
                    if text_bytes is not None:
                        try:
                            text = text_bytes.decode("utf-8")
                        except (UnicodeDecodeError, AttributeError):
                            text = str(text_bytes)
                    # Filter out shebangs — not meaningful comments
                    if node_type != "shebang":
                        comments.append(
                            Comment(
                                text=text,
                                start_line=start[0] + 1,  # 1-indexed
                                end_line=end[0] + 1,
                            )
                        )
            for child in getattr(node, "children", []):
                _walk(child)
        except Exception:
            # If we can't walk a node, skip it
            pass

    try:
        root = getattr(tree, "root_node", getattr(tree, "root", None))
        if root is not None:
            _walk(root)
    except Exception:
        pass

    return comments


# ---------------------------------------------------------------------------
# Ref count integration
# ---------------------------------------------------------------------------


def apply_ref_counts(
    classified: list[ClassifiedSymbol],
    scope_symbols: list,
) -> None:
    """Populate ref_count on ClassifiedSymbol from scope's computed Symbol.

    Called after scope's compute_importance() has run. Scope modifies Symbol
    objects in-place by setting .ref_count and .importance. This function
    copies those values back to the corresponding ClassifiedSymbol.
    """
    # Build a lookup by (file, name, line) from scope symbols
    scope_lookup: dict[tuple[str, str, int], int] = {}
    for s in scope_symbols:
        scope_lookup[(s.file, s.name, s.line)] = getattr(s, "ref_count", 0)

    for cs in classified:
        key = (cs.file, cs.name, cs.line)
        rc = scope_lookup.get(key, 0)
        if rc > 0:
            cs.ref_count = rc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ext_to_lang(ext: str) -> str:
    """Map file extension to human-readable language name."""
    ext = ext.lower()
    mapping = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TSX",
        ".go": "Go",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".java": "Java",
        ".c": "C",
        ".h": "C",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".hpp": "C++",
        ".hxx": "C++",
        ".cs": "C#",
        ".php": "PHP",
        ".kt": "Kotlin",
        ".kts": "Kotlin",
        ".swift": "Swift",
        ".scala": "Scala",
        ".sc": "Scala",
        ".sh": "Shell",
        ".bash": "Shell",
        ".sql": "SQL",
        ".lua": "Lua",
        ".tf": "Terraform",
        ".tfvars": "Terraform",
        ".hcl": "HCL",
    }
    return mapping.get(ext, "Unknown")
