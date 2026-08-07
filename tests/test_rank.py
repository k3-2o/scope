"""Tests for the graph-aware ranking (PageRank + blast radius) and import resolution."""


from scope.ast.engine.rank import _page_rank, compute_importance
from scope.ast.engine.references import resolve_internal_import
from scope.ast.models import Symbol


class TestImportResolution:
    """The internal-import resolver must handle varying package-root layouts."""

    def test_absolute_module_matches_stripped_prefix(self):
        files = ["ast/engine/rank.py", "engine/types.py"]
        assert (
            resolve_internal_import("scope.ast.engine.rank", "engine/parser.py", files)
            == "ast/engine/rank.py"
        )

    def test_relative_import_resolves_with_extension(self):
        files = ["engine/sub/feature.py"]
        base = resolve_internal_import("./feature", "engine/sub/__init__.py", files)
        assert base == "engine/sub/feature.py"

    def test_unknown_module_returns_none(self):
        assert resolve_internal_import("nonexistent_mod", "a.py", ["a.py", "b.py"]) is None


class TestPageRank:
    def test_transitive_chain_roots_root_file(self):
        pr = _page_rank(["a.py", "b.py", "c.py"], {"c.py": ["b.py"], "b.py": ["a.py"]})
        assert pr["a.py"] > pr["b.py"] > pr["c.py"]

    def test_isolated_node_gets_minimal_weight(self):
        pages = _page_rank(["a.py", "b.py", "c.py"], {"b.py": ["a.py"]})
        # c imports nothing and nothing imports it -> lowest rank
        assert pages["c.py"] < pages["a.py"]


class TestBlastRadius:
    def test_transitive_dependents_counted(self, tmp_path):
        (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text(
            "from a import alpha\n\ndef beta():\n    return alpha()\n", encoding="utf-8"
        )
        (tmp_path / "c.py").write_text(
            "from b import beta\n\ndef gamma():\n    return beta()\n", encoding="utf-8"
        )

        repo = str(tmp_path)
        all_symbols = {
            "a.py": [Symbol(name="alpha", kind="function", file="a.py", line=1)],
            "b.py": [Symbol(name="beta", kind="function", file="b.py", line=3)],
            "c.py": [Symbol(name="gamma", kind="function", file="c.py", line=3)],
        }
        compute_importance(all_symbols, repo)

        # a is imported by b and transitively by c -> blast 2; b -> 1; c -> 0.
        assert all_symbols["a.py"][0].blast_radius == 2
        assert all_symbols["b.py"][0].blast_radius == 1
        assert all_symbols["c.py"][0].blast_radius == 0
        # graph overlay should make alpha (transitively depended on) out-rank gamma.
        assert all_symbols["a.py"][0].importance > all_symbols["c.py"][0].importance
