# Scope Architecture

Scope is a CLI tool that produces a compact orientation card for any source file.
It builds on Tree-sitter with 5 additional phases layered on top of symbol extraction.

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
5. RANKER — Role priority, then PageRank-overlaid importance + blast radius
   → ordered symbol list
  ↓
6. JSON — serialize the orientation card
   → structured JSON to stdout (single file) or a JSON array (directory)
```

## File Map

```
src/scope/
├── __init__.py           CLI entry (argparse, dispatch, cache wiring, JSON, --changed/--schema)
├── __main__.py           python -m scope support
├── types.py              Shared dataclasses (ClassifiedSymbol, Role, Anomaly, etc.)
├── engine/               Analytic layer
│   ├── parser.py         Tree-sitter parse via ast engine + comment collection
│   ├── classifier.py     Naming-first, structure-fallback role detection
│   ├── extractor.py      Headers, exports, categorized imports, configs
│   ├── anomaly.py        12 heuristic detectors
│   └── ranker.py         Read-order ranking by role priority + importance
└── ast/                   Low-level Tree-sitter engine (no CLI)
    ├── models.py         Symbol dataclass
    └── engine/
        ├── symbols.py    extract_symbols() — Tree-sitter AST walker
        ├── discover.py   file discovery, ignore rules, prioritization
        ├── references.py import extraction + internal-import resolution
        ├── rank.py       in-degree + PageRank + blast radius
        └── cache.py      symbol cache (save/load, git-aware signature)

tests/
├── test_classifier.py
├── test_extractor.py
├── test_anomaly.py
├── test_rank.py
├── test_cli.py            CLI/JSON regressions, cache + double-parse guards
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
- All other languages: rely on the inherited engine's `is_exported` flag

### Cross-file ref counts require directory mode

Single-file mode always shows 0 refs. Directory mode does a coordinated pass:
collect all symbols once, compute cross-file importance, then build each
file's card from the shared symbol data (no second Tree-sitter pass).

### A single engine, one parse per file

The Tree-sitter engine (the `ast` package) is parsed exactly once per file even
in directory mode: discovery + reference counting reuse the extraction that
feeds the per-file cards.

## Edge Cases Handled

| Case | Behavior |
|---|---|
| Permission denied | Returns empty ParserResult, no crash |
| Binary files | Null-byte detection in first 4KB, skips |
| Large files (>5MB) | Stat-before-read cap, skips |
| Encoding errors | Falls back to latin-1 |
| Symlinks | Resolved via os.path.realpath |
| No supported files | Exit code 2 with message |
| All parse failures | Graceful degradation, partial card |

## Comparison: Old scope vs New scope

Recently the repo consolidated: the symbol-listing CLI (modes `map|overview|pairs`)
and its dedicated helpers were removed. Only the low-level Tree-sitter extraction
it shared with this tool survived, promoted to the `ast` package. This tool is
now the single CLI with per-file orientation cards and a directory/audit view:

```
scope --path <file|dir> [--mode orient|audit] [--max-files N] [--no-cache]
```

Output is always JSON; pipe through `jq` for any human layout.

## Dependencies

- `tree-sitter` — AST parsing
- `tree-sitter-language-pack` — 25+ language grammars
- Dev: `ruff`, `mypy`, `bandit`, `pytest`, `pytest-cov`
