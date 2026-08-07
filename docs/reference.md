# Reference — CLI Flags and the JSON Contract

Reference documentation for `scope`. For a guided first run, see [Tutorial](tutorials.md); for workflows, see [How-to](how-to.md).

## CLI

```
scope [--path PATH] [--mode orient|audit] [--max-files N]
      [--no-cache] [--changed [REF]] [--schema]
```

| Flag | Type / default | Meaning |
|---|---|---|
| `--path PATH` | string / **required unless `--schema`** | File or directory to analyze |
| `--mode` | `orient` \| `audit`, default `orient` | `orient` per-file cards (default), `audit` repo-wide structural view. **Both currently emit the same per-file JSON array**; the distinct text audit summary was removed with the JSON-only transition, and the `audit` flag remains for interface compatibility. |
| `--max-files N` | int, default `20` | Cap the number of files scanned on large trees. |
| `--no-cache` | flag | Bypass the symbol cache (use after large renames/refactors). |
| `--changed [REF]` | flag; optional `REF` (default `HEAD`) | Analyze only files changed in the working tree, or changed since `REF`. Uses git. |
| `--schema` | flag | Print the JSON output schema and exit (no `--path` needed). |

**Exit codes:** `0` success; `1` bad path/arguments; `2` no supported source files found.

### Note on single-file output

Running against one file has no import graph, so `refs`, `importance`, and `blast_radius` are all `0`. The card carries a `note` field explaining this. Point scope at a directory for graph ranking and blast radius.

## JSON output

**One file** → a single JSON object. **A directory** → a JSON array of file objects (orient and audit both).

### Card object

| field | type | notes |
|---|---|---|
| `file` | string | File path (relative to the scanned directory). |
| `language` | string | Detected language, e.g. `Python`, `TypeScript`. |
| `summary` | string \| null | First descriptive header comment, or `null`. |
| `total_lines` | int | Line count. |
| `note` | string (optional) | Present only in single-file output; explains why graph fields are `0`. |
| `symbols` | array of symbol objects | Every extracted symbol. |
| `read_order` | array | Symbols ranked for reading (role priority, then importance). |
| `exports` | array of string | Exported names. |
| `imports` | object | Categorized: `built_in`, `external`, `internal` (each an array of strings). |
| `configs` | array | Extracted named constants: `{key, value, type, line}`. |
| `roles` | object | role → count. |
| `anomalies` | array | Detected problems: `{severity, type, message, locations}`. |

### Symbol object

| field | type | notes |
|---|---|---|
| `name` | string | |
| `kind` | string | `function`, `class`, `method`, `interface`, … |
| `line` | int | 1-indexed. |
| `exported` | bool | |
| `role` | string | one of the role enum below, or `unknown`. |
| `confidence` | string | `high` \| `medium` \| `low`. |
| `refs` | int | Cross-file in-degree (`0` in single-file mode). |
| `importance` | float | PageRank-blended salience (`0.0` in single-file mode). |
| `blast_radius` | int | Transitive dependent count (`0` in single-file mode). |

### Role enum

`entry_point` · `pi_tool` · `provider_config` · `http_caller` · `normalizer` · `data_mapper` · `config_value` · `async_orchestrator` · `predicate` · `accessor` · `mutator` · `unknown`

### Anomaly object

`severity`: `high` \| `medium` \| `low`. `type`: one of the 12 detectors: `asymmetry`, `silent_error`, `timing_mismatch`, `dual_mode_handler`, `weak_naming`, `missing_header`, `high_nesting`, `config_interleaving`, `inconsistent_error_handling`, `hardcoded_value`, `name_value_mismatch`, `unused_export`. `locations`: line numbers. `message`: human-readable explanation.

> Anomalies are **heuristic**. Scope flags; it does not decide. Expect occasional false positives; read the `message` and decide for yourself.

## How to keep this honest

Run `scope --schema` to print the canonical schema and compare it to this document.