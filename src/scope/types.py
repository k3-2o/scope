"""
Shared types for the scope pipeline.

Every phase reads from or writes to these dataclasses. Keep them lean.
No business logic — just data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------

Role = Literal[
    "entry_point",
    "pi_tool",
    "provider_config",
    "http_caller",
    "normalizer",
    "data_mapper",
    "config_value",
    "async_orchestrator",
    "predicate",
    "accessor",
    "mutator",
    "unknown",
]

ROLE_PRIORITY: dict[Role, int] = {
    "entry_point": 1,
    "pi_tool": 1,
    "async_orchestrator": 2,
    "provider_config": 3,
    "http_caller": 3,
    "normalizer": 4,
    "data_mapper": 4,
    "accessor": 5,
    "mutator": 5,
    "predicate": 5,
    "config_value": 6,
    "unknown": 7,
}

# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class ClassifiedSymbol:
    """A symbol with a role assigned by the classifier."""

    name: str
    kind: str  # function, class, interface, type, const, method
    file: str  # relative path from repo root
    line: int  # 1-indexed
    column: int  # 0-indexed
    is_exported: bool = False
    parent: str | None = None  # parent class/trait name if method
    role: Role = "unknown"
    confidence: str = "low"  # "high" | "medium" | "low"
    reasoning: str = ""  # human-readable: why this role was assigned
    ref_count: int = 0  # populated by ranker


@dataclass
class Config:
    """A named configuration value extracted from the code."""

    key: str
    value: str  # stringified
    type: str  # "number" | "string" | "boolean" | "object" | "array"
    line: int


@dataclass
class Comment:
    """A source comment (block or line)."""

    text: str
    start_line: int
    end_line: int


@dataclass
class Anomaly:
    """A detected structural anomaly."""

    severity: str  # "high" | "medium" | "low"
    type: str  # e.g. "asymmetry", "silent_error"
    message: str  # human-readable description
    locations: list[int] = field(default_factory=list)  # line numbers


# ---------------------------------------------------------------------------
# Extracted metadata
# ---------------------------------------------------------------------------


@dataclass
class ExtractedData:
    """File-level metadata extracted from source."""

    summary: str | None = None  # from file header comment
    exports: list[str] = field(default_factory=list)
    imports: dict[str, list[str]] = field(
        default_factory=lambda: {
            "built_in": [],
            "external": [],
            "internal": [],
        }
    )
    configs: list[Config] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline I/O
# ---------------------------------------------------------------------------


@dataclass
class ParserResult:
    """Raw output of the parser phase — before classification."""

    symbols: list[ClassifiedSymbol]  # roles=unknown until classified
    comments: list[Comment]
    source: str
    language: str
    total_lines: int


@dataclass
class OrientationCard:
    """The complete orientation data for a single file."""

    file_path: str
    language: str
    summary: str | None
    symbols: list[ClassifiedSymbol]
    exports: list[str]
    imports: dict[str, list[str]]
    configs: list[Config]
    roles: dict[str, int]  # role → count (typed broadly for mypy compatibility)
    anomalies: list[Anomaly]
    read_order: list[str]  # symbol names, ranked
    total_lines: int
