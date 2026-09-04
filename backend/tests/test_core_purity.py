"""The boundary, enforced by CI rather than by good intentions.

``app.core`` is the deterministic half of the system: every number, legality
verdict, cost and ranking. If it can import a web framework, an ORM or a model
client, then over a hackathon weekend it eventually will, and the claim that
the LLM computes nothing stops being checkable.

So this test walks the import graph of every module under ``app/core`` and
fails if any of them reaches across the line.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parent.parent / "app" / "core"

#: Nothing under app.core may import these, directly or transitively.
FORBIDDEN = {
    "fastapi",
    "starlette",
    "pydantic",
    "sqlalchemy",
    "psycopg",
    "langgraph",
    "langchain",
    "langchain_core",
    "anthropic",
    "openai",
    "apscheduler",
    "httpx",
    "requests",
}

#: The core is also not allowed to reach back into the layers above it.
FORBIDDEN_LOCAL = {"app.api", "app.agent", "app.db", "app.tools", "app.jobs", "app.obs"}


def _modules() -> list[Path]:
    return sorted(p for p in CORE.rglob("*.py") if p.name != "__pycache__")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside app.core
                continue
            if node.module:
                found.add(node.module.split(".")[0])
                found.add(node.module)
    return found


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_core_module_imports_nothing_forbidden(path: Path) -> None:
    imported = _imports(path)
    leaked = (imported & FORBIDDEN) | {m for m in imported if m in FORBIDDEN_LOCAL}
    assert not leaked, (
        f"{path.relative_to(CORE.parent.parent)} imports {sorted(leaked)}. "
        "app.core is the deterministic core: standard library and app.core only."
    )


def test_core_is_importable_without_optional_dependencies() -> None:
    """Loading the world and resolving a disruption must need nothing installed."""
    blocked = {name for name in FORBIDDEN if name in sys.modules}
    # Import the heaviest path in the core and confirm it pulls in nothing new.
    from app.core.candidates import enumerate_cover_for_pairing  # noqa: F401
    from app.core.loader import load_world  # noqa: F401
    from app.core.scenarios import run_event  # noqa: F401

    newly = {name for name in FORBIDDEN if name in sys.modules} - blocked
    assert not newly, f"importing app.core pulled in {sorted(newly)}"


def test_rules_are_all_registered() -> None:
    from app.core.rules.engine import ALL_RULE_IDS, RuleEngine

    engine = RuleEngine()
    registered = {
        engine.qual.rule_id,
        engine.cert.rule_id,
        engine.fdp.rule_id,
        engine.rest.rule_id,
        engine.duty.rule_id,
        engine.flight.rule_id,
    }
    # RULE-BASE-07 is a pre-engine gate in candidates.py, by design.
    assert registered == set(ALL_RULE_IDS) - {"RULE-BASE-07"}
