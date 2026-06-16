# Opener Architecture

Opener is a CLI tool that produces a compact orientation card for any source file.
It builds on **scope** (Tree-sitter AST engine) with 5 additional phases.

## Pipeline

```
file path
  ↓
1. PARSER — Tree-sitter AST walk + comment collection
   → raw Symbol[] + Comment[] + source text
  ↓
2. CLASSIFIER — Name-first, structure-fallback role detection
   → ClassifiedSymbol[] with roles (entry_point, normalizer, http_caller, etc.)
  ↓
3. EXTRACTOR — File headers, exports, imports, config values
   → ExtractedData (summary string, exports[], imports{}, configs[])
  ↓
4. ANOMALY DETECTOR — 12 heuristic rules
   → Anomaly[] sorted by severity (high → medium → low)
  ↓
5. RANKER — Read order by role priority + cross-file ref counts
   → ordered symbol list
  ↓
6. RENDERER — Compact or verbose orientation card
   → ~20 line card printed to stdout
```

## File Map

```
src/scope/
├── __init__.py           CLI entry (argparse, dispatch, exit codes)
├── __main__.py           python -m scope support
├── types.py              Shared dataclasses (ClassifiedSymbol, Role, Anomaly, etc.)
├── engine/
│   ├── parser.py         Tree-sitter AST via scope + comment collection
│   ├── classifier.py     Naming-first, structure-fallback role detection
│   ├── extractor.py      File headers, exports (TS/Python/Go), imports, configs
│   ├── anomaly.py        12 heuristic detectors
│   └── ranker.py         Read order by role priority + ref count
├── render/
│   └── card.py           Compact and verbose orientation card formatter
└── scope/                Inherited from scope project (Tree-sitter AST engine)
    ├── engine/
    │   ├── symbols.py    extract_symbols() — core AST walker
    │   ├── discover.py   discover_files(), language detection
    │   ├── references.py dependency graph, import extraction
    │   └── rank.py       compute_importance() — cross-file ref counting
    └── models.py         Symbol dataclass

tests/
├── test_classifier.py    11 tests
├── test_extractor.py     11 tests
└── test_anomaly.py       10 tests
```

## Key Decisions

### Classification: naming-first, structure-second

Naming patterns are checked BEFORE structural patterns. This avoids false
positives from source-window scanning bleeding into adjacent code. Names
are normalized: Python `_prefix` stripped, case-insensitive matching.

### Roles are generic, not language-specific

The same 12 roles cover Python, TypeScript, Go, Rust, and others. Per-language
differences are handled by naming normalization (stripping `_`, lowercasing,
matching `new` as constructor).

### Anomaly detection is heuristic, not precise

Each rule is a 15-30 line function that scans source text for patterns.
False positives are expected and marked with appropriate severity (high/med/low).
The card always renders, even if no anomalies are found.

### Export detection is language-aware

- **TypeScript**: `export default`, `export function`, `export class`
- **Python**: module-level `def` and `class` at indent 0
- **Go**: capitalized function/type names (`func GetName`)
- All other languages: rely on scope's `is_exported` flag

### Cross-file ref counts require directory mode

Single-file mode always shows 0 refs. Directory mode does a two-phase pass:
first collect all symbols, compute cross-file importance, then apply ref counts
to each file's symbols before classification/rendering.

## Edge Cases Handled

| Case | Behavior |
|---|---|
| Permission denied | Returns empty ParserResult, no crash |
| Binary files | Null-byte detection in first 4KB, skips |
| Large files (>5MB) | Stat-before-read cap, skips |
| Encoding errors | Falls back to latin-1 |
| Symlinks | Resolved via os.path.realpath |
| No supported files | Exit code 2 with message |
| All parse failures Graceful degradation, partial card |

## vs scope

| Dimension | scope | scope |
|---|---|---|
| Output | Symbol list + importance scores | Orientation card (summary, roles, anomalies, read order) |
| Symbols | Functions, classes, types only | Same + consts, comments, literals |
| Classification | None (raw symbols only) | 12 roles via naming + structural matching |
| Anomalies | None | 12 heuristic detectors |
| Multi-language | 25+ languages (Tree-sitter) | Same engine, plus per-language exports |
| CLI | `--path --mode map\|overview\|pairs` | `--path --mode orient|health --verbose` |
| Install | `uv tool install .` | `uv tool install .` (same) |

## Dependencies

- `tree-sitter` — AST parsing
- `tree-sitter-language-pack` — 25+ language grammars
- Dev: `ruff`, `mypy`, `bandit`, `pytest`, `pytest-cov`
