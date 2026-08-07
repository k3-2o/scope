from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

from scope.ast.engine.discover import SUPPORTED_EXTENSIONS

IMPORT_RE = re.compile(
    r"(?:from\s+([\w\.\/\-@]+)\s+import|import\s+([\w\.\/\-@]+)|require\(['\"]([^'\"]+)['\"]\)|use\s+([\w:]+))"
)
FROM_STRING_RE = re.compile(r"\bfrom\s+['\"]([^'\"]+)['\"]")
SIDE_EFFECT_IMPORT_RE = re.compile(r"^import\s+['\"]([^'\"]+)['\"]")

MAX_FILE_SIZE = 500_000


def read_text(repo_path: str, rel_path: str, max_bytes: int = MAX_FILE_SIZE) -> str:
    try:
        full_path = Path(repo_path) / rel_path
        if full_path.stat().st_size > max_bytes:
            return ""
        return full_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def extract_imports(repo_path: str, rel_path: str) -> list[str]:
    text = read_text(repo_path, rel_path)
    if not text:
        return []
    ext = Path(rel_path).suffix
    imports: set[str] = set()
    for line in text.splitlines()[:2000]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "*")):
            continue
        if ext in (".js", ".ts", ".tsx"):
            match = FROM_STRING_RE.search(stripped) or SIDE_EFFECT_IMPORT_RE.search(stripped)
            if match:
                imports.add(match.group(1))
            require = re.search(r"require\(['\"]([^'\"]+)['\"]\)", stripped)
            if require:
                imports.add(require.group(1))
            continue
        if ext == ".py" and not stripped.startswith(("import ", "from ")):
            continue
        if ext == ".rs" and not stripped.startswith("use "):
            continue
        if ext == ".go" and not (stripped.startswith("import ") or stripped.startswith('"')):
            continue
        for match in IMPORT_RE.finditer(stripped):
            target = next((g for g in match.groups() if g), "")
            if target:
                imports.add(target)
    return sorted(imports)


def resolve_internal_import(import_name: str, importer: str, files: list[str]) -> str | None:
    file_set = set(files)
    candidates: set[str] = set()

    # Relative imports (Python ./ ../)
    if import_name.startswith("."):
        base = Path(importer).parent / import_name
        base_s = str(base).replace("\\", "/")
        candidates.add(base_s)  # bare module file (extension appended later)
        candidates.add(base_s + "/index")  # or a package dir with an index module

    # Absolute module names — try progressively shorter prefixes so the package
    # root doesn't have to coincide with the scanned directory root.
    dotted = import_name.replace("::", "/").replace(".", "/")
    segs = dotted.strip("/").split("/")
    for i in range(len(segs)):
        stem = "/".join(segs[i:])
        for prefix in ("", "src/"):
            padded = (prefix + stem) if prefix else stem
            candidates.add(padded)

    for cand in candidates:
        for ext in SUPPORTED_EXTENSIONS:
            norm = os.path.normpath(cand + ext).replace("\\", "/")
            if norm in file_set:
                return norm
    return None


def dependency_graph(repo_path: str, files: list[str]) -> dict[str, any]:
    """Build a dependency map: internal imports (who imports whom) and external packages."""
    imports_by_file: dict[str, list[str]] = {}
    imported_by: dict[str, set[str]] = defaultdict(set)
    external: dict[str, int] = defaultdict(int)

    for rel_path in files:
        if Path(rel_path).suffix not in SUPPORTED_EXTENSIONS:
            continue
        imports = extract_imports(repo_path, rel_path)
        imports_by_file[rel_path] = imports
        for item in imports:
            internal = resolve_internal_import(item, rel_path, files)
            if internal:
                imported_by[internal].add(rel_path)
            else:
                root = item.split("/", 1)[0].split(".", 1)[0].split("::", 1)[0]
                if root and not root.startswith("."):
                    external[root] += 1

    internal_counts = {file: len(importers) for file, importers in imported_by.items()}
    return {
        "internal_counts": dict(
            sorted(internal_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "external_counts": dict(sorted(external.items(), key=lambda item: (-item[1], item[0]))),
    }
