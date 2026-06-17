# Scope

**Codebase orientation radar.** Understand any file in one screen — entry points, exports, imports, configs, anomalies. No reading the whole thing required.

Works on Python, TypeScript, JavaScript, Go, Rust, Java, C++, and 25+ languages.

## Install

```bash
git clone https://github.com/k3-2o/scope ~/scope
cd ~/scope
uv tool install .
```

Verify:

```bash
scope --help
```

## Usage

```bash
scope --path src/main.py          # one file card
scope --path src/                 # directory cards + summary
scope --path src/ --mode audit    # aggregated health overview
scope --path src/ --verbose       # full symbol detail
scope --path src/ --output json   # machine-readable
```

## Example Output

```
  handler.ts
  TypeScript  |  Processes HTTP requests and routes to services

  Symbols: 24  |  Roles: 6  |  Exports: 3  |  Imports: 8  |  Anomalies: 2  |  Configs: 4

Read Order (start here)
  1. execute (L155)  → entry_point  ← 3 refs
  2. validateRequest (L42)  → accessor
  3. formatResponse (L89)  → normalizer

Anomalies
  🟡 [MEDIUM] high_nesting L[120]
  🟢 [LOW] hardcoded_value L[30]

Roles
  entry_point    1  |  normalizer  2  |  accessor  3
```

## How It Works

```
discover → parse → classify → extract → detect → rank → render
```

Six phases layered on Tree-sitter symbol extraction. See [`docs/scope/SKILL.md`](docs/scope/SKILL.md) for the full workflow.

## License

MIT
