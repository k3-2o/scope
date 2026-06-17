---
name: scope
description: "Generates compact orientation cards for source files and directories — showing entry points, exports, imports, symbol roles, cross-file dependencies, and structural issues ranked by importance. Use when: dropped into an unfamiliar codebase and cannot name the top 3 most important files; the user gives an open-ended task spanning multiple modules and you need the project map first; about to edit or refactor a file you haven't read yet and need the symbol-level read order; or about to rename or move a shared symbol and need to check what depends on it. Trigger words: orient, explore, overview, map codebase, understand file, code structure, file summary, radar, unfamiliar repo, critical path, read order."
compatibility: "Requires Python 3.11+ and `uv`. Install with `uv tool install` from the scope repo root."
---

# Scope

Codebase orientation radar. Understand what you're looking at before you read a single line.

## Setup

Check prerequisites:

```bash
which scope
```

If missing, install:

```bash
git clone https://github.com/k3-2o/scope ~/scope && cd ~/scope && uv tool install .
```

Verify: `which scope`

## When to invoke

- **New project, no map.** You just entered a codebase and cannot name its three most important files. Run `scope --path <directory>` to get per-file cards ranked by importance and issue count.
- **About to edit unfamiliar code.** The user asked you to modify a file you haven't read yet. Run `scope --path <file>` first to get the symbol-level read order — which symbols to read, and in what sequence, before writing a single edit.
- **Cross-file impact check.** You renamed or moved a shared symbol and need to know what other files reference it. Run `scope --path <file>` and inspect the imports, exports, and cross-file reference counts in the card.
- **Pre-review or refactor health pass.** You need a quick structural overview across a directory before diving deeper. Run `scope --path <directory>` to surface files ranked by anomaly and dependency density.

## Workflow

### Step 1: Orient on a single file

```bash
scope --path <file>
```

Returns a compact card with five sections: language header, symbol stats, ranked read order, anomalies, and role classifications.

**Read the read-order symbols first.** They are ranked by role priority (entry points first), then cross-file reference count (higher = more files depend on it), then line number. This is the critical path through the file.

### Step 2: Orient on a directory

```bash
scope --path <directory>
```

Produces a card for every supported file plus a directory summary. The summary surfaces files ranked by issue count and cross-file reference density. Focus on high-anomaly files first.

For large directories, cap the scan:

```bash
scope --path <directory> --max-files 50
```

For a repo-wide structural summary:

```bash
scope --path <directory> --mode audit
```

### Step 3: Get full detail when the compact card isn't enough

```bash
scope --path <file> --verbose
```

Shows every symbol with its line number, role, and classification confidence — useful when something didn't get classified or you need to see what was missed.

### Step 4: Get structured output for downstream processing

```bash
scope --path <file> --output json
```

Use JSON when another step or tool needs to parse the card programmatically. Default text output is for human and agent reading.

### Step 5: Bypass the cache after large refactors

After renames, moves, or mass edits the symbol cache may be stale:

```bash
scope --path <directory> --no-cache
```

## Interpreting output

Your job is to read the card and act on it, not to dump it back at the user. Prioritize:

- **Read order** — the critical path. Start there before reading anything else.
- **Cross-file references** — blast radius for any edit. Symbols other files import are high-risk when renaming or restructuring.
- **Anomalies** — structural red flags (hardcoded values, deep nesting, silent catch blocks). Note them, then judge for yourself. The tool classifies; it does not decide.
- **Role classifications** — what each symbol does (entry point, http caller, normalizer, config loader). Use these to build a mental model fast.

## When to Skip

- The path is a config file with no symbols to classify (`package.json`, `pyproject.toml`, `.env`)
- The file is binary, minified, or auto-generated
- You already know the file structure and just need to find one specific symbol
- The task is a trivial one-line edit in code you already understand
- You need code complexity metrics, test coverage, or security analysis — use a structural analysis tool for that
- You need deep logical analysis of a single function's correctness — scope shows structure, not semantic correctness
