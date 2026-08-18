# Scope

> Turn any file or directory into a structured **codebase orientation map** with entry points, exports, imports, symbol roles, and an importance ranking, as machine-readable JSON.

Scope is a CLI for the problem every developer meets: *what is this file, what matters in it, and where do I look first?* Instead of reading a whole file to find out, scope parses it with Tree-sitter (25+ languages), classifies each symbol into a role, detects structural anomalies, and ranks symbols by cross-file importance and blast radius, then emits clean JSON for `jq`, a script, or a coding agent.

## Features

- **One-file or whole-directory orientation**, output as strict JSON (no human-formatting layer to fight).
- **Role classification** — every symbol tagged as an `entry_point`, `http_caller`, `normalizer`, `accessor`, `mutator`, `predicate`, etc.
- **Graph ranking** — PageRank over the import graph + transitive **blast radius**, so central files surface first.
- **Anomaly detection** — 12 heuristic rules flag high nesting, silent catch blocks, hardcoded values, unused exports, and more.
- **Fast** — symbol cache, `--changed <ref>` for diff-scoped scans, and 25+ languages via Tree-sitter.

## Quick Start

```bash
pip install -e .          # or: uv sync && uv tool install .
scope --path src/main.py
```

JSON for any file in one command.

## Usage

```bash
scope --path src/main.py             # one file  → JSON object
scope --path src/                    # a directory → JSON array of files
scope --path src/ --mode audit       # repo-wide structural view (JSON)
scope --path src/ --changed           # only files changed since HEAD
scope --path src/ --changed v1.0      # files changed since a ref
scope --path src/ --full              # detailed per-symbol view
scope --path src/ --exit-code         # exit 1 when any anomaly is flagged
scope --schema                        # document the JSON shape, then exit
```

By default the output is a **compact summary** per file (top symbols, role
tallies, anomalies) — trimmed so an agent can afford to read it. `--full`
expands to every symbol with `refs`/`importance`/`blast_radius`/`read_order`.


Drill in with `jq`:

```bash
scope --path src/ --full | \
  jq -r '.[].symbols[] | select(.role != "unknown") | [.name, .role, .refs, .blast_radius] | @tsv'
```

## Documentation

- [Reference — CLI flags & the JSON contract](docs/reference.md)
- [Tutorial — orient yourself in a new codebase](docs/tutorials.md)
- [How-to — practical workflows](docs/how-to.md)
- [Architecture — how scope works](docs/architecture.md)

## Contributing

Bug reports and pull requests are welcome. Requirements are enforced in CI (ruff, mypy, pytest).

## License

MIT — see [LICENSE](LICENSE).