"""CLI regression tests — JSON-only output shape + handler wiring."""

import io
import json
import os
from contextlib import redirect_stdout

import scope
from scope.types import OrientationCard

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO_ROOT, "tests")


def _run(fn, *args, **kwargs) -> str:
    """Run a handler and capture what it prints to stdout."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


class TestDirectoryJSON:
    """Directory paths must emit ONE well-formed JSON document."""

    def test_orient_output_is_a_single_json_array(self):
        out = _run(scope._handle_directory_orient, TESTS_DIR, 10)
        data = json.loads(out)  # raises if the output isn't one valid doc
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any("file" in card and "symbols" in card for card in data)

    def test_audit_output_is_a_single_json_array(self):
        out = _run(scope._handle_directory_audit, TESTS_DIR, 10)
        data = json.loads(out)
        assert isinstance(data, list)

    def test_single_file_output_is_a_single_json_object(self):
        target = os.path.join(TESTS_DIR, "test_anomaly.py")
        out = _run(scope._handle_file, target, None)
        data = json.loads(out)
        assert isinstance(data, dict)
        assert data.get("file") == "test_anomaly.py"

    def test_read_order_and_symbol_fields_present(self):
        out = _run(scope._handle_directory_orient, TESTS_DIR, 10)
        data = json.loads(out)
        card = next(c for c in data if c["symbols"])
        assert "read_order" in card
        sym = card["symbols"][0]
        for key in ("name", "line", "role", "refs", "importance", "blast_radius"):
            assert key in sym


class TestDoubleParseRemoved:
    """Directory mode should extract each file exactly once."""

    def test_each_file_parsed_once(self):
        orig_extract = scope.extract_symbols
        calls: dict[str, int] = {}

        def counted(rel, repo):
            calls[rel] = calls.get(rel, 0) + 1
            return orig_extract(rel, repo)

        scope.extract_symbols = counted
        try:
            # use_cache=False keeps this deterministic (always a fresh parse).
            _run(scope._handle_directory_orient, TESTS_DIR, 10, False)
        finally:
            scope.extract_symbols = orig_extract

        assert calls, "expected at least one file to be parsed"
        assert all(n <= 1 for n in calls.values()), f"double-parse detected: {calls}"


class TestCardBuilding:
    """Cards are built from the shared, cached symbol data."""

    def test_cards_built_from_reused_symbols_at_directories(self):
        files = scope.discover(TESTS_DIR)[:5]
        syms, lookup = scope._collect_symbols_and_refs(
            files, TESTS_DIR, max_files=5, use_cache=False
        )
        card = None
        for f in files:
            card = scope._build_card(
                os.path.join(TESTS_DIR, f),
                TESTS_DIR,
                ref_lookup=lookup,
                scope_symbols=syms.get(f),
            )
            if card:
                break
        assert isinstance(card, OrientationCard)


class TestSchemaAndNotes:
    """JSON conveniences + single-file guidance note."""

    def test_schema_is_well_formed(self):
        schema = scope._scope_schema()
        assert schema["version"] == 1
        assert "symbols" in schema["single_file"]["fields"]

    def test_single_file_json_includes_note(self):
        target = os.path.join(TESTS_DIR, "test_anomaly.py")
        payload = json.loads(_run(scope._handle_file, target, None))
        assert "note" in payload

    def test_no_git_returns_all_files(self, tmp_path):
        # Not a git repo -> _repo_root returns None -> _changed_files doesn't filter.
        (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
        discovered = scope.discover(str(tmp_path))
        assert scope._changed_files(discovered, str(tmp_path), "HEAD") == discovered


class TestCacheWiring:
    """Cached directory mode must reload symbols without re-parsing files."""

    def test_cache_skips_reparse_on_second_run(self, tmp_path, monkeypatch):
        # Sandbox the on-disk cache under a temp dir so the test is hermetic.
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("def beta():\n    return alpha()\n", encoding="utf-8")

        orig_extract = scope.extract_symbols
        extracted: list[str] = []

        def counting(rel, repo):
            extracted.append(rel)
            return orig_extract(rel, repo)

        scope.extract_symbols = counting
        try:
            first = json.loads(_run(scope._handle_directory_orient, str(tmp_path), 5))
            extracted.clear()
            second = json.loads(_run(scope._handle_directory_orient, str(tmp_path), 5))
        finally:
            scope.extract_symbols = orig_extract

        assert isinstance(first, list) and isinstance(second, list)
        assert len(extracted) == 0, f"cache hit should skip re-parse, got: {extracted}"
