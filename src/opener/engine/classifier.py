"""
Classifier — takes raw symbols and assigns roles.

Two-phase classification:
  1. STRUCTURAL: check the symbol's definition in source for specific patterns
     (object shapes, function calls, control flow) → high confidence
  2. NAMING: check the symbol's name against known conventions → medium confidence

If neither matches → role: "unknown", confidence: "low".
"""

from __future__ import annotations

import re
from pathlib import Path

from opener.types import ClassifiedSymbol

# ---------------------------------------------------------------------------
# Naming patterns — checked by prefix/suffix
# ---------------------------------------------------------------------------

_NORMALIZER_PREFIXES = (
    "normalize",
    "transform",
    "parse",
    "serialize",
    "deserialize",
    "convert",
    "format",
    "render",
)

_ACCESSOR_PREFIXES = (
    "get",
    "fetch",
    "load",
    "read",
    "query",
    "search",
    "resolve",
    "find",
    "lookup",
    "collect",
)

_MUTATOR_PREFIXES = (
    "set",
    "save",
    "write",
    "update",
    "delete",
    "remove",
    "create",
    "insert",
    "put",
    "patch",
    "destroy",
    "clear",
)

_PREDICATE_PREFIXES = (
    "is",
    "has",
    "can",
    "should",
    "contains",
    "exists",
)

_ASYNC_PREFIXES = (
    "poll",
    "watch",
    "subscribe",
    "listen",
)

_ENTRY_NAMES = (
    "main",
    "handler",
    "serve",
    "start",
    "run",
    "app",
    "execute",
)

# ---------------------------------------------------------------------------
# Structural patterns — checked by scanning source text
# ---------------------------------------------------------------------------

# A provider config typically defines url + envKey + buildHeaders + normalize + buildBody
_PROVIDER_CONFIG_KEYS = {"url", "envkey", "buildheaders", "buildbody", "normalize"}

# A pi tool registration has execute, renderCall, renderResult, parameters
_PI_TOOL_KEYS = {"execute", "rendercall", "renderresult", "parameters"}

# HTTP client method calls
_HTTP_CALL_PATTERNS = re.compile(
    r"\b(fetch|axios\.(get|post|put|patch|delete)|requests\.(get|post|put|delete))\s*\("
)

# Async orchestration: polling loop with AbortSignal
_ASYNC_PATTERN = re.compile(
    r"\b(AbortSignal|signal\.aborted|pollInterval|poll_interval|maxWait|max_wait|while\s*\(.*deadline)"
)

# Data mapping: .map().join() chain
_DATA_MAP_PATTERN = re.compile(r"\.map\s*\([^)]*\)\s*\n?\s*\.join\s*\(")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def classify_symbols(symbols: list[ClassifiedSymbol], repo_path: str) -> list[ClassifiedSymbol]:
    """Assign roles to all symbols."""
    for sym in symbols:
        _classify_one(sym, repo_path)
    return symbols


# ---------------------------------------------------------------------------
# Single-symbol classification
# ---------------------------------------------------------------------------


def _classify_one(sym: ClassifiedSymbol, repo_path: str) -> None:
    """Classify a single symbol. Modifies sym in place."""
    # Step 1: Naming checks (medium confidence)
    # Run BEFORE structural because names are more reliable than
    # noisy source-window scanning. E.g., normalize* should be
    # normalizer even if the source window bleeds into other objects.
    if _classify_by_name(sym):
        return

    # Step 2: Structural checks (high confidence)
    # Skip interfaces/type declarations — they have no runtime structure
    no_struct_kinds = ("interface", "type", "type_alias")
    if sym.kind not in no_struct_kinds and _classify_by_structure(sym, repo_path):
        return

    # Step 3: Fallback
    sym.role = "unknown"
    sym.confidence = "low"
    sym.reasoning = "No structural or naming pattern matched"


# ---------------------------------------------------------------------------
# Structural classification
# ---------------------------------------------------------------------------


def _classify_by_structure(sym: ClassifiedSymbol, repo_path: str) -> bool:
    """Try to classify by examining the symbol's definition in source.

    Reads the source file and checks for structural patterns around
    the symbol's definition line.
    """
    source = _read_symbol_source(sym, repo_path)
    if not source:
        return False

    source_lower = source.lower()

    # --- Provider config ---
    # Object literal with keys matching provider config pattern
    matched_keys = _PROVIDER_CONFIG_KEYS & set(_extract_object_keys(source_lower))
    if len(matched_keys) >= 3:
        sym.role = "provider_config"
        sym.confidence = "high"
        keys_str = ", ".join(sorted(matched_keys))
        sym.reasoning = f"Object has {len(matched_keys)} provider config keys: {keys_str}"
        return True

    # --- Pi tool ---
    matched_keys = _PI_TOOL_KEYS & set(_extract_object_keys(source_lower))
    if len(matched_keys) >= 3:
        sym.role = "pi_tool"
        sym.confidence = "high"
        keys_str = ", ".join(sorted(matched_keys))
        sym.reasoning = f"Object has {len(matched_keys)} pi tool keys: {keys_str}"
        return True

    # --- HTTP caller ---
    if _HTTP_CALL_PATTERNS.search(source):
        sym.role = "http_caller"
        sym.confidence = "high"
        sym.reasoning = "Function body calls fetch() or HTTP client"
        return True

    # --- Async orchestrator ---
    if _ASYNC_PATTERN.search(source):
        sym.role = "async_orchestrator"
        sym.confidence = "high"
        sym.reasoning = "Uses AbortSignal with polling/deadline pattern"
        return True

    # --- Data mapper ---
    if _DATA_MAP_PATTERN.search(source):
        sym.role = "data_mapper"
        sym.confidence = "medium"
        sym.reasoning = "Chains .map().join() on array"
        return True

    return False


# ---------------------------------------------------------------------------
# Naming-based classification
# ---------------------------------------------------------------------------


def _classify_by_name(sym: ClassifiedSymbol) -> bool:
    """Try to classify by the symbol's name alone.

    Multi-language support:
      - Strips leading underscores (Python private convention)
      - Case-insensitive prefix matching (handles Go CamelCase)
      - Language-agnostic entry point detection
    """
    raw_name = sym.name
    # Normalize: strip Python private prefix, lowercase for matching
    name = raw_name.lstrip("_").lower()

    # --- Entry point ---
    if sym.is_exported and _is_entry_name(name):
        sym.role = "entry_point"
        sym.confidence = "medium"
        sym.reasoning = f"Exported symbol named '{raw_name}' — likely entry point"
        return True

    # --- Entry point (unexported but named execute/handler/main) ---
    if name in ("execute", "handler", "main", "serve"):
        sym.role = "entry_point"
        sym.confidence = "medium"
        sym.reasoning = f"Named '{raw_name}' — likely a framework entry method"
        return True

    # --- Go/Rust constructor pattern ---
    if name.startswith("new"):
        sym.role = "entry_point"
        sym.confidence = "medium"
        sym.reasoning = "Constructor pattern — named 'new'"
        return True

    # --- Normalizer ---
    if name.startswith(_NORMALIZER_PREFIXES):
        sym.role = "normalizer"
        sym.confidence = "medium"
        sym.reasoning = f"Name '{raw_name}' starts with normalizer prefix"
        return True

    # --- Predicate ---
    if name.startswith(_PREDICATE_PREFIXES):
        sym.role = "predicate"
        sym.confidence = "medium"
        sym.reasoning = f"Name '{raw_name}' starts with predicate prefix"
        return True

    # --- Async orchestrator (by name) ---
    if name.startswith(_ASYNC_PREFIXES):
        sym.role = "async_orchestrator"
        sym.confidence = "medium"
        sym.reasoning = f"Name '{raw_name}' starts with async/orchestrator prefix"
        return True

    # --- Accessor ---
    if name.startswith(_ACCESSOR_PREFIXES):
        sym.role = "accessor"
        sym.confidence = "medium"
        sym.reasoning = f"Name '{raw_name}' starts with accessor prefix"
        return True

    # --- Mutator ---
    if name.startswith(_MUTATOR_PREFIXES):
        sym.role = "mutator"
        sym.confidence = "medium"
        sym.reasoning = f"Name '{raw_name}' starts with mutator prefix"
        return True

    # --- Config value (UPPER_SNAKE_CASE with literal) ---
    if raw_name.isupper() and "_" in raw_name:
        sym.role = "config_value"
        sym.confidence = "low"
        sym.reasoning = "UPPER_SNAKE_CASE name — likely a constant"
        return True

    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_entry_name(name: str) -> bool:
    """Check if the name matches a known entry-point pattern."""
    base = name.lower()
    if base in _ENTRY_NAMES:
        return True
    return bool(base.endswith("handler") or base.endswith("controller") or base.endswith("service"))


def _read_symbol_source(sym: ClassifiedSymbol, repo_path: str) -> str | None:
    """Read the source text around the symbol's definition.

    Returns a window of source text from the symbol's line to the end
    of its definition (or up to 50 lines ahead).
    """
    if not sym.file:
        return None

    full_path = Path(repo_path) / sym.file
    if not full_path.exists():
        return None

    try:
        lines = full_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    if sym.line < 1 or sym.line > len(lines):
        return None

    # Read from symbol line to end of file (up to 80 lines, enough for most definitions)
    start = sym.line - 1  # 0-indexed
    end = min(start + 80, len(lines))
    return "\n".join(lines[start:end])


def _extract_object_keys(source_lower: str) -> set[str]:
    """Extract object property/literal keys from source text.

    Uses a simple regex to find key: value or key() patterns
    in an object literal context.
    """
    # Match lines that look like object property definitions:
    #   key: value,
    #   key() { ... }
    #   key,
    keys: set[str] = set()

    # Find all word-like identifiers that appear before : or (
    pattern = re.compile(r"^\s*['\"]?(\w+)['\"]?\s*[:\(]")
    for line in source_lower.splitlines():
        m = pattern.match(line)
        if m:
            keys.add(m.group(1).lower())

    return keys
