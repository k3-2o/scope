from __future__ import annotations

from opener.scope.models import Symbol


def render(all_symbols: dict[str, list[Symbol]], token_budget: int) -> str:
    """Ranked symbol map — the one thing bash cannot do.

    Returns functions, classes, methods sorted by cross-file reference importance,
    grouped by file (highest-importance file first).
    """
    if not all_symbols:
        return "# No symbols found"

    char_budget = token_budget * 4
    current = 0
    lines: list[str] = []

    # Rank files by total symbol importance
    file_scores: list[tuple[str, float, list[Symbol]]] = []
    for file_path, symbols in all_symbols.items():
        if not symbols:
            continue
        total = sum(s.importance for s in symbols)
        file_scores.append((file_path, total, symbols))

    file_scores.sort(key=lambda x: (-x[1], x[0]))

    for file_path, _score, symbols in file_scores:
        symbols.sort(key=lambda s: (-s.importance, s.line))

        header = f"- {file_path}:"
        if current + len(header) > char_budget:
            break
        lines.append(header)
        current += len(header) + 1

        seen: set[tuple[str, str]] = set()
        for sym in symbols[:30]:
            key = (sym.kind, sym.name)
            if key in seen:
                continue
            seen.add(key)

            entry = f"  {sym.kind} {sym.name} (line {sym.line})"
            if sym.ref_count > 0:
                entry += f"  ← {sym.ref_count} files"

            if current + len(entry) > char_budget:
                break
            lines.append(entry)
            current += len(entry) + 1

        if current >= char_budget:
            break

    return "\n".join(lines)


def render_suggestions(reads: list[str]) -> str:
    if not reads:
        return ""
    lines = ["\n## Suggested next reads"]
    lines.extend(f"{i + 1}. {path}" for i, path in enumerate(reads))
    return "\n".join(lines)
