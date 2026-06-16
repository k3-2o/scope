# Opener

**Codebase orientation radar.** Understand any file in one screen — entry points, exports, imports, configs, anomalies. No reading the whole thing required.

Works on Python, TypeScript, JavaScript, Go, Rust, Java, C++, and 25+ languages.

## Install

```bash
# 1. Clone the repo
git clone https://github.com/k3-2o/opener ~/opener
cd ~/opener

# 2. Install with uv
uv tool install .
```

Then verify:

```bash
opener --help
```

## Usage

```bash
# One file — see what it does, what's important, what's wrong
opener --path src/main.py

# A directory — per-file cards + summary
opener --path src/

# Structural audit overview — aggregated issues across all files
opener --path src/ --mode audit

# Full detail with every symbol listed
opener --path src/ --verbose

# Machine-readable output
opener --path src/ --output json
```

## What It Tells You

Every file gets a compact **orientation card**:

```
  handler.ts
  TypeScript  |  Processes HTTP requests and routes them to services

  Symbols: 24  |  Roles: 6  |  Exports: 3  |  Imports: 8  |  Anomalies: 2  |  Configs: 4

Read Order (start here)
  1. execute (L155)  → entry_point  ← 3 refs
  2. validateRequest (L42)  → accessor
  3. formatResponse (L89)  → normalizer

Anomalies
  🟡 [MEDIUM] high_nesting L[120]
    Maximum nesting depth of 8 at line 120
  🟢 [LOW] hardcoded_value L[30]
    Hardcoded URL 'https://api.example.com'

Roles
  entry_point    1
  normalizer     2
  accessor       3
```

### Sections

| Section | What it tells you |
|---|---|
| **Header** | Language, one-line summary from the file's own docstring/comment |
| **Stats** | How many symbols, roles, exports, imports, anomalies, configs |
| **Read Order** | Which symbols to examine first, ranked by role priority + cross-file references |
| **Anomalies** | Structural issues: hardcoded URLs, deep nesting, silent error handling, etc. |
| **Roles** | What each symbol does: entry_point, normalizer, http_caller, accessor, etc. |

### 12 Anomaly Detectors

| Anomaly | Severity | What it catches |
|---|---|---|
| Asymmetry | 🔴 High | One role has 1 member while others have many |
| Silent error | 🔴 High | Empty or trivial catch blocks |
| Dual mode handler | 🟡 Medium | Variable accessed via optional chaining at different depths (v1/v2 fallback) |
| High nesting | 🟡 Medium | Control flow >7 levels deep |
| Timing mismatch | 🟡 Medium | Divergent timeout/interval values |
| Inconsistent error handling | 🟡 Medium | Mixed try/catch within same role |
| Unused export | 🟡 Medium | Exported but never imported elsewhere |
| Weak naming | 🟢 Low | ≤2 char names, generic terms like `data`, `tmp` |
| Hardcoded value | 🟢 Low | Inline URLs, unconfigurable magic numbers |
| Missing header | 🟢 Low | No descriptive file comment |
| Config interleaving | 🟢 Low | Related configs scattered across file |
| Name/value mismatch | 🟢 Low | `TIMEOUT_MS = 60000` (name says ms, value looks like seconds) |

## Language Support

Parsing: 25+ languages via Tree-sitter (scope engine).

Role classification works across all languages — naming prefixes are matched case-insensitively with Python `_` stripped:
- `normalize*`, `parse*`, `transform*`, `render*` → normalizer
- `get*`, `fetch*`, `load*`, `read*`, `search*` → accessor
- `set*`, `save*`, `create*`, `delete*` → mutator
- `is*`, `has*`, `can*`, `contains*` → predicate
- `execute`, `main`, `handler`, `serve`, `new` → entry_point
- `UPPER_SNAKE_CASE` → config_value

Export detection is language-specific:
- **Python**: module-level `def` and `class`
- **TypeScript**: `export default`, `export function`, `export class`
- **Go**: capitalized function/type names
- **Rust**: `pub` items (planned)

## Development

```bash
# Setup
uv sync --all-extras

# Quality
make lint           # ruff check
make fmt            # ruff format check
make typecheck      # mypy
make check          # all three

# Tests
make test           # 32 pytest tests

# Install locally
uv tool install .   # makes `opener` available globally
```

## Architecture

Opener is built on **scope** (its Tree-sitter AST engine) with five additional layers:

```
discover → parse → classify → extract → detect → rank → render
```

| Phase | File | What it does | Lines |
|---|---|---|---|
| Parse | `engine/parser.py` | Tree-sitter AST walk + comment collection | 214 |
| Classify | `engine/classifier.py` | Naming-first, structure-fallback role detection | 334 |
| Extract | `engine/extractor.py` | File headers, exports, imports, config values | 442 |
| Detect | `engine/anomaly.py` | 12 heuristic anomaly detectors | 708 |
| Rank | `engine/ranker.py` | Read order by role priority + ref counts | 71 |
| Render | `render/card.py` | Compact and verbose orientation card | 233 |
| CLI | `__init__.py` | argparse, file/dir/audit dispatch, JSON output | 247 |

## Philosophy

**Scope maps structure. Opener maps meaning.**

Tree-sitter gives you AST nodes (functions, classes, types). But an agent doesn't need to know there are 18 functions. It needs to know:

- 8 of those are data normalizers (same role, different providers)
- 2 are HTTP callers (one sync, one async)  
- 1 is the entry point
- 9 are provider config objects (the file's actual logic)
- The catch block in execute silences errors — don't touch unless you fix that

This is the difference between a listing and a filter.

## License

MIT
