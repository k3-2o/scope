"""Tests for the classifier."""

from pathlib import Path

from scope.engine.classifier import classify_symbols
from scope.types import ClassifiedSymbol


def _make_sym(name: str, kind: str = "function", line: int = 1, exported: bool = False) -> ClassifiedSymbol:
    return ClassifiedSymbol(
        name=name,
        kind=kind,
        file="test.py",
        line=line,
        column=0,
        is_exported=exported,
    )


class TestNamingClassification:
    """Role assignment based on symbol names (language-agnostic)."""

    def test_normalizer_prefix(self):
        sym = _make_sym("normalizeSerper")
        classify_symbols([sym], "/tmp")
        assert sym.role == "normalizer"
        assert sym.confidence == "medium"

    def test_predicate_prefix(self):
        sym = _make_sym("isAvailable")
        classify_symbols([sym], "/tmp")
        assert sym.role == "predicate"

    def test_accessor_prefix(self):
        sym = _make_sym("getTaskResult")
        classify_symbols([sym], "/tmp")
        assert sym.role == "accessor"

    def test_mutator_prefix(self):
        sym = _make_sym("createTask")
        classify_symbols([sym], "/tmp")
        assert sym.role == "mutator"

    def test_entry_point_exported(self):
        sym = _make_sym("main", exported=True)
        classify_symbols([sym], "/tmp")
        assert sym.role == "entry_point"

    def test_entry_point_execute(self):
        sym = _make_sym("execute")
        classify_symbols([sym], "/tmp")
        assert sym.role == "entry_point"

    def test_constructor_new(self):
        sym = _make_sym("new")
        classify_symbols([sym], "/tmp")
        assert sym.role == "entry_point"

    def test_config_value_uppercase(self):
        sym = _make_sym("TIMEOUT_MS")
        classify_symbols([sym], "/tmp")
        assert sym.role == "config_value"

    def test_python_private_underscore(self):
        """Python _prefixed functions should match the prefix after stripping _."""
        sym = _make_sym("_is_valid")
        classify_symbols([sym], "/tmp")
        assert sym.role == "predicate"

    def test_unknown_fallback(self):
        sym = _make_sym("doStuff")
        classify_symbols([sym], "/tmp")
        assert sym.role == "unknown"
        assert sym.confidence == "low"


class TestStructuralClassification:
    """Role assignment based on source structure (requires real file)."""

    def test_http_caller_fetch(self, tmp_path: Path):
        """A function calling fetch() should be http_caller.

        Use a name that doesn't match any naming prefix so the structural
        check (which runs second) has a chance to fire.
        """
        src = "async def make_request():\n    return await fetch('https://api.example.com')"
        f = tmp_path / "caller.py"
        f.write_text(src)
        result = _parse(tmp_path, "caller.py")
        classify_symbols(result.symbols, str(tmp_path))
        sym = result.symbols[0]
        assert sym.role == "http_caller"
        assert sym.confidence == "high"


def _parse(repo: Path, file: str):
    """Helper: parse a single test file."""
    from scope.engine.parser import parse_file
    return parse_file(file, str(repo))
