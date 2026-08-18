---
name: scope
description: "Codebase orientation radar. Emits JSON only: a compact per-file map (language, top symbols by importance, role counts, anomalies) by default, with --full for every symbol plus read order and blast radius. Use when: just landed in an unfamiliar codebase and need the top 3-5 most important files/symbols without reading everything; given an open-ended task spanning modules and need the project map first; about to edit or rename a shared symbol and need to know what depends on it; or judging whether a structural refactor touched high-risk code. Trigger words: orient, explore, overview, map codebase, understand file, code structure, file summary, radar, unfamiliar repo, critical path, read order."
compatibility: "Requires Python 3.11+ and `uv`. Install: `uv tool install` from the scope repo root."
---

# Scope

Codebase orientation radar. You understand what you are looking at before you read a single line — and you only pay JSON tokens for the detail you actually need.

## Setup

```bash
which scope        # installed?
# if missing:
uv tool install /path/to/scope     # or: git clone https://github.com/k3-2o/scope && cd scope && uv tool install .
```

## Output contract (current CLI)

`scope` emits **JSON only** — a single object for one file, an array of per-file objects for a directory. Two tiers:

| Tier | Command | You get |
|---|---|---|
| **Compact (default)** | `scope --path <file>/<dir>` | `file`, `language`, `total_lines`, `top` (≤8 highest-`importance` symbols with `name`/`role`/`line`/`blast`), `roles` (role→count), `anomalies` (`type`/`severity`/`loc`). Minified. |
| **Detail** | add `--full` | Every symbol (`name`,`kind`,`line`,`exported`,`role`,`confidence`,`refs`,`importance`,`blast_radius`), plus `summary`, `read_order`, `exports`, `imports`, `configs`. Pretty-printed. |

> The default is a **summary, not the whole dump**. It deliberately truncates to the top symbols. Take the `--full` view when you need the complete symbol map or the read order.

Full flag surface:

| Flag | Purpose |
|---|---|
| `--mode orient\|audit` | both emit the same per-file array; `audit` kept for compatibility |
| `--max-files N` | default `20`, cap the scan on large trees |
| `--changed [REF]` | only files changed in the working tree (no REF) or since `REF` (default `HEAD`) |
| `--no-cache` | bypass the symbol cache after big renames/refactors |
| `--full` | the detailed per-symbol card |
| `--exit-code` | exit `1` when any anomaly is flagged, else `0` (script/CI gating, like semgrep) |
| `--schema` | print the JSON contract and exit (no `--path` needed) |

## When to invoke

- **New project, no map.** `scope --path <dir>` for per-file compact cards. Read each `top` and the `anomalies` first; that names the files and their important symbols before you open anything.
- **About to edit unread code.** `scope --path <file> --full`, then read `read_order` top-to-bottom — it is the critical path through that file. Read in that order before writing.
- **Cross-file impact / rename.** `scope --path <dir> --full`, then look at `blast_radius` and `refs`. Symbols other files import are high-risk to rename or move.
- **Health / pre-review pass.** `scope --path <dir>` and focus on the cards with the most `anomalies`; then `--full` on just those files.

## Workflows

### 1) Single file — compact to full

```bash
scope --path src/main.py                     # compact object
scope --path src/main.py --full              # full symbols + read_order
```

### 2) Directory — map with the compact cards, deep-dive on targets

```bash
scope --path .                               # array of compact cards
scope --path . --max-files 100               # cap a large tree
scope --path . --full | jq -r '. | ... '
```

### 3) Diff-scoped scan

```bash
scope --path . --changed                     # only files changed vs HEAD
scope --path . --changed v2.0               # only files changed since v2.0
```

### 4) Scriptable gating

```bash
scope --path . --exit-code && echo clean || echo "anomalies found"
```

### 5) Downstream route (JSON always)

```bash
# top symbols across the repo (compact has .top; full has .symbols):
scope --path . --full | jq -r '.[].symbols[] | select(.role != "unknown") | [.name, .role, .refs, .blast_radius] | @tsv'
```

## Interpreting output

- Read `top`/`read_order` **first**, before reading anything else — it is the critical path.
- Watch `blast_radius`: a symbol many files transitively depend on is high-risk to rename or restructure.
- `anomalies` are *heuristic* — the tool flags, it does not decide. Judge each `message` yourself.
- `roles` tell you what a symbol does (entry point, http caller, normalizer, config loader) — build the mental model fast.

## When to skip

- The path is a config file with no symbols to classify (`package.json`, `pyproject.toml`, `.env`)
- The file is binary, minified, or auto-generated
- You already know the structure and just need one symbol
- It's a trivial one-line edit in code you already understand
- You need complexity metrics, test coverage, or security analysis — use a structural analysis tool

---

_Keep this skill in sync with `docs/reference.md` — the `--schema` command is the source of truth; re-run it after any output contract change._
