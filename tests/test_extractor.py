"""Tests for the extractor — headers, exports, configs."""

from scope.engine.extractor import _extract_header, _extract_exports, _extract_configs
from scope.types import Comment


class TestHeaderExtraction:
    def test_block_comment_header(self):
        """First block comment (non-license) becomes the summary."""
        comments = [Comment(text="/**\n * My File\n * Does a thing\n */", start_line=1, end_line=4)]
        result = _extract_header(comments)
        assert result is not None
        assert "My File" in result

    def test_license_header_skipped(self):
        """License headers should not be extracted as file summary."""
        comments = [
            Comment(text="Copyright 2024 MIT License", start_line=1, end_line=1),
            Comment(text="/**\n * Actual Description\n */", start_line=3, end_line=5),
        ]
        result = _extract_header(comments)
        assert result is not None
        assert "Actual Description" in result
        assert "Copyright" not in (result or "")

    def test_no_header_returns_none(self):
        """File with no comments returns None."""
        result = _extract_header([])
        assert result is None


class TestExportExtraction:
    def test_typescript_default_export(self):
        source = "export default function omniSearchGateway(pi: any) {}"
        exports = _extract_exports([], source, "TypeScript")
        assert "omniSearchGateway" in exports

    def test_typescript_named_export(self):
        source = "export function foo() {}\nexport class Bar {}"
        exports = _extract_exports([], source, "TypeScript")
        assert "foo" in exports
        assert "Bar" in exports

    def test_python_exports(self):
        source = "def foo():\n    pass\n\ndef _bar():\n    pass\n\nclass Baz:\n    pass"
        exports = _extract_exports([], source, "Python")
        assert "foo" in exports
        assert "_bar" in exports  # Python exports everything at module level
        assert "Baz" in exports

    def test_no_exports(self):
        source = "42"
        exports = _extract_exports([], source, "Python")
        assert exports == []


class TestConfigExtraction:
    def test_number_config(self):
        source = "TIMEOUT_MS = 15000"
        configs = _extract_configs(source)
        assert len(configs) == 1
        assert configs[0].key == "TIMEOUT_MS"
        assert configs[0].type == "number"

    def test_string_config(self):
        source = 'const NAME = "opener"'
        configs = _extract_configs(source)
        assert len(configs) == 1
        assert configs[0].key == "NAME"
        assert configs[0].type == "string"

    def test_boolean_config(self):
        source = "const DEBUG = true"
        configs = _extract_configs(source)
        assert len(configs) == 1
        assert configs[0].key == "DEBUG"
        assert configs[0].type == "boolean"

    def test_no_configs(self):
        source = "function foo() { return 42; }"
        configs = _extract_configs(source)
        assert configs == []
