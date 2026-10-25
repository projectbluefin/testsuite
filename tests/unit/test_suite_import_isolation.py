"""Guard: suite code may import only its own package and tests.shared.

CI copies just tests/<suite> and tests/shared into the VM before running a GUI
suite (.github/workflows/e2e.yml and .github/actions/gnome-e2e/action.yml). An
import of another suite's package resolves locally but fails in the VM, which
leaves every step of the importing suite undefined. Helpers needed by more than
one suite belong in tests/shared.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

TESTS_ROOT = pathlib.Path(__file__).resolve().parents[1]
NOT_SUITES = {"unit", "shared", "__pycache__"}

SUITES = sorted(
    p.name for p in TESTS_ROOT.iterdir() if p.is_dir() and p.name not in NOT_SUITES
)


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def _cross_suite_imports(suite: str) -> list[str]:
    allowed = {suite, "shared"}
    offenders = []
    for path in sorted((TESTS_ROOT / suite).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, module in _imported_modules(tree):
            parts = module.split(".")
            if parts[0] == "tests" and len(parts) > 1 and parts[1] not in allowed:
                rel = path.relative_to(TESTS_ROOT.parent)
                offenders.append(f"{rel}:{lineno} imports {module}")
    return offenders


def test_suites_are_discovered():
    assert {"smoke", "software", "common"} <= set(SUITES)


@pytest.mark.parametrize("suite", SUITES)
def test_suite_imports_only_itself_and_shared(suite):
    offenders = _cross_suite_imports(suite)
    assert not offenders, (
        "Suite code imports another suite's package, which is not copied into "
        "the VM; move the helper into tests/shared: " + "; ".join(offenders)
    )


def test_guard_flags_a_cross_suite_import(tmp_path, monkeypatch):
    suite_dir = tmp_path / "tests" / "alpha" / "features" / "steps"
    suite_dir.mkdir(parents=True)
    (suite_dir / "steps.py").write_text(
        "from tests.shared.ssh_config import ssh_argv\n"
        "from tests.alpha.features.steps import helpers\n"
        "import tests.beta.features.steps.helpers\n"
        "from tests.gamma import x\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "TESTS_ROOT", tmp_path / "tests")

    offenders = _cross_suite_imports("alpha")

    assert offenders == [
        "tests/alpha/features/steps/steps.py:3 imports tests.beta.features.steps.helpers",
        "tests/alpha/features/steps/steps.py:4 imports tests.gamma",
    ]
