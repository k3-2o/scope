"""
Extractor — pulls file-level metadata from source.

Four independent extractors, all working from ParserResult:
  1. HEADER — first block comment (skip licenses)
  2. EXPORTS — export default + named exports
  3. IMPORTS — categorize by source type (built-in vs external vs internal)
  4. CONFIGS — module-level const/let with literal values

All can fail independently. None depend on each other.
"""

from __future__ import annotations

import re
from pathlib import Path

from scope._scope.engine.references import extract_imports as scope_extract_imports
from scope.types import ClassifiedSymbol, Comment, Config, ExtractedData

# ---------------------------------------------------------------------------
# License markers — skip these when looking for file headers
# ---------------------------------------------------------------------------

_LICENSE_MARKERS = {
    "copyright",
    "license",
    "mit",
    "apache",
    "bsd",
    "spdx",
    "all rights reserved",
    "all rights reserved.",
}

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def extract_all(
    symbols: list[ClassifiedSymbol],
    comments: list[Comment],
    source: str,
    file_path: str,
    repo_path: str,
) -> ExtractedData:
    """Run all extractors and return aggregated ExtractedData."""
    language = _detect_language(file_path)
    return ExtractedData(
        summary=_extract_header(comments),
        exports=_extract_exports(symbols, source, language),
        imports=_extract_imports(file_path, repo_path),
        configs=_extract_configs(source),
    )


# ---------------------------------------------------------------------------
# Header extraction
# ---------------------------------------------------------------------------


def _extract_header(comments: list[Comment]) -> str | None:
    """Extract the file summary from the first meaningful comment block.

    Strategy:
      1. Find the first block comment that is NOT a license header.
      2. Take the first paragraph (before first blank line) as the summary.
      3. If no block comment, check for consecutive line comments at the top.

    Returns None if no header found.
    """
    # --- Try block comments first ---
    for c in comments:
        text = c.text.strip()
        if not text:
            continue

        # Skip license headers
        if _is_license(text):
            continue

        # Extract first paragraph (everything before first blank line)
        paragraphs = re.split(r"\n\s*\n", text, maxsplit=1)
        summary = paragraphs[0].strip()

        # Skip if it's just a section divider like "// ----" or "// Types"
        if len(summary) < 10 or _is_divider(summary):
            continue

        # Clean up comment delimiters
        summary = _clean_comment_text(summary)
        if summary:
            return summary

    # --- Try line comments at top of file ---
    # (implemented by scanning source directly, since line comments
    #  are usually handled as individual Comment objects)
    return None


def _is_license(text: str) -> bool:
    """Check if a comment block is a license header."""
    first_200 = text.lower()[:200]
    return any(marker in first_200 for marker in _LICENSE_MARKERS)


def _is_divider(text: str) -> bool:
    """Check if text is just a section divider like -- or ==."""
    stripped = text.strip("-=*#/ \t\n")
    return len(stripped) < 5


def _clean_comment_text(text: str) -> str:
    """Remove comment syntax artifacts from extracted text.

    Handles:
      /* ... */  — remove leading /* and trailing */
      * ...     — remove leading asterisks on continuation lines
      // ...    — remove leading //
      # ...     — remove leading #
    """
    lines = text.split("\n")
    cleaned: list[str] = []

    for line in lines:
        # Remove block comment markers
        line = line.strip()
        line = re.sub(r"^/\*\*?\s*", "", line)  # opening /*
        line = re.sub(r"\s*\*/\s*$", "", line)  # closing */
        line = re.sub(r"^\s*\*\s?", "", line)  # leading * on continuation lines
        line = re.sub(r"^//\s?", "", line)  # //
        line = re.sub(r"^#\s?", "", line)  # #
        cleaned.append(line)

    # Join and strip
    result = "\n".join(cleaned).strip()
    return result


# ---------------------------------------------------------------------------
# Export extraction
# ---------------------------------------------------------------------------


def _extract_exports(symbols: list[ClassifiedSymbol], source: str, language: str = "") -> list[str]:
    """Extract exported symbol names.

    Language-aware:
      - JS/TS/MANY: exports with `export default`, `export function`, `export class`
      - Python: module-level `def` and `class` (everything at indent 0 is an export)
      - Go: capitalized names accessible to other packages
      - Rust: items preceded by `pub`
    """
    exports: list[str] = []

    # From symbol list (scope's is_exported flag — populated for Go/Rust)
    for sym in symbols:
        if sym.is_exported:
            name = sym.name
            if name not in exports:
                exports.append(name)

    # From source: per-language export patterns
    if language in ("TypeScript", "TSX", "JavaScript"):
        # JS/TS: export default function|class|const <name>
        named_default = re.search(
            r"\bexport\s+default\s+(?:function|class|const|let|var)\s+(\w+)",
            source,
        )
        if named_default:
            name = named_default.group(1)
            if name not in exports:
                exports.append(name)
        else:
            bare_default = re.search(r"\bexport\s+default\s+(\w+)\s*[;=]", source)
            if bare_default:
                name = bare_default.group(1)
                if name not in exports:
                    exports.append(name)
            else:
                anon_default = re.search(
                    r"\bexport\s+default\s+(?:function|class|const)\s*\(", source
                )
                if anon_default and "(anonymous)" not in exports:
                    exports.append("(anonymous)")

        # Named exports: `export function foo`, `export class Bar`, `export const Baz`
        for match in re.finditer(
            r"\bexport\s+(?:function|class|const|let|var|interface|type)\s+(\w+)",
            source,
        ):
            name = match.group(1)
            if name not in exports:
                exports.append(name)

    elif language == "Python":
        # Python: module-level def/class are public
        for line in source.splitlines():
            stripped = line.lstrip()
            if line.startswith(("def ", "class ")):
                # Extract name
                m = re.match(r"(?:def|class)\s+(\w+)", stripped)
                if m:
                    name = m.group(1)
                    if name not in exports:
                        exports.append(name)

    elif language in ("Go",):
        # Go: capitalized functions/types at module level are exported
        for m in re.finditer(r"^\s*func\s+([A-Z]\w+)", source, re.MULTILINE):
            name = m.group(1)
            if name not in exports:
                exports.append(name)
        for m in re.finditer(r"^\s*type\s+([A-Z]\w+)", source, re.MULTILINE):
            name = m.group(1)
            if name not in exports:
                exports.append(name)

    return sorted(set(exports))

    return sorted(set(exports))


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _extract_imports(file_path: str, repo_path: str) -> dict[str, list[str]]:
    """Extract and categorize imports.

    Categorizes into:
      - built_in: Python stdlib, Node.js builtins
      - external: third-party npm/pip packages
      - internal: relative imports (./ ../)

    Uses scope's extract_imports() for parsing, then re-categorizes.
    """
    result: dict[str, list[str]] = {
        "built_in": [],
        "external": [],
        "internal": [],
    }

    try:
        raw_imports = scope_extract_imports(repo_path, file_path)
    except Exception:
        return result

    for imp in raw_imports:
        if not imp:
            continue

        # Categorize
        if imp.startswith((".", "/")):
            result["internal"].append(imp)
        elif _is_built_in(imp):
            result["built_in"].append(imp)
        else:
            result["external"].append(imp)

    # Deduplicate and sort each category
    for key in result:
        result[key] = sorted(set(result[key]))

    return result


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    ext = Path(file_path).suffix.lower()
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
        ".hpp": "C++",
        ".cs": "C#",
        ".php": "PHP",
        ".kt": "Kotlin",
        ".swift": "Swift",
    }
    return mapping.get(ext, "")


def _is_built_in(name: str) -> bool:
    """Check if an import is a built-in module.

    Python builtins from sys.stdlib_module_names (Python 3.10+)
    Node.js builtins: node:* prefix, or well-known names.
    """
    # Node.js: node: prefix
    if name.startswith("node:"):
        return True

    # Python stdlib modules (common ones)
    python_stdlib = {
        "os",
        "sys",
        "re",
        "json",
        "math",
        "time",
        "datetime",
        "pathlib",
        "collections",
        "typing",
        "functools",
        "itertools",
        "argparse",
        "subprocess",
        "shutil",
        "glob",
        "tempfile",
        "hashlib",
        "base64",
        "textwrap",
        "dataclasses",
        "enum",
        "io",
        "abc",
        "threading",
        "multiprocessing",
        "asyncio",
        "logging",
        "warnings",
        "traceback",
        "inspect",
        "pprint",
        "copy",
        "random",
        "statistics",
        "uuid",
        "decimal",
        "fractions",
        "socket",
        "email",
        "html",
        "http",
        "urllib",
        "xml",
        "configparser",
        "csv",
        "zipfile",
        "tarfile",
        "pickle",
        "shelve",
        "sqlite3",
        "struct",
        "binascii",
        "string",
        "bisect",
        "array",
        "weakref",
        "types",
        "importlib",
        "pkgutil",
        "platform",
        "errno",
        "ctypes",
        "unittest",
        "pytest",
    }

    # Node.js built-in module names
    node_stdlib = {
        "fs",
        "path",
        "os",
        "http",
        "https",
        "url",
        "util",
        "stream",
        "events",
        "child_process",
        "crypto",
        "buffer",
        "assert",
        "net",
        "tls",
        "dns",
        "dgram",
        "cluster",
        "readline",
        "repl",
        "vm",
        "worker_threads",
        "perf_hooks",
        "async_hooks",
        "string_decoder",
        "querystring",
        "punycode",
        "zlib",
        "timers",
        "console",
        "process",
        "module",
    }

    base = name.split("/")[0].split(".")[0]
    return base in python_stdlib or base in node_stdlib


# ---------------------------------------------------------------------------
# Config extraction
# ---------------------------------------------------------------------------


def _extract_configs(source: str) -> list[Config]:
    """Extract module-level constants with literal values.

    Looks for patterns like:
      const FOO = 42;
      const BAR = "hello";
      let BAZ = true;
      FOO = "bar";          # Python-style module-level assignment

    Returns list of Config objects with key, value, type, line.
    Only captures primitive literals (number, string, boolean).
    Objects and arrays are noted with their type but not full content.
    """
    configs: list[Config] = []
    lines = source.splitlines()

    # Patterns
    # JS/TS: const/let/var NAME = <value>;
    # Python: NAME = <value>  (module-level, not preceded by def/class)
    # Go: const NAME = <value>
    # Rust: const NAME: type = <value>;
    # Ruby: NAME = <value>  (module-level)
    for i, line in enumerate(lines):
        stripped = line.strip()
        line_no = i + 1  # 1-indexed

        # Skip comments, empty lines, and indented code
        if not stripped or stripped.startswith(("#", "//", "/*", "*", "--")):
            continue
        if line.startswith((" ", "\t")):
            # Indented code — skip (not module-level)
            # But also catch return statements in objects
            continue

        config = _parse_config_line(stripped, line_no)
        if config:
            configs.append(config)

    return configs


def _parse_config_line(line: str, line_no: int) -> Config | None:
    """Try to parse a single line as a config assignment.

    Returns Config if the line contains a primitive literal assignment.
    """
    # Pattern: optional const/let/var/let/let, then NAME = <literal>
    # JS/TS:  const NAME = <literal>;
    # Python: NAME = <literal>
    # Go/Rust: const NAME = <literal>

    # Remove trailing semicolons
    line = line.rstrip(";")

    # Try: const|var|let NAME = value or just NAME = value (module-level Python)
    m = re.match(
        r"(?:(?:const|var|let|let)\s+)?"
        r"([A-Z_][A-Z0-9_]*)\s*[:=]?\s*"
        r"(true|false|True|False|"
        r"\d[\d_]*(?:\.\d+)?|"
        r"'[^']*'|\"[^\"]*\")"
        r"\s*$",
        line,
        re.IGNORECASE,
    )

    if not m:
        return None

    name = m.group(1)
    raw_value = m.group(2)

    # Determine type and clean value
    if raw_value.lower() in ("true", "false"):
        return Config(key=name, value=raw_value.lower(), type="boolean", line=line_no)

    # Number
    if re.match(r"^[\d_.]+$", raw_value):
        clean = raw_value.replace("_", "")
        if "." in clean:
            return Config(key=name, value=clean, type="number", line=line_no)
        else:
            return Config(key=name, value=clean, type="number", line=line_no)

    # String
    if raw_value.startswith(("'", '"')):
        clean = raw_value.strip("'\"")
        return Config(key=name, value=clean, type="string", line=line_no)

    return None
