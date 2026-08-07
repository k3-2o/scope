# How-To Guides

Task-oriented recipes for `scope`. Each solves one problem. For every flag in detail, see [Reference](reference.md).

## How to find the files that matter most

Rank files/symbols by dependency centrality, not by size.

```bash
scope --path /my/project | jq -r '
  .[] | select(any(.symbols[]; .blast_radius > 0))
       | [.file, ([.symbols[] | .blast_radius] | max)] | @tsv'
```

High blast radius = many files transitively depend on this one. Changed it, and it ripples. Want the **whole repo**, not the first 20 files:

```bash
scope --path /my/project --max-files 10000
```

**Verify:** the files listed each have `blast_radius > 0`, and the top rows are the files you'd expect (data models, shared utils), not tests.

## How to scan only what changed since a ref

Skip files you haven't touched.

```bash
scope --path /my/project --changed          # working tree vs HEAD
scope --path /my/project --changed v2.0     # files changed since v2.0
```

Uses `git`; run from inside the repo. **Limitation:** `--changed` filters the scanned file set; the card's own `refs`/`blast_radius` still come from the (now smaller) set, so numbers are relative to what you scanned.

**Verify:** the output card for a file you edited this session should appear; the unedited ones should not.

## How to find potentially dead code

Scope has a heuristic for "exported but not referenced anywhere":

```bash
scope --path /my/proj | jq -r '
 .[] | .anomalies[]? | select(.type == "unused_export") | [.file, .message] | @tsv'
```

**Caveat:** `unused_export` is heuristic and only fires in directory scans. Treat its output as leads, not a verdict — grep before deleting anything.

## How to bypass a stale symbol cache

The cache keys on file mtimes + git HEAD. After a mass rename or move, the cached symbols can lag:

```bash
scope --path /my/proj --no-cache
```

**Verify:** re-run once (no-cache), then once normally; both should agree.

## How to read scope as a coding agent

Scope was built for agents. Have the agent:

```bash
scope --path <dir> | jq -c '. as $ro | ... '
```

For an agent, the highest-value fields are `read_order` (which symbols to read first), `blast_radius` (what a change affects), and `role` (what a symbol does). Instruct the agent to **read the `read_order` symbols, not re-derive the map**, and to check `blast_radius` before renaming/moving a shared symbol.

## How to look genuinely, not skim

- Prefer directory scans for any "what's important?" question (single-file shows `refs`/`blast_radius` = 0).
- Treat anomalies as hints and read the `message`+`locations` yourself.
- Confirm with `grep`/reading before trusting `unused_export` or `high_nesting`.

For each task there's a Decision Tree on the [Reference](reference.md); pick the reading path that fits.