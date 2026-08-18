# Tutorial — Orient Yourself in a New Codebase in 10 Minutes

You have just landed in a codebase you have never seen and need to know where to look. This walks you end to end (install, a first scan, reading the output) without branching.

**Prereqs:** Python 3.11+, and scope installed (Step 1). No other tools; `jq` is optional in Step 4.

## Step 1 — Install

```bash
git clone https://github.com/k3-2o/scope
cd scope
pip install -e .
```

Verify it works:

```bash
scope --help
```

You should see the `--path`, `--mode`, `--schema` flags.

## Step 2 — Open a single file

Point scope at any file you are curious about (this example uses the project's own types file, but use a file in *your* project):

```bash
scope --path src/scope/types.py
```

You get one compact JSON object. What matters first:

- `top` — the top-`importance` symbols (up to 8) with `name`, `role`, `line`, and `blast`.
- `roles` — how many instances of each role the file has.
- `anomalies` — anything suspicious, with `type`, `severity`, and `loc`.

Example (trimmed):

```json
{
  "file": "types.py",
  "language": "Python",
  "total_lines": 248,
  "top": [{ "name": "ClassifiedSymbol", "role": "unknown", "line": 3, "blast": 0 }],
  "roles": {}, "anomalies": []
}
```

Add `--full` to expand every symbol with `summary`, `read_order`, `refs`, `importance`, and the human-readable anomaly `message`.

> In single-file mode `refs`/`blast_radius` are `0` (there is no surrounding graph). A `note` field tells you this. For ranking you need a directory — that's Step 3.

## Step 3 — Open a directory

To see importance and blast radius, hand scope the whole tree:

```bash
scope --path path/to/my/project
```

You get a JSON **array**, one card per file. To find the files that matter most, sort cards by their `top[].blast` field (or run `--full` and use each symbol's `blast_radius`): those are the files the most code depends on.

## Step 4 — Read it like a human with jq

If `jq` is installed, you can turn the directory array into a skim-able table:

```bash
scope --path /to/my/project --full | \
  jq -r '.[].symbols[] | select(.role != "unknown") | [.name, .role, .refs, .blast_radius] | @tsv'
```

Expected shape (columns: name, role, refs, blast radius):

```tsv
main   entry_point   4  0
normalize_scope   normalizer   1  7
```

`normalize_scope` has blast radius 7: seven other files transitively depend on it — that is what "important" means here.

## Step 5 — Focus on what changed (optional 2 minutes)

If you are orienting before a PR, skip unchanged files:

```bash
scope --path /path/to/my/project --changed HEAD
```

You now get cards only for files changed in your working tree.

---

**Where next?** Read a file's `read_order` top-to-bottom when you start editing. For deeper workflows (finding dead exports, ranking a blast radius, caching gotchas) see [How-to](how-to.md). For every flag and field, see [Reference](reference.md).