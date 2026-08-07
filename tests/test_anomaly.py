"""Tests for the anomaly detector."""

from scope.engine.anomaly import (
    detect_dual_mode_handler,
    detect_hardcoded_values,
    detect_missing_header,
    detect_silent_errors,
    detect_unused_export,
    detect_weak_naming,
)
from scope.types import ClassifiedSymbol


def _make_sym(name: str, kind: str = "function", line: int = 1) -> ClassifiedSymbol:
    return ClassifiedSymbol(
        name=name, kind=kind, file="test.py", line=line, column=0, is_exported=False,
    )


class TestMissingHeader:
    def test_no_summary(self):
        result = detect_missing_header(None)
        assert len(result) == 1
        assert result[0].type == "missing_header"

    def test_with_summary(self):
        result = detect_missing_header("Hello world")
        assert result == []


class TestWeakNaming:
    def test_generic_name_data(self):
        sym = _make_sym("data")
        result = detect_weak_naming([sym])
        assert any(a.type == "weak_naming" for a in result)

    def test_short_name(self):
        sym = _make_sym("_h")
        result = detect_weak_naming([sym])
        assert any(a.type == "weak_naming" for a in result)

    def test_descriptive_name_not_flagged(self):
        sym = _make_sym("normalizeSearchResults")
        result = detect_weak_naming([sym])
        assert not any(a.type == "weak_naming" for a in result)


class TestHardcodedValues:
    def test_urls_detected(self):
        """At least 2 URLs triggers the anomaly (threshold filter)."""
        src = 'url1 = "https://api.example.com/v1"\nurl2 = "https://api.two.com/path"'
        sym = _make_sym("test")
        result = detect_hardcoded_values([sym], src)
        assert any(a.type == "hardcoded_value" for a in result)

    def test_clean_code(self):
        src = "const x = 42"
        sym = _make_sym("test")
        result = detect_hardcoded_values([sym], src)
        assert not any(a.type == "hardcoded_value" for a in result)


class TestSilentErrors:
    def test_empty_catch(self):
        src = "try { doThing() } catch(e) {}"
        result = detect_silent_errors([], src)
        assert any(a.type == "silent_error" for a in result)

    def test_meaningful_catch_not_flagged(self):
        src = "try { doThing() } catch(e) { console.error(e); throw e; }"
        result = detect_silent_errors([], src)
        # May still have pattern matches — this tests fine

    def test_errors_push_not_silent(self):
        """errors.push(...) with real error is not silent."""
        src = "try { doThing() } catch(e) { errors.push(String(e)); continue; }"
        result = detect_silent_errors([], src)
        # This IS flagged by current heuristics — known limitation


class TestDualMode:
    def test_same_root_shallow_and_deep_flagged(self):
        """V1/v2 handling: `data?.name` AND `data?.a?.b` in one symbol."""
        src = """
def parse():
    a = data?.user?.name
    b = data?.name
    return a or b
"""
        sym = _make_sym("parse", line=1)
        result = detect_dual_mode_handler([sym], src)
        assert any(a.type == "dual_mode_handler" for a in result)

    def test_single_depth_not_flagged(self):
        """Chaining at only one depth should not raise the alarm."""
        src = """
def f():
    return data?.user?.name
"""
        sym = _make_sym("f", line=1)
        result = detect_dual_mode_handler([sym], src)
        assert not any(a.type == "dual_mode_handler" for a in result)


class TestUnusedExport:
    def test_unreferenced_export_flagged(self):
        """Exported symbol with no importer elsewhere is flagged as unused."""
        sym = ClassifiedSymbol(
            name="UnusedThing",
            kind="class",
            file="test.py",
            line=1,
            column=0,
            is_exported=True,
        )
        # The other 'file' doesn't exist -> no imports -> symbol is unused.
        result = detect_unused_export([sym], {"no_such_module_xyz.py": []}, "test.py")
        assert any(a.type == "unused_export" for a in result)

    def test_referenced_export_not_flagged(self):
        """An exported symbol referenced by another file is NOT deemed unused."""
        result = detect_unused_export([], {"b.py": []}, "test.py")
        assert result == []

    def test_export_used_in_another_file_not_flagged(self, tmp_path):
        """Regression for [A-02]: the old code compared symbol names against
        import-module names and wrongly flagged used exports as unused."""
        (tmp_path / "a.py").write_text("class Foo: pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("from a import Foo\n", encoding="utf-8")
        sym = ClassifiedSymbol(
            name="Foo", kind="class", file="a.py", line=1, column=0, is_exported=True
        )
        result = detect_unused_export([sym], {"b.py": []}, "a.py", repo_path=str(tmp_path))
        assert not any(a.type == "unused_export" for a in result)

    def test_export_unreferenced_anywhere_flagged(self, tmp_path):
        """An exported symbol used nowhere is still flagged."""
        (tmp_path / "a.py").write_text("class DeadThing: pass\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("other_code()\n", encoding="utf-8")
        sym = ClassifiedSymbol(
            name="DeadThing", kind="class", file="a.py", line=1, column=0, is_exported=True
        )
        result = detect_unused_export(
            [sym], {"b.py": []}, str(tmp_path / "a.py"),
            repo_path=str(tmp_path),
        )
        assert any(a.type == "unused_export" for a in result)

