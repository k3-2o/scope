"""
Opener — Codebase orientation radar.

Know what you're looking at, fast. Gives agents (and humans) a compact
orientation card showing what a file does, what's important, and what's
anomalous — without reading the whole thing.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from opener.engine.anomaly import detect_all
from opener.engine.classifier import classify_symbols
from opener.engine.extractor import extract_all
from opener.engine.parser import discover, parse_file
from opener.render.card import render_audit_summary, render_card, render_directory_summary
from opener.scope.engine.rank import compute_importance
from opener.scope.engine.symbols import extract_symbols
from opener.types import OrientationCard


def main() -> None:
    """CLI entry point — dispatch to orient or audit mode."""
    ap = argparse.ArgumentParser(
        description="Codebase orientation radar — know what you're looking at, fast",
        epilog=(
            "examples:\n"
            "  opener --path main.py                          Single file card\n"
            "  opener --path src/                              Directory cards\n"
            "  opener --path src/ --mode audit                 Repo health\n"
            "  opener --path src/ --verbose                    Full detail\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--path", required=True, help="File or directory to analyze")
    ap.add_argument(
        "--mode",
        choices=("orient", "audit"),
        default="orient",
        help="orient = per-file cards (default), audit = repo-wide summary",
    )
    ap.add_argument("--verbose", action="store_true", help="Show full card instead of compact")
    ap.add_argument(
        "--max-files",
        type=int,
        default=20,
        help="Maximum files to scan (default: 20)",
    )
    ap.add_argument("--no-cache", action="store_true", help="Bypass symbol cache")
    ap.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text)",
    )
    args = ap.parse_args()

    path = os.path.abspath(args.path)

    # Resolve symlinks
    if os.path.islink(path):
        path = os.path.realpath(path)

    if not os.path.exists(path):
        print(f"Error: path not found: {path}", file=sys.stderr)
        sys.exit(1)

    # --- Dispatch ---
    if os.path.isfile(path):
        _handle_file(path, None, args.verbose, args.output)
    elif os.path.isdir(path):
        if args.mode == "audit":
            _handle_directory_audit(path, args.max_files, args.output)
        else:
            _handle_directory_orient(path, args.max_files, args.verbose, args.output)
    else:
        print(f"Error: not a file or directory: {path}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# File handler
# ---------------------------------------------------------------------------


def _handle_file(
    file_path: str,
    repo_path: str | None,
    verbose: bool,
    output: str,
) -> OrientationCard | None:
    """Process a single file and render its orientation card."""
    repo, rel_path = _resolve_repo_path(file_path, repo_path)

    result = parse_file(rel_path, repo)
    if not result.symbols and not result.source:
        if output != "json":
            print(f"No symbols extracted from {rel_path}")
        return None

    classify_symbols(result.symbols, repo)
    data = extract_all(result.symbols, result.comments, result.source, rel_path, repo)
    anomalies = detect_all(result.symbols, result.source, data, rel_path, repo)

    role_counter = Counter(s.role for s in result.symbols if s.role != "unknown")
    role_counts: dict[str, int] = dict(role_counter)  # type: ignore[arg-type]

    card = OrientationCard(
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

    if output == "json":
        import json as j

        print(j.dumps(_card_to_dict(card), indent=2))
    else:
        print(render_card(card, verbose=verbose))

    return card


# ---------------------------------------------------------------------------
# Directory handlers
# ---------------------------------------------------------------------------


def _handle_directory_orient(dir_path: str, max_files: int, verbose: bool, output: str) -> None:
    """Process a directory and show per-file cards.

    Uses two-phase processing for cross-file reference counting:
      1. Parse all files with scope to get raw symbols
      2. Compute cross-file importance (ref_counts)
      3. Apply ref_counts back to classified symbols
      4. Render each file's card
    """
    files = discover(dir_path)
    if not files:
        print("No supported source files found.")
        sys.exit(2)

    files = files[:max_files]

    # --- Phase 1: collect raw scope symbols ---
    scope_symbols: dict[str, list] = {}
    for rel_path in files:
        syms = extract_symbols(rel_path, dir_path)
        if syms:
            scope_symbols[rel_path] = syms

    # --- Phase 2: compute cross-file importance ---
    if scope_symbols:
        compute_importance(scope_symbols, dir_path)

    # Build nested ref_count lookup: (file, name, line) -> ref_count
    ref_lookup: dict[tuple[str, str, int], int] = {}
    for file_path, syms in scope_symbols.items():
        for sym in syms:
            ref_lookup[(file_path, sym.name, sym.line)] = getattr(sym, "ref_count", 0)

    # --- Phase 3: full opener pipeline per file ---
    cards: list[OrientationCard] = []
    for rel_path in files:
        card = _handle_file(os.path.join(dir_path, rel_path), dir_path, verbose, output)
        if card:
            # Apply pre-computed ref_counts
            for s in card.symbols:
                key = (card.file_path, s.name, s.line)
                if key in ref_lookup:
                    s.ref_count = ref_lookup[key]
            cards.append(card)

    if not cards:
        return

    # Show aggregated summary
    if output != "json":
        print()
        print(render_directory_summary(cards))


def _handle_directory_audit(dir_path: str, max_files: int, output: str) -> None:
    """Process a directory and show structural audit summary."""
    files = discover(dir_path)
    if not files:
        print("No supported source files found.")
        sys.exit(2)

    files = files[:max_files]

    # --- Phase 1: collect raw scope symbols ---
    scope_symbols: dict[str, list] = {}
    for rel_path in files:
        syms = extract_symbols(rel_path, dir_path)
        if syms:
            scope_symbols[rel_path] = syms

    if scope_symbols:
        compute_importance(scope_symbols, dir_path)

    ref_lookup: dict[tuple[str, str, int], int] = {}
    for file_path, syms in scope_symbols.items():
        for sym in syms:
            ref_lookup[(file_path, sym.name, sym.line)] = getattr(sym, "ref_count", 0)

    # --- Phase 2: full opener pipeline per file ---
    cards: list[OrientationCard] = []
    for rel_path in files:
        full_path = os.path.join(dir_path, rel_path)
        repo, rp = _resolve_repo_path(full_path, dir_path)
        result = parse_file(rp, repo)
        if not result.symbols:
            continue

        # Apply ref_counts before classification
        for s in result.symbols:
            key = (rp, s.name, s.line)
            if key in ref_lookup:
                s.ref_count = ref_lookup[key]

        classify_symbols(result.symbols, repo)
        data = extract_all(result.symbols, result.comments, result.source, rp, repo)
        anomalies = detect_all(result.symbols, result.source, data, rp, repo)
        role_counter = Counter(s.role for s in result.symbols if s.role != "unknown")
        role_counts: dict[str, int] = dict(role_counter)  # type: ignore[arg-type]

        card = OrientationCard(
            file_path=rp,
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
        cards.append(card)

    if output == "json":
        import json as j

        print(j.dumps([_card_to_dict(c) for c in cards], indent=2))
    else:
        print(render_audit_summary(cards))


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


def _card_to_dict(card: OrientationCard) -> dict:
    """Serialize an OrientationCard to a JSON-compatible dict."""
    return {
        "file": card.file_path,
        "language": card.language,
        "summary": card.summary,
        "symbols": len(card.symbols),
        "exports": card.exports,
        "imports": card.imports,
        "configs": [
            {"key": c.key, "value": c.value, "type": c.type, "line": c.line} for c in card.configs
        ],
        "roles": card.roles,
        "anomalies": [
            {"severity": a.severity, "type": a.type, "message": a.message} for a in card.anomalies
        ],
        "total_lines": card.total_lines,
    }
