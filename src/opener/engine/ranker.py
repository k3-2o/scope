"""
Ranker — determines the best order to read symbols.

Sorts by:
  1. Role priority (entry_point first, unknown last)
  2. Cross-file reference count (higher = more important)
  3. Line number (earlier in file = tiebreaker within same priority)

The top 5-7 symbols are shown in the orientation card's "READ ORDER" section.
"""

from __future__ import annotations

from opener.types import ROLE_PRIORITY, ClassifiedSymbol

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_read_order(symbols: list[ClassifiedSymbol]) -> list[str]:
    """Compute the ideal reading order for symbols in a file.

    Returns a list of symbol names ranked by importance.
    """
    # Create a mutable list and sort
    ranked = list(symbols)

    ranked.sort(
        key=lambda s: (
            ROLE_PRIORITY.get(s.role, 99),  # lower = more important
            -s.ref_count,  # higher ref count = more important
            s.line,  # earlier in file = tiebreaker
        )
    )

    # Return names, filtering out unknowns that have no signal
    result: list[str] = []
    for s in ranked:
        if s.role == "unknown" and s.ref_count == 0:
            continue
        if s.role == "predicate" and s.ref_count == 0:
            continue
        result.append(s.name)

    # Limit to top 10
    return result[:10]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def read_order_with_lines(
    symbols: list[ClassifiedSymbol],
) -> list[tuple[str, int, str, int]]:
    """Return read order with line numbers and ref counts for rendering.

    Returns list of (name, line, role, ref_count).
    """
    order = compute_read_order(symbols)
    lookup = {s.name: s for s in symbols}

    result: list[tuple[str, int, str, int]] = []
    for name in order:
        s = lookup.get(name)
        if s:
            result.append((s.name, s.line, s.role, s.ref_count))

    return result
