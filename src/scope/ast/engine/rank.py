from __future__ import annotations

import os
import re
from collections import defaultdict

from scope.ast.engine.references import extract_imports, resolve_internal_import
from scope.ast.models import Symbol

_IDENTIFIER_RE = re.compile(r"[a-zA-Z_]\w+")

# Blend weights for the graph overlay.
_RANK_K = 1.5  # how much file-level PageRank amplifies a symbol's score
_BLAST_W = 0.15  # how much blast radius adds to a symbol's score


def build_symbol_index(all_symbols: dict[str, list[Symbol]]) -> dict[str, list[Symbol]]:
    """Build a token → symbols lookup for fast reference scanning."""
    index: dict[str, list[Symbol]] = defaultdict(list)
    for symbols in all_symbols.values():
        for sym in symbols:
            for token in _reference_tokens(sym.name):
                index[token].append(sym)
    return dict(index)


def _reference_tokens(name: str) -> set[str]:
    base = name.rsplit(".", 1)[-1]
    tokens = {base}
    if "." not in name:
        tokens.add(name)
    return {token for token in tokens if _IDENTIFIER_RE.fullmatch(token)}


def compute_importance(
    all_symbols: dict[str, list[Symbol]],
    repo_path: str,
    file_inrefs: dict[str, int] | None = None,
) -> None:
    """Rank symbols by cross-file reference count, then overlay graph signals.

    Stage 1 computes per-symbol in-degree (how many other files reference each
    symbol by name). Stage 2 overlays a file-level PageRank over the import
    graph and a blast radius (transitive dependents), so symbols in central
    files and symbols with wide blast radius outrank equal-count peers.

    Sets ``Symbol.ref_count`` (raw in-degree), ``Symbol.importance`` (combined
    salience) and ``Symbol.blast_radius`` on every symbol, in place.
    """
    index = build_symbol_index(all_symbols)
    token_set = frozenset(index.keys())

    # --- Stage 1: in-degree reference counts ---
    ref_count: dict[tuple[str, str], int] = defaultdict(int)

    if token_set:
        for file_path, _symbols in all_symbols.items():
            full_path = os.path.join(repo_path, file_path)
            try:
                with open(full_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue

            words_in_file: set[str] = set()
            for word in _IDENTIFIER_RE.finditer(content):
                token = word.group(0)
                if token in token_set and token not in words_in_file:
                    words_in_file.add(token)
                    for sym in index[token]:
                        if sym.file != file_path:
                            ref_count[(sym.file, sym.name)] += 1

    for file_path, symbols in all_symbols.items():
        is_test = _is_test_file(file_path)

        for sym in symbols:
            raw = int(ref_count.get((sym.file, sym.name), 0))
            sym.ref_count = raw
            score = float(raw)

            # Boost important symbol kinds
            if sym.kind in ("class", "interface"):
                score *= 1.5
            elif sym.kind in ("resource", "module", "data"):
                score *= 2.0
            elif sym.kind == "key":
                score = -1.0

            # Boost well-known entry point names
            base_name = sym.name.rsplit(".", 1)[-1]
            if base_name in (
                "main",
                "index",
                "App",
                "Server",
                "setup",
                "configure",
                "create_app",
                "handler",
            ):
                score += 5.0

            # Boost files with high incoming import counts
            if file_inrefs:
                score += min(file_inrefs.get(file_path, 0), 25) * 0.35

            # Penalize test files
            if is_test or base_name.startswith("test_") or base_name.startswith("it("):
                score *= 0.05

            sym.importance = score

    # --- Stage 2: PageRank centrality + blast radius over the import graph ---
    page_rank, blast_radius = _graph_signals(all_symbols, repo_path)
    pr_max = max(page_rank.values(), default=0.0)

    for file_path, symbols in all_symbols.items():
        norm = (page_rank.get(file_path, 0.0) / pr_max) if pr_max else 0.0
        br = blast_radius.get(file_path, 0)
        for sym in symbols:
            sym.blast_radius = br
            sym.importance = sym.importance * (1.0 + _RANK_K * norm) + _BLAST_W * float(br)


def _graph_signals(
    all_symbols: dict[str, list[Symbol]], repo_path: str
) -> tuple[dict[str, float], dict[str, int]]:
    """Compute PageRank and blast radius from the internal import graph.

    Returns (page_rank, blast_radius) keyed by relative file path. PageRank is
    run over the file graph where an edge ``a -> b`` means ``a`` imports ``b``.
    Blast radius is the number of other files transitively importing a file
    (i.e. how many would be affected by a change there).
    """
    files = list(all_symbols.keys())
    file_set = set(files)

    imports: dict[str, list[str]] = defaultdict(list)  # file -> files it imports
    importers_of: dict[str, set[str]] = defaultdict(set)  # file -> files importing it
    for rel in files:
        for imp in extract_imports(repo_path, rel):
            target = resolve_internal_import(imp, rel, files)
            if target and target in file_set and target != rel:
                if target not in imports[rel]:
                    imports[rel].append(target)
                importers_of[target].add(rel)

    page_rank = _page_rank(files, imports, iterations=40)
    blast_radius = {f: len(_transitive_importers(f, importers_of, file_set)) for f in files}
    return page_rank, blast_radius


def _page_rank(
    nodes: list[str], imports: dict[str, list[str]], iterations: int = 60, damping: float = 0.85
) -> dict[str, float]:
    """Standard PageRank over ``imports`` (file -> files that file imports)."""
    n = len(nodes)
    if n == 0:
        return {}
    index = {node: i for i, node in enumerate(nodes)}
    out_edges: list[set[int]] = [set() for _ in nodes]
    for node, targets in imports.items():
        i = index[node]
        for t in targets:
            if t in index:
                out_edges[i].add(index[t])

    out_count = [len(e) for e in out_edges]
    rank = [1.0 / n] * n
    base = (1.0 - damping) / n

    for _ in range(iterations):
        new = [base] * n
        dangling_mass = 0.0
        for i in range(n):
            if out_count[i] == 0:
                # Dangling node: redistribute its mass evenly.
                dangling_mass += damping * rank[i]
            else:
                share = damping * rank[i] / out_count[i]
                for j in out_edges[i]:
                    new[j] += share
        if dangling_mass:
            leftover = dangling_mass / n
            for j in range(n):
                new[j] += leftover
        rank = new

    return {node: rank[idx] for node, idx in index.items()}


def _transitive_importers(
    file: str, importers_of: dict[str, set[str]], node_set: set[str]
) -> set[str]:
    """All files (excluding ``file``) that depend on ``file`` transitively."""
    seen: set[str] = set()
    stack = list(importers_of.get(file, ()))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in node_set:
            continue
        if cur != file:
            seen.add(cur)
        stack.extend(importers_of.get(cur, ()))
    return seen


def _is_test_file(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/")
    base = os.path.basename(p)
    TEST_MARKERS = ("/test/", "/tests/", "/__tests__/", ".test.", ".spec.")
    return (
        any(marker in f"/{p}" for marker in TEST_MARKERS)
        or base.startswith("test_")
        or base.endswith("_test.py")
        or base.endswith("_test.go")
    )


def suggested_reads(
    all_symbols: dict[str, list[Symbol]], files: list[str], limit: int = 5
) -> list[str]:
    """Rank files by total accumulated symbol importance."""
    scored: list[tuple[float, str]] = []
    for file_path, symbols in all_symbols.items():
        total = sum(sym.importance for sym in symbols)
        scored.append((total, file_path))
    if not scored:
        return files[:limit]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [file_path for _score, file_path in scored[:limit]]
