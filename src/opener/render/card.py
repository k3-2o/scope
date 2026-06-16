"""
Card Renderer — formats orientation data into a compact terminal card.

Two output modes:
  - compact (default): ~20 lines, fits in agent context window
  - verbose: full detail, all symbols, all anomalies

The card always renders, even if some data is missing (graceful degradation).
"""

from __future__ import annotations

from opener.engine.ranker import compute_read_order
from opener.types import ROLE_PRIORITY, OrientationCard

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

CARD_WIDTH = 67


def render_card(card: OrientationCard, verbose: bool = False) -> str:
    """Render a full orientation card for a single file."""
    parts: list[str] = []

    parts.append(_render_header(card))
    parts.append(_render_stats(card))
    parts.append(_render_read_order(card))
    parts.append(_render_anomalies(card))
    parts.append(_render_roles(card, verbose))
    if verbose:
        parts.append(_render_symbol_list(card, verbose))

    # Join sections by double newline (blank line separator)
    raw = "\n\n".join(parts)
    # Strip trailing whitespace from each line
    lines = raw.splitlines()
    return "\n".join(line.rstrip() for line in lines)


def render_directory_summary(cards: list[OrientationCard]) -> str:
    """Render an aggregated summary for a directory."""
    if not cards:
        return "No orientation data available."

    total_symbols = sum(len(c.symbols) for c in cards)
    total_anomalies = sum(len(c.anomalies) for c in cards)
    files_with_anomalies = sum(1 for c in cards if c.anomalies)
    clean_files = sum(1 for c in cards if not c.anomalies)

    lines = [
        _b("Directory Overview"),
        f"  Files: {len(cards)}  |  Symbols: {total_symbols}  |  "
        f"Anomalies: {total_anomalies} (across {files_with_anomalies} files)",
        "",
    ]

    # Show files ranked by anomaly count (most anomalous first)
    ranked = sorted(cards, key=lambda c: -len(c.anomalies))
    lines.append(_b("Most anomalous files"))
    for c in ranked[:10]:
        n = len(c.anomalies)
        marker = f"({n})" if n > 0 else ""
        lines.append(f"  {c.file_path:45s}  {len(c.symbols):3d} symbols  {marker}")

    if clean_files > 0:
        lines.append("")
        lines.append(_b("Clean files (0 anomalies)"))
        for c in cards:
            if not c.anomalies:
                lines.append(f"  {c.file_path}")

    return "\n".join(lines)


def render_audit_summary(cards: list[OrientationCard]) -> str:
    """Render a structural health overview (audit mode)."""
    if not cards:
        return "No data to audit."

    # Aggregate anomalies by type
    anomaly_types: dict[str, int] = {}
    files_by_anomaly: dict[str, list[str]] = {}
    for c in cards:
        for a in c.anomalies:
            anomaly_types[a.type] = anomaly_types.get(a.type, 0) + 1
            if a.type not in files_by_anomaly:
                files_by_anomaly[a.type] = []
            files_by_anomaly[a.type].append(c.file_path)

    total_symbols = sum(len(c.symbols) for c in cards)
    total_anomalies = sum(len(c.anomalies) for c in cards)

    lines = [
        _b("Structural Audit"),
        f"  Files: {len(cards)}  |  Symbols: {total_symbols}  |  Anomalies: {total_anomalies}",
        "",
        _b("Issues by type"),
    ]

    sev_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    for atype, count in sorted(anomaly_types.items(), key=lambda x: -x[1]):
        lines.append(f"  {sev_map.get(atype, '⚪')} {atype:30s} {count} file(s)")
        files = files_by_anomaly.get(atype, [])
        for f in files[:5]:
            lines.append(f"    {f}")

    if total_anomalies == 0:
        lines.append("  ✅ No anomalies detected.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Render helpers — compact card
# ---------------------------------------------------------------------------


def _render_header(card: OrientationCard) -> str:
    """Render the file header section."""
    lang = card.language or "Unknown"
    summary = card.summary or "(no header comment)"
    first_line = summary.split("\n")[0]

    lines = [
        _b(f"  {card.file_path}"),
        f"  {lang}  |  {first_line}",
    ]
    return "\n".join(lines) + "\n"


def _render_stats(card: OrientationCard) -> str:
    """Render the stats summary line."""
    n_symbols = len(card.symbols)
    n_roles = len(card.roles)
    n_exports = len(card.exports)
    n_imports = sum(len(v) for v in card.imports.values())
    n_anomalies = len(card.anomalies)
    n_configs = len(card.configs)

    lines = [
        f"  Symbols: {n_symbols}  |  Roles: {n_roles}  |  "
        f"Exports: {n_exports}  |  Imports: {n_imports}  |  "
        f"Anomalies: {n_anomalies}  |  Configs: {n_configs}",
    ]
    return "\n".join(lines)


def _render_read_order(card: OrientationCard) -> str:
    """Render the READ ORDER section."""
    order = compute_read_order(card.symbols)
    if not order:
        return ""

    # Build lookup
    lookup = {s.name: s for s in card.symbols}

    lines = [_b("Read Order (start here)")]
    for i, name in enumerate(order[:7]):
        s = lookup.get(name)
        if s and s.role != "unknown":
            ref_str = f"  ← {s.ref_count} refs" if s.ref_count > 0 else ""
            lines.append(f"  {i + 1}. {name} (L{s.line})  → {s.role}{ref_str}")
        elif s:
            lines.append(f"  {i + 1}. {name} (L{s.line})")

    return "\n".join(lines)


def _render_anomalies(card: OrientationCard) -> str:
    """Render the anomalies section."""
    if not card.anomalies:
        return ""

    sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines = [_b("Anomalies")]
    for a in card.anomalies[:5]:  # max 5 in compact
        icon = sev_icon.get(a.severity, "⚪")
        locs = f" L{a.locations}" if a.locations else ""
        lines.append(f"  {icon} [{a.severity.upper()}] {a.type}{locs}")
        lines.append(f"    {a.message[:90]}")

    if len(card.anomalies) > 5:
        lines.append(f"  ... and {len(card.anomalies) - 5} more anomalies")

    return "\n".join(lines)


def _render_roles(card: OrientationCard, verbose: bool) -> str:
    """Render the role distribution."""
    if not card.roles:
        return ""

    lines = [_b("Roles")]
    for role, count in sorted(
        card.roles.items(),
        key=lambda x: (_role_priority(x[0]), -x[1]),
    ):
        lines.append(f"  {role:20s}  {count}")
    return "\n".join(lines)


def _render_symbol_list(card: OrientationCard, verbose: bool) -> str:
    """Render the full symbol list (verbose only)."""
    if not verbose:
        return ""

    if not card.symbols:
        return "(no symbols)"

    lines = [_b("All Symbols")]
    for s in sorted(card.symbols, key=lambda x: x.line):
        export = "export " if s.is_exported else ""
        role_str = f"  → {s.role} ({s.confidence})" if s.role != "unknown" else ""
        ref_str = f"  ← {s.ref_count} refs" if s.ref_count > 0 else ""
        lines.append(f"  {export}{s.kind:10s} {s.name:25s} L{s.line:4d}{role_str}{ref_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _b(text: str) -> str:
    """Bold marker for section headers (terminal-agnostic)."""
    return text


def _role_priority(role: str) -> int:
    """Get the priority for a role string (handles typing safely)."""
    return ROLE_PRIORITY.get(role, 99)  # type: ignore[call-overload,no-any-return]
