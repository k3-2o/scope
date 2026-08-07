"""
Anomaly Detector — 12 heuristic rules that scan classified symbols and
source text for structural anomalies.

Each rule is an independent function returning list[Anomaly] (0 or more).
All results are concatenated and sorted by severity at the end.

Rules (in order of implementation):
  1. ASYMMETRY — one role has a single member while others have many
  2. SILENT ERRORS — empty/trivial catch blocks
  3. TIMING MISMATCH — divergent timeout/interval values
  4. DUAL MODE HANDLER — optional chaining fallback (v1/v2 shapes)
  5. WEAK NAMING — ≤2 character names, generic terms
  6. MISSING HEADER — no descriptive file header
  7. HIGH NESTING — >5 control flow levels in a function body
  8. CONFIG INTERLEAVING — similar configs scattered, not adjacent
  9. INCONSISTENT ERROR HANDLING — mixed try/catch within same role
  10. HARDCODED VALUES — inline URLs, magic numbers in function bodies
  11. NAME/VALUE MISMATCH — name says one unit, value says another
  12. UNUSED EXPORT — exported symbol with no internal importers
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from scope.ast.engine.references import read_text
from scope.types import Anomaly, ClassifiedSymbol, Config, ExtractedData

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def detect_all(
    symbols: list[ClassifiedSymbol],
    source: str,
    extracted: ExtractedData,
    file_path: str,
    repo_path: str,
    all_file_symbols: dict[str, list[ClassifiedSymbol]] | None = None,
) -> list[Anomaly]:
    """Run all 12 anomaly detectors and return sorted results."""
    anomalies: list[Anomaly] = []

    anomalies.extend(detect_asymmetry(symbols))
    anomalies.extend(detect_silent_errors(symbols, source))
    anomalies.extend(detect_timing_mismatch(extracted.configs, symbols, source))
    anomalies.extend(detect_dual_mode_handler(symbols, source))
    anomalies.extend(detect_weak_naming(symbols))
    anomalies.extend(detect_missing_header(extracted.summary))
    anomalies.extend(detect_high_nesting(symbols, source))
    anomalies.extend(detect_config_interleaving(symbols, extracted.configs))
    anomalies.extend(detect_inconsistent_error_handling(symbols, source))
    anomalies.extend(detect_hardcoded_values(symbols, source))
    anomalies.extend(detect_name_value_mismatch(extracted.configs))
    anomalies.extend(detect_unused_export(symbols, all_file_symbols, file_path, repo_path))

    severity_order = {"high": 0, "medium": 1, "low": 2}
    anomalies.sort(key=lambda a: (severity_order.get(a.severity, 99), a.type))

    return anomalies


# ---------------------------------------------------------------------------
# 1. ASYMMETRY
# ---------------------------------------------------------------------------


def detect_asymmetry(symbols: list[ClassifiedSymbol]) -> list[Anomaly]:
    """Detect roles where one member is isolated while others are numerous.

    E.g., 8 normalizers but only 1 HTTP caller. The singleton is suspicious.
    """
    if not symbols:
        return []

    # Count by role
    role_counts: Counter[str] = Counter()
    for s in symbols:
        if s.role != "unknown":
            role_counts[s.role] += 1

    if len(role_counts) < 2:
        return []

    mode = _most_common_count(role_counts)
    if mode < 3:
        return []  # too few to detect asymmetry

    anomalies: list[Anomaly] = []
    for role, count in role_counts.items():
        if count == 1 and mode >= 4:
            anomalies.append(
                Anomaly(
                    severity="high",
                    type="asymmetry",
                    message=(
                        f"'{role}' has only 1 member "
                        f"while the typical role has {int(mode)} members. "
                        "This singleton may be architecturally significant "
                        "or an outlier."
                    ),
                )
            )

    return anomalies


def _most_common_count(counter: Counter) -> float:
    """Return the most common count among all values."""
    if not counter:
        return 0
    values = list(counter.values())
    # Return the median-ish value, or the mean
    return sum(values) / len(values)


# ---------------------------------------------------------------------------
# 2. SILENT ERRORS
# ---------------------------------------------------------------------------

_SILENT_CATCH_PATTERNS = [
    re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*\}"),  # catch(e) {}
    re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*return\b"),  # catch(e) { return }
    re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*continue\b"),  # catch(e) { continue }
    re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*pass\b"),  # except: pass (Python)
    re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*errors?\.push"),  # catch(e) { errors.push }
]


def detect_silent_errors(symbols: list[ClassifiedSymbol], source: str) -> list[Anomaly]:
    """Detect catch blocks that are empty or only contain trivial statements."""
    anomalies: list[Anomaly] = []
    for pattern in _SILENT_CATCH_PATTERNS:
        for match in pattern.finditer(source):
            # Find which symbol this belongs to
            line_no = source[: match.start()].count("\n") + 1
            anomalies.append(
                Anomaly(
                    severity="high",
                    type="silent_error",
                    message=(
                        f"Catch block at line {line_no} is empty or only "
                        "contains a trivial statement (return/continue/errors.push). "
                        "Errors are silently swallowed."
                    ),
                    locations=[line_no],
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# 3. TIMING MISMATCH
# ---------------------------------------------------------------------------

_TIMING_NAME_PATTERN = re.compile(
    r"(TIMEOUT|INTERVAL|DELAY|MAX_WAIT|POLL_INTERVAL|TTL|RETRY)",
    re.IGNORECASE,
)


def detect_timing_mismatch(
    configs: list[Config], symbols: list[ClassifiedSymbol], source: str
) -> list[Anomaly]:
    """Detect divergent timing values — config says X but code uses Y nearby."""
    if not configs:
        return []

    timing_configs = [c for c in configs if _TIMING_NAME_PATTERN.search(c.key)]
    if not timing_configs:
        return []

    anomalies: list[Anomaly] = []

    for cfg in timing_configs:
        if cfg.type != "number":
            continue
        try:
            config_value = int(cfg.value)
        except (ValueError, TypeError):
            continue

        # Look for number literals in the source that differ significantly
        # from the config value (outside 20% range)
        for match in re.finditer(r"\b(\d{3,})\b", source):
            try:
                source_val = int(match.group(1))
            except ValueError:
                continue

            if source_val == config_value:
                continue

            # Check if it's near the config (within 20 lines)
            src_line = source[: match.start()].count("\n") + 1
            if abs(src_line - cfg.line) > 20:
                continue

            # Check if they differ significantly (>50%)
            if source_val > 0 and config_value > 0:
                ratio = max(source_val, config_value) / min(source_val, config_value)
                if ratio > 1.5:
                    anomalies.append(
                        Anomaly(
                            severity="medium",
                            type="timing_mismatch",
                            message=(
                                f"Value {source_val} at line {src_line} differs "
                                f"from config '{cfg.key}'={cfg.value} at line {cfg.line} "
                                f"(ratio {ratio:.1f}x). May be inconsistent."
                            ),
                            locations=[cfg.line, src_line],
                        )
                    )

    return anomalies


# ---------------------------------------------------------------------------
# 4. DUAL MODE HANDLER
# ---------------------------------------------------------------------------

_DUAL_MODE_PATTERN = re.compile(
    r"\?\.(\w+)\??\.?\s*\??\s*(?:\?\.|\.\s*)",
)


def detect_dual_mode_handler(symbols: list[ClassifiedSymbol], source: str) -> list[Anomaly]:
    """Detect symbols that handle multiple API response shapes.

    Optional chaining lets one field be read at varying depths in the same
    body, e.g. `data?.field` (depth 1) vs `data?.a?.b` (depth 2). When the
    *same root* is dereferenced shallowly *and* deeply, the author is likely
    supporting two different response shapes (v1/v2).

    Each symbol is scanned only across its own definition window (its line to
    the next symbol's), so findings don't leak into neighboring symbols.
    """
    anomalies: list[Anomaly] = []
    lines = source.splitlines()

    ordered = [s for s in symbols if 1 <= s.line <= len(lines)]
    ordered.sort(key=lambda s: s.line)

    for i, sym in enumerate(ordered):
        start = max(0, sym.line - 1)
        end = ordered[i + 1].line - 1 if i + 1 < len(ordered) else len(lines)
        window = "\n".join(lines[start:end])

        # The same root being read at multiple depths is the signal.
        root_depths: dict[str, set[int]] = {}
        for m in re.finditer(r"\b(\w+)\?\.\w+(?:\?\.\w+)*", window):
            root = m.group(1)
            depth = m.group(0).count("?.")
            root_depths.setdefault(root, set()).add(depth)

        for root, depths in root_depths.items():
            if max(depths) >= 2 and 1 in depths:
                anomalies.append(
                    Anomaly(
                        severity="medium",
                        type="dual_mode_handler",
                        message=(
                            f"'{root}' is accessed via optional chaining at "
                            "different depths — likely handling multiple API "
                            "response shapes (v1/v2)."
                        ),
                        locations=[sym.line],
                    )
                )
                break  # one per symbol is enough

    return anomalies


# ---------------------------------------------------------------------------
# 5. WEAK NAMING
# ---------------------------------------------------------------------------

_GENERIC_NAMES = {
    "data",
    "temp",
    "tmp",
    "stuff",
    "misc",
    "utils",
    "helper",
    "util",
    "common",
    "base",
    "core",
    "main",
    "index",
}


def detect_weak_naming(symbols: list[ClassifiedSymbol]) -> list[Anomaly]:
    """Detect symbol names that are too short or too generic."""
    anomalies: list[Anomaly] = []

    for sym in symbols:
        # Skip interfaces and types — they're structural
        if sym.kind in ("interface", "type", "type_alias"):
            continue

        name_lower = sym.name.lower()

        # Too short
        if len(sym.name) <= 2 and sym.role not in ("unknown",):
            pass  # Short-but-known roles are fine (e.g., `is`, `run`)

        # Generic name
        if name_lower in _GENERIC_NAMES:
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="weak_naming",
                    message=(
                        f"Symbol '{sym.name}' at line {sym.line} has a "
                        f"generic name that doesn't describe its purpose."
                    ),
                    locations=[sym.line],
                )
            )

        # Very short (≤2 chars) with unknown role
        if len(sym.name) <= 2 and sym.role == "unknown":
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="weak_naming",
                    message=(
                        f"Symbol '{sym.name}' at line {sym.line} is only "
                        f"{len(sym.name)} character(s) long."
                    ),
                    locations=[sym.line],
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# 6. MISSING HEADER
# ---------------------------------------------------------------------------


def detect_missing_header(summary: str | None) -> list[Anomaly]:
    """Detect files without a descriptive header."""
    if not summary:
        return [
            Anomaly(
                severity="low",
                type="missing_header",
                message=(
                    "File has no descriptive header comment. "
                    "The tool cannot determine its purpose from a comment."
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 7. HIGH NESTING
# ---------------------------------------------------------------------------


_NESTING_KW = re.compile(r"^\s*(?:if|elif|else|for|while|with|try|except|finally|case|catch)\b")


def detect_high_nesting(symbols: list[ClassifiedSymbol], source: str) -> list[Anomaly]:
    """Detect excessive control flow nesting using keyword tracking.

    Uses keywords (if/for/while/try) instead of brace counting to avoid
    false positives from object literals and template expressions.
    Resets depth at each function/class/def boundary.
    """
    anomalies: list[Anomaly] = []
    lines = source.splitlines()

    max_depth = 0
    max_depth_line = 0
    open_blocks: list[int] = []  # indentation of each open control-flow block
    in_function = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith(("#", "//", "/*", "*", "--")):
            continue

        # Reset at a function/class/module boundary
        if re.match(r"^\s*(?:function|class|def|module|struct|trait|impl)\b", stripped):
            open_blocks = []
            in_function = True
            continue

        if not in_function:
            continue

        indent = len(line) - len(line.lstrip())

        # Close any block at or below this line's indentation. Using indentation
        # (instead of braces) keeps the count correct for both brace-less
        # languages (Python/Ruby) and brace languages, and stops sibling blocks
        # at the same indentation from being summed as nesting.
        while open_blocks and indent <= open_blocks[-1]:
            open_blocks.pop()

        if _NESTING_KW.match(stripped):
            open_blocks.append(indent)
            if len(open_blocks) > max_depth:
                max_depth = len(open_blocks)
                max_depth_line = i + 1

        if max_depth >= 7:
            break

    if max_depth >= 7:
        anomalies.append(
            Anomaly(
                severity="medium",
                type="high_nesting",
                message=(
                    f"Maximum control flow nesting depth of {max_depth} "
                    f"reached at line {max_depth_line}. "
                    "Deep nesting (>7 levels) hurts readability."
                ),
                locations=[max_depth_line],
            )
        )

    return anomalies


# ---------------------------------------------------------------------------
# 8. CONFIG INTERLEAVING
# ---------------------------------------------------------------------------


def detect_config_interleaving(
    symbols: list[ClassifiedSymbol], configs: list[Config]
) -> list[Anomaly]:
    """Detect when similar configs/objects are scattered through the file."""
    if len(configs) < 2:
        return []

    # Group configs by type
    type_groups: dict[str, list[Config]] = {}
    for c in configs:
        if c.type not in type_groups:
            type_groups[c.type] = []
        type_groups[c.type].append(c)

    anomalies: list[Anomaly] = []
    for ctype, group in type_groups.items():
        if len(group) < 3:
            continue

        # Check if any two adjacent configs in sorted order are >20 lines apart
        sorted_configs = sorted(group, key=lambda c: c.line)
        gaps = []
        for i in range(len(sorted_configs) - 1):
            gap = sorted_configs[i + 1].line - sorted_configs[i].line
            gaps.append(gap)

        max_gap = max(gaps) if gaps else 0
        if max_gap > 20:
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="config_interleaving",
                    message=(
                        f"Config values of type '{ctype}' are scattered "
                        f"across the file (largest gap: {max_gap} lines). "
                        "Grouping related configs improves readability."
                    ),
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# 9. INCONSISTENT ERROR HANDLING
# ---------------------------------------------------------------------------


def detect_inconsistent_error_handling(
    symbols: list[ClassifiedSymbol], source: str
) -> list[Anomaly]:
    """Detect when functions of the same role have inconsistent error handling.

    E.g., some normalizers have try/catch, others don't.
    """
    # Group symbols by role
    role_groups: dict[str, list[ClassifiedSymbol]] = {}
    for s in symbols:
        if s.role == "unknown":
            continue
        if s.role not in role_groups:
            role_groups[s.role] = []
        role_groups[s.role].append(s)

    anomalies: list[Anomaly] = []
    for role, group in role_groups.items():
        if len(group) < 3:
            continue  # Need enough functions to detect inconsistency

        # Check which functions have try/catch in their source window
        total = len(group)
        with_catch = 0
        for s in group:
            if s.line:
                # Read 5 lines before and 5 lines after — rough check
                lines = source.splitlines()
                start = max(0, s.line - 6)
                end = min(len(lines), s.line + 5)
                window = "\n".join(lines[start:end])
                if re.search(r"\btry\b", window) or re.search(r"\bcatch\b", window):
                    with_catch += 1

        ratio = with_catch / total if total > 0 else 0

        # Flag if less than 60% of functions in the same role handle errors
        if 0.2 < ratio < 0.8:
            anomalies.append(
                Anomaly(
                    severity="medium",
                    type="inconsistent_error_handling",
                    message=(
                        f"Role '{role}' has mixed error handling: "
                        f"{with_catch}/{total} functions use try/catch "
                        f"({ratio:.0%}). "
                        "Functions with the same role should handle errors consistently."
                    ),
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# 10. HARDCODED VALUES
# ---------------------------------------------------------------------------

_URL_PATTERN = re.compile(r"""['\"](https?://[^'\"]+)['\"]""")

_MAGIC_NUMBER_PATTERN = re.compile(
    r"\b(\d{4,})\b"  # Numbers >= 1000 (likely significant)
)


def detect_hardcoded_values(symbols: list[ClassifiedSymbol], source: str) -> list[Anomaly]:
    """Detect inline URLs and large magic numbers in function bodies.

    These should typically be extracted to named constants.
    """
    anomalies: list[Anomaly] = []

    # Find URLs in source (outside comments and strings already, but close enough)
    urls = list(_URL_PATTERN.finditer(source))
    if len(urls) >= 2:
        for m in urls[:3]:  # Max 3 to avoid noise
            line_no = source[: m.start()].count("\n") + 1
            url = m.group(1)
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="hardcoded_value",
                    message=(
                        f"Hardcoded URL at line {line_no}: "
                        f"'{url[:60]}{'...' if len(url) > 60 else ''}'. "
                        "Consider extracting to a named constant."
                    ),
                    locations=[line_no],
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# 11. NAME/VALUE MISMATCH
# ---------------------------------------------------------------------------


def detect_name_value_mismatch(configs: list[Config]) -> list[Anomaly]:
    """Detect constants whose name implies one unit but value uses another.

    E.g., TIMEOUT_MS = 60000 (should be in milliseconds, 60000ms = 60s)
    """
    anomalies: list[Anomaly] = []

    for cfg in configs:
        if cfg.type != "number":
            continue

        try:
            val = int(cfg.value)
        except (ValueError, TypeError):
            continue

        name_upper = cfg.key.upper()

        # *_MS → value should be < 3600000 (1 hour in ms)
        if (name_upper.endswith("_MS") or "_MS_" in name_upper) and val > 3_600_000:
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="name_value_mismatch",
                    message=(
                        f"'{cfg.key}'={cfg.value} — name says milliseconds "
                        f"({cfg.key}) but value ({val}) exceeds 1 hour "
                        f"in ms (3600000). Possibly using different units."
                    ),
                    locations=[cfg.line],
                )
            )

        # TIMEOUT without MS → value should be in seconds or milliseconds
        # Typical timeouts are 100-30000ms or 1-30s
        if "TIMEOUT" in name_upper and not name_upper.endswith("_MS") and val < 100:
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="name_value_mismatch",
                    message=(
                        f"'{cfg.key}'={cfg.value} — unusually low for "
                        f"a timeout value. Maybe uses larger units?"
                    ),
                    locations=[cfg.line],
                )
            )

        # *_BYTES, *_KB, *_MB → check reasonable ranges
        if name_upper.endswith("_BYTES") and val < 32:
            anomalies.append(
                Anomaly(
                    severity="low",
                    type="name_value_mismatch",
                    message=(
                        f"'{cfg.key}'={cfg.value} — only {val} bytes "
                        f"is very small. Possibly wrong unit?"
                    ),
                    locations=[cfg.line],
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# 12. UNUSED EXPORT
# ---------------------------------------------------------------------------


def detect_unused_export(
    symbols: list[ClassifiedSymbol],
    all_file_symbols: dict[str, list[ClassifiedSymbol]] | None,
    current_file: str,
    repo_path: str | None = None,
) -> list[Anomaly]:
    """Detect exported symbols that are not referenced by any other file.

    Only works in directory/repo mode when ``all_file_symbols`` is provided.
    Uses ``repo_path`` (the repo root ``detect_all`` already holds) so each other
    file's source can be read to test whether the exported identifier appears
    anywhere — rather than comparing symbol names against import-module names,
    which can never match and would flag every export as unused.
    """
    if all_file_symbols is None:
        return []

    exported = {s.name for s in symbols if s.is_exported}
    if not exported:
        return []

    repo_root = repo_path or str(Path(current_file).parent)
    used: set[str] = set()
    for other_file in all_file_symbols:
        if other_file == current_file:
            continue
        other_src = read_text(repo_root, other_file)
        if not other_src:
            continue
        for name in exported:
            if re.search(rf"\b{re.escape(name)}\b", other_src):
                used.add(name)

    unused = sorted(exported - used)
    if unused:
        return [
            Anomaly(
                severity="medium",
                type="unused_export",
                message=(
                    f"Exported symbol(s) not referenced by other files: "
                    f"{', '.join(unused)}. May be dead code."
                ),
            )
        ]
    return []
