"""
Opener — Codebase orientation radar.

Know what you're looking at, fast. Gives agents (and humans) a compact
orientation card showing what a file does, what's important, and what's
anomalous — without reading the whole thing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter

from scope.ast.engine.cache import load_cached_symbols, save_cached_symbols
from scope.ast.engine.rank import compute_importance
from scope.ast.engine.symbols import extract_symbols
from scope.engine.anomaly import detect_all
from scope.engine.classifier import classify_symbols
from scope.engine.extractor import extract_all
from scope.engine.parser import discover, parse_file
from scope.engine.ranker import read_order_with_lines
from scope.types import OrientationCard


def main() -> None:
    """CLI entry point — dispatch to orient or audit mode."""
    ap = argparse.ArgumentParser(
        description="Codebase orientation radar — JSON output",
        epilog=(
            "examples:\n"
            "  scope --path main.py                       Single file as JSON\n"
            "  scope --path src/                          Directory as JSON\n"
            "  scope --path src/ --mode audit             Repo-wide summary as JSON\n"
            "  pipe through jq for layout\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--path", default=None, help="File or directory to analyze")
    ap.add_argument(
        "--mode",
        choices=("orient", "audit"),
        default="orient",
        help="orient = per-file JSON (default), audit = repo-wide summary",
    )
    ap.add_argument(
        "--max-files",
        type=int,
        default=20,
        help="Maximum files to scan (default: 20)",
    )
    ap.add_argument("--no-cache", action="store_true", help="Bypass symbol cache")
    ap.add_argument(
        "--changed",
        nargs="?",
        const="HEAD",
        default=None,
        metavar="REF",
        help=(
            "Only analyze changed files: the working tree (no REF) or changed "
            "since the given REF (defaults to HEAD)"
        ),
    )
    ap.add_argument(
        "--schema", action="store_true", help="Print the JSON output schema and exit"
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="Emit the detailed per-symbol view (default is a compact summary)",
    )
    ap.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit 1 if any anomaly was detected (0 otherwise), like semgrep/lizard",
    )
    args = ap.parse_args()

    if args.schema:
        print(json.dumps(_scope_schema(), indent=2))
        return

    if not args.path:
        ap.error("the following arguments are required: --path")

    path = os.path.abspath(args.path)

    # Resolve symlinks
    if os.path.islink(path):
        path = os.path.realpath(path)

    if not os.path.exists(path):
        print(f"Error: path not found: {path}", file=sys.stderr)
        sys.exit(1)

    # --- Dispatch ---
    if os.path.isfile(path):
        _handle_file(path, None, full=args.full, exit_code=args.exit_code)
    elif os.path.isdir(path):
        if args.mode == "audit":
            _handle_directory_audit(
                path,
                args.max_files,
                not args.no_cache,
                args.changed,
                full=args.full,
                exit_code=args.exit_code,
            )
        else:
            _handle_directory_orient(
                path,
                args.max_files,
                not args.no_cache,
                args.changed,
                full=args.full,
                exit_code=args.exit_code,
            )
    else:
        print(f"Error: not a file or directory: {path}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# File handler
# ---------------------------------------------------------------------------


def _build_card(
    file_path: str,
    repo_path: str | None,
    ref_lookup: dict[tuple[str, str, int], int] | None = None,
    scope_symbols: list | None = None,
    repo_files: set[str] | None = None,
) -> OrientationCard | None:
    """Run with pipeline for a single file and return its orientation card.

    ``scope_symbols`` carries an already-extracted symbol list so directory
    passes don't re-parse the same file (see ``_collect_symbols_and_refs``).
    ``ref_lookup`` maps (file, name, line) -> cross-file reference count.
    ``repo_files`` is the known source file set, used for import classification.

    Returns None when there is nothing to show (no symbols and no source).
    """
    repo, rel_path = _resolve_repo_path(file_path, repo_path)
    result = parse_file(rel_path, repo, scope_symbols=scope_symbols)
    if not result.symbols and not result.source:
        return None

    if ref_lookup:
        for s in result.symbols:
            key = (rel_path, s.name, s.line)
            if key in ref_lookup:
                s.ref_count = ref_lookup[key]

    classify_symbols(result.symbols, repo)
    data = extract_all(
        result.symbols,
        result.comments,
        result.source,
        rel_path,
        repo,
        repo_files=repo_files,
    )
    anomalies = detect_all(result.symbols, result.source, data, rel_path, repo)

    role_counter: Counter[str] = Counter(
        s.role for s in result.symbols if s.role != "unknown"
    )
    role_counts: dict[str, int] = dict(role_counter)  # type: ignore[arg-type]

    return OrientationCard(
        file_path=rel_path,
        language=result.language,
        summary=data.summary,
        symbols=result.symbols,
        exports=data.exports,
        imports=data.imports,
        configs=data.configs,
        roles=role_counts,
        anomalies=anomalies,
        read_order=[],
        total_lines=result.total_lines,
    )


def _collect_symbols_and_refs(
    files: list[str],
    dir_path: str,
    max_files: int,
    use_cache: bool = True,
) -> tuple[dict[str, list], dict[tuple[str, str, int], int]]:
    """Directory-wide pass: get symbols once and compute cross-file refs.

    When ``use_cache`` and a matching signature exists, symbols are reloaded
    from the symbol cache instead of re-extracting (no file re-parse). Otherwise
    they're extracted and written back to the cache for the next run.

    Returns (scope_symbols, ref_lookup) where scope_symbols maps rel_path to the
    extracted symbol list and ref_lookup maps (file, name, line) -> ref count.
    """
    scope_symbols: dict[str, list] = {}

    if use_cache:
        cached = load_cached_symbols(dir_path, files, ".", max_files)
        if cached is not None:
            scope_symbols = cached  # type: ignore[assignment]

    if not scope_symbols:
        for rel_path in files:
            syms = extract_symbols(rel_path, dir_path)
            if syms:
                scope_symbols[rel_path] = syms
        if use_cache and scope_symbols:
            save_cached_symbols(dir_path, files, ".", max_files, scope_symbols)  # type: ignore[arg-type]

    if scope_symbols:
        compute_importance(scope_symbols, dir_path)

    ref_lookup: dict[tuple[str, str, int], int] = {}
    for file_path, syms in scope_symbols.items():
        for sym in syms:
            ref_lookup[(file_path, sym.name, sym.line)] = getattr(sym, "ref_count", 0)

    return scope_symbols, ref_lookup


# ---------------------------------------------------------------------------
# File handler
# ---------------------------------------------------------------------------


def _handle_file(
    file_path: str,
    repo_path: str | None,
    full: bool = False,
    exit_code: bool = False,
) -> OrientationCard | None:
    """Process a single file and print its (lean or full) JSON card."""
    card = _build_card(file_path, repo_path)
    if card is None:
        _, rel = _resolve_repo_path(file_path, repo_path)
        print(json.dumps({"file": rel, "symbols": [], "error": "no symbols extracted"}))
        return None

    payload = _card_to_dict(card) if full else _lean_card_dict(card)
    _attach_single_file_note(payload)
    _emit_json(payload, full)
    if exit_code and card.anomalies:
        sys.exit(1)
    return card


def _attach_single_file_note(payload: dict) -> None:
    """Clarify that graph fields are empty when there's no directory context."""
    payload["note"] = (
        "refs/blast_radius/importance are 0 here because no directory was scanned; "
        "run scope against a directory for graph ranking."
    )

# ---------------------------------------------------------------------------
# Directory handlers
# ---------------------------------------------------------------------------


def _handle_directory_orient(
    dir_path: str,
    max_files: int,
    use_cache: bool = True,
    changed: str | None = None,
    full: bool = False,
    exit_code: bool = False,
) -> None:
    """Process a directory and emit per-file orientation cards as JSON."""
    files = discover(dir_path)
    if not files:
        print(json.dumps({"error": "no supported source files"}))
        sys.exit(2)

    if changed is not None:
        files = _changed_files(files, dir_path, changed)
        if not files:
            print(json.dumps([]))
            return

    files = files[:max_files]
    repo_files = set(files) or None
    scope_symbols, ref_lookup = _collect_symbols_and_refs(
        files, dir_path, max_files, use_cache=use_cache
    )

    cards: list[OrientationCard] = []
    for rel_path in files:
        card = _build_card(
            os.path.join(dir_path, rel_path),
            dir_path,
            ref_lookup=ref_lookup,
            scope_symbols=scope_symbols.get(rel_path),
            repo_files=repo_files,
        )
        if card:
            cards.append(card)

    payloads = [(_card_to_dict if full else _lean_card_dict)(c) for c in cards]
    _emit_json(payloads, full)
    if exit_code and _any_anomalies(cards):
        sys.exit(1)


def _handle_directory_audit(
    dir_path: str,
    max_files: int,
    use_cache: bool = True,
    changed: str | None = None,
    full: bool = False,
    exit_code: bool = False,
) -> None:
    """Process a directory and emit the structural audit summary as JSON."""
    files = discover(dir_path)
    if not files:
        print(json.dumps({"error": "no supported source files"}))
        sys.exit(2)

    if changed is not None:
        files = _changed_files(files, dir_path, changed)
        if not files:
            print(json.dumps([]))
            return

    files = files[:max_files]
    repo_files = set(files) or None
    scope_symbols, ref_lookup = _collect_symbols_and_refs(
        files, dir_path, max_files, use_cache=use_cache
    )

    cards: list[OrientationCard] = []
    for rel_path in files:
        card = _build_card(
            os.path.join(dir_path, rel_path),
            dir_path,
            ref_lookup=ref_lookup,
            scope_symbols=scope_symbols.get(rel_path),
            repo_files=repo_files,
        )
        if card:
            cards.append(card)

    payloads = [(_card_to_dict if full else _lean_card_dict)(c) for c in cards]
    _emit_json(payloads, full)
    if exit_code and _any_anomalies(cards):
        sys.exit(1)


def _changed_files(files: list[str], dir_path: str, ref: str | None) -> list[str]:
    """Keep only ``files`` that changed in the working tree or since ``ref``.

    git emits repo-root-relative paths, so the scan subdir (``dir_path``) is
    correlated back to the actual repo root before matching. If git is
    unavailable, returns ``files`` unfiltered.
    """
    repo_root = _repo_root(dir_path)
    if not repo_root:
        return files

    commands = [
        ["git", "diff", "--name-only", ref or "HEAD"],
        ["git", "diff", "--name-only", "--cached"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]

    changed: set[str] = set()
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, cwd=repo_root, capture_output=True, text=True, timeout=20
            )
        except (OSError, subprocess.TimeoutExpired):
            return files
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip().replace("\\", "/")
                if line and line not in changed:
                    changed.add(line)

    if not changed:
        return []

    prefix = os.path.relpath(dir_path, repo_root).replace(os.sep, "/")
    matched: list[str] = []
    for f in files:
        rel_root = f if prefix == "." else f"{prefix}/{f}"
        if rel_root in changed:
            matched.append(f)
    return matched


def _repo_root(dir_path: str) -> str | None:
    """Walk up from ``dir_path`` to the nearest directory containing ``.git``."""
    path = os.path.abspath(dir_path)
    while True:
        if os.path.isdir(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def _scope_schema() -> dict:
    """Describe the stable JSON contract every card adheres to."""
    return {
        "version": 1,
        "mode": "orient | audit",
        "single_file": {
            "type": "object",
            "default": ["file", "language", "total_lines", "top", "roles", "anomalies"],
            "full": [
                "file", "language", "summary", "total_lines", "symbols",
                "read_order", "exports", "imports", "configs", "roles", "anomalies",
            ],
        },
        "directory": {"type": "array", "items": {"ref": "single_file"}},
        "symbol": {
            "name": "str",
            "kind": "str",
            "line": "int",
            "exported": "bool",
            "role": "str",
            "confidence": "str",
            "refs": "int",
            "importance": "float",
            "blast_radius": "int",
        },
        "role_values": [
            "entry_point", "pi_tool", "provider_config", "http_caller", "normalizer",
            "data_mapper", "config_value", "async_orchestrator", "predicate",
            "accessor", "mutator", "unknown",
        ],
        "note_single_file": "refs/blast_radius/importance are 0 outside a directory scan",
        "top": ["name", "role", "line", "blast"],
        "default": "compact summary (minified); --full emits the detailed card",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_repo_path(file_path: str, repo_path: str | None) -> tuple[str, str]:
    """Resolve a file path into (repo_root, relative_path).

    If the file is inside a known repo, returns the repo root and
    the relative path from there. Otherwise returns the parent dir
    and the basename.
    """
    if repo_path:
        abs_repo = os.path.abspath(repo_path)
        abs_file = os.path.abspath(file_path)
        if abs_file.startswith(abs_repo + os.sep):
            return abs_repo, os.path.relpath(abs_file, abs_repo)
        return abs_repo, os.path.basename(abs_file)

    # No repo path given — use file's parent dir as repo
    abs_file = os.path.abspath(file_path)
    parent = os.path.dirname(abs_file)
    return parent, os.path.basename(abs_file)


def _lean_card_dict(card: OrientationCard) -> dict:
    """Compact, agent-friendly summary: top-ranked symbols + counts only.

    The default output. Full per-symbol detail (refs, confidence, read order,
    exports, configs) is available with ``--full``.
    """
    top = sorted(
        card.symbols,
        key=lambda s: (s.importance, getattr(s, "ref_count", 0)),
        reverse=True,
    )[:8]
    return {
        "file": card.file_path,
        "language": card.language,
        "total_lines": card.total_lines,
        "top": [
            {"name": s.name, "role": s.role, "line": s.line, "blast": s.blast_radius}
            for s in top
        ],
        "roles": card.roles,
        "anomalies": [
            {"type": a.type, "severity": a.severity, "loc": a.locations}
            for a in card.anomalies
        ],
    }


def _any_anomalies(cards: list[OrientationCard]) -> bool:
    """True if any card reported at least one anomaly (for --exit-code)."""
    return any(bool(c.anomalies) for c in cards)


def _emit_json(payload: object, full: bool) -> None:
    """Print one JSON doc: pretty for --full, minified for the lean default."""
    if full:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, separators=(",", ":")))


def _card_to_dict(card: OrientationCard) -> dict:
    """Serialize an OrientationCard to a JSON-compatible dict.

    Higher-resolution than the compact text card: every symbol with its
    role/importance/blast radius, the ranked read order, and full anomaly
    details (including line locations).
    """
    read_order = [
        {"name": name, "line": line, "role": role, "refs": refs}
        for name, line, role, refs in read_order_with_lines(card.symbols)
    ]

    return {
        "file": card.file_path,
        "language": card.language,
        "summary": card.summary,
        "total_lines": card.total_lines,
        "symbols": [
            {
                "name": s.name,
                "kind": s.kind,
                "line": s.line,
                "exported": s.is_exported,
                "role": s.role,
                "confidence": s.confidence,
                "refs": s.ref_count,
                "importance": round(s.importance, 3),
                "blast_radius": s.blast_radius,
            }
            for s in card.symbols
        ],
        "read_order": read_order,
        "exports": card.exports,
        "imports": card.imports,
        "configs": [
            {"key": c.key, "value": c.value, "type": c.type, "line": c.line}
            for c in card.configs
        ],
        "roles": card.roles,
        "anomalies": [
            {
                "severity": a.severity,
                "type": a.type,
                "message": a.message,
                "locations": a.locations,
            }
            for a in card.anomalies
        ],
    }
