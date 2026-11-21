"""Dependency rules between layers (DESIGN_GROUP_E.md §2).

    bootstrap ─► api ─► engines ─► services ─► tools (Base… contracts)
                                               core  (shared kernel)

Reads every import in ``app/`` with ``ast`` and fails on the first rule a module breaks.
When this test fails, move the code to the right layer (or inject the dependency
through a constructor) instead of loosening the rule.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Modules allowed to import anything: they assemble the application.
COMPOSITION_ROOTS = {"app.main", "app.bootstrap", "app.tools.factory"}
WEB_FRAMEWORKS = ("fastapi", "starlette")


def _module_name(path: Path) -> str:
    parts = path.relative_to(APP.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
    return found


def _is_tool_contract(target: str) -> bool:
    """``app.tools.<tool>.base`` — the only part of a tool other layers may import."""
    parts = target.split(".")
    return len(parts) == 4 and parts[:2] == ["app", "tools"] and parts[3] == "base"


def _tool_of(module: str) -> str | None:
    parts = module.split(".")
    return parts[2] if len(parts) > 2 and parts[:2] == ["app", "tools"] else None


def _violation(module: str, target: str) -> str | None:
    """Why importing ``target`` from ``module`` breaks a rule, or None when allowed."""
    if module in COMPOSITION_ROOTS:
        return None
    top = target.split(".")[0]
    in_app = top == "app"
    layer = module.split(".")[1] if "." in module else module

    if layer == "core":
        if in_app and not target.startswith("app.core"):
            return "core/ is the shared kernel and may only import app.core"
        return None

    if layer == "tools":
        if top in WEB_FRAMEWORKS:
            return "tools must not depend on the web framework"
        if not in_app or target.startswith("app.core"):
            return None
        own = _tool_of(module)
        if own == "storage":
            # Storage adapters implement the ports a service defines (and use its entities).
            if target.startswith("app.tools.storage") or _is_tool_contract(target):
                return None
            if target.startswith("app.services.") and target.rsplit(".", 1)[-1] in {"ports", "model"}:
                return None
            return "tools/storage may only import core, services/*/ports|model and tool contracts"
        if _tool_of(target) == own or _is_tool_contract(target):
            return None
        return "a tool may only import core, its own package and other tools' base.py"

    if layer in {"services", "engines", "api"}:
        if layer != "api" and top in WEB_FRAMEWORKS:
            return f"{layer}/ must not depend on the web framework"
        if not in_app:
            return None
        if target.startswith("app.tools") and not _is_tool_contract(target):
            return "use the tool's Base… contract (app.tools.<tool>.base); bootstrap picks the implementation"
        if target in COMPOSITION_ROOTS:
            return "only the composition root may import the composition root"
        forbidden = {"services": ("app.engines", "app.api"), "engines": ("app.api",), "api": ()}[layer]
        if target.startswith(forbidden):
            return f"{layer}/ must not import {target.split('.')[1]}/ (dependencies point inward)"
        return None

    return None


def _all_violations() -> list[str]:
    problems = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = _module_name(path)
        for target in _imports(path):
            reason = _violation(module, target)
            if reason:
                problems.append(f"{module} imports {target}: {reason}")
    return problems


def test_layers_only_depend_inward():
    problems = _all_violations()
    assert not problems, "Layer rule violations:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize(
    ("module", "target", "allowed"),
    [
        ("app.services.library.service", "app.tools.llm.base", True),
        ("app.services.library.service", "app.tools.llm.openai_llm", False),
        ("app.services.library.service", "fastapi", False),
        ("app.services.library.service", "app.engines.chat_engine.engine", False),
        ("app.engines.chat_engine.engine", "app.api.dependencies", False),
        ("app.core.config", "app.services.library.model", False),
        ("app.tools.vision.openai_vision", "app.tools.document_parser.base", True),
        ("app.tools.vision.openai_vision", "app.tools.document_parser.docling_loader", False),
        ("app.tools.llm.openai_llm", "app.services.library.model", False),
        ("app.tools.storage.sqlite.library", "app.services.library.ports", True),
        ("app.tools.storage.sqlite.library", "app.services.library.service", False),
        ("app.api.routers.library", "app.tools.vector_store.chroma", False),
        ("app.bootstrap", "app.tools.vector_store.chroma", True),
    ],
)
def test_rule_examples(module, target, allowed):
    assert (_violation(module, target) is None) is allowed
