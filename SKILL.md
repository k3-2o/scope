---
name: opener
description: "Generate a compact orientation card for any source file — shows entry points, exports, imports, configs, structural issues, and what to read first. Use when: dropped into an unfamiliar codebase, need to understand a file without reading it all, want to know what symbols are important before editing, or looking for structural problems (hardcoded values, deep nesting, silent error handling) before a code review. Trigger words: orient, explore, what's here, map codebase, overview, understand file, read order, code structure, file summary, radar."
compatibility: "Requires Python 3.11+ and `uv` tool. Install: `uv tool install /path/to/opener` from the repo root."
---

# Opener

## Setup

Check if opener is available:

```bash
which opener
```

If not found, ask the user: **"opener is not installed. Install it from github.com/k3-2o/scope?"**
If they agree, clone and install:

```bash
git clone https://github.com/k3-2o/scope ~/opener
cd ~/opener
uv tool install .
```

Then verify:

```bash
which opener
```

## Workflow

### Step 1: Get Your Bearings on a File

Run:

```bash
opener --path <file>
```

This prints a compact card with five sections:
- **Header** — file language and one-line summary from its own docstring
- **Stats** — how many symbols, roles, exports, imports, configs, anomalies
- **Read Order** — symbol names ranked by importance, with line numbers. Read these first.
- **Anomalies** — structural issues the tool found (hardcoded URLs, deep nesting, silent catch blocks)
- **Roles** — what each classified symbol does (entry_point, normalizer, http_caller, etc.)

### Step 2: Orient on a Directory

If you're new to a project, run:

```bash
opener --path <directory>
```

This produces a card for every supported file plus a directory summary showing which files have the most issues. Focus on the high-anomaly files first — they need more attention.

### Step 3: Read the Top Anomalies Yourself

For each anomaly in the card, open the file and judge for yourself:

- **Hardcoded URLs** — should they be extracted to a config constant?
- **Deep nesting** — is the function genuinely hard to follow, or is it a state machine that needs the branches?
- **Silent catch blocks** — does the error get handled elsewhere, or is it genuinely swallowed?
- **Dual-mode handlers** — is it a v1/v2 compatibility shim, or just sloppy code?

### Step 4: Read in the Suggested Order

The "Read Order" section lists symbols ranked by:
1. Role priority (entry points first)
2. Cross-file reference count (higher = more files depend on it)
3. Line number (earlier in file = tiebreaker)

Open each file and read the listed symbols in that order. This gives you the critical path through the file without reading everything.

### Step 5: Get More Detail When Needed

If the compact card doesn't give enough context, run with verbose:

```bash
opener --path <file> --verbose
```

This shows every symbol with its line number, role, and classification confidence. Use this when you need to see what didn't get classified.

## When to Skip

Do not use opener when:
- The file is a config file (package.json, pyproject.toml, tsconfig.json) — no symbols to classify, the card will be empty
- The file is binary or minified — opener skips these automatically via extension and null-byte detection
- You already know the file structure — the card is for orientation, not detailed analysis
- The task is a simple one-line edit — opener helps with unfamiliar code, not trivial changes you already understand
- You need code quality metrics (complexity, test coverage) — use a structural analysis tool for that
- You need deep logical analysis of a single function — opener shows structure, not correctness
