"""Contract tests for the per-suite behave ``environment.py`` modules.

Every behave suite under ``tests/<suite>/features/`` ships its own
``environment.py``. The cross-cutting hooks they are all expected to honour are
copy-pasted rather than inherited from a shared base, so nothing currently
detects a suite that silently drops one.

``tests/shared/quarantine.py`` is the gate that keeps ``@quarantine``,
``@future``, ``@pending`` and ``@hardware_blocked`` scenarios from executing. It
has thorough unit coverage of its own logic in ``tests/unit/test_quarantine.py``,
but that coverage says nothing about whether a suite calls it. A suite that omits
the call runs its known-failing scenarios for real, which surfaces much later as a
red E2E gate that reads like a product regression.

These tests parse each ``environment.py`` with ``ast`` — no imports, no behave
runtime, no VM — and assert the wiring is present.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.shared.results_dir import DEFAULT_RESULTS_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

QUARANTINE_HELPER = "skip_quarantine"
QUARANTINE_MODULE = "tests.shared.quarantine"

FIRST_VALUE_HELPER = "_first_value"
FIRST_VALUE_MODULE = "tests.shared.ssh_config"


def _environment_modules() -> list[Path]:
    return sorted(TESTS_ROOT.glob("*/features/environment.py"))


def _suite_name(path: Path) -> str:
    return path.parent.parent.name


ENVIRONMENT_MODULES = _environment_modules()
ENVIRONMENT_IDS = [_suite_name(path) for path in ENVIRONMENT_MODULES]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(node: ast.AST) -> set[str]:
    """Return every callable name invoked anywhere inside ``node``."""
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _imports_quarantine_helper(node: ast.AST) -> bool:
    """True when ``skip_quarantine`` is imported from the shared module."""
    for child in ast.walk(node):
        if not isinstance(child, ast.ImportFrom):
            continue
        if child.module != QUARANTINE_MODULE:
            continue
        if any(alias.name == QUARANTINE_HELPER for alias in child.names):
            return True
    return False


def _imports_first_value_helper(node: ast.AST) -> bool:
    """True when ``_first_value`` is imported from the shared module."""
    for child in ast.walk(node):
        if not isinstance(child, ast.ImportFrom):
            continue
        if child.module != FIRST_VALUE_MODULE:
            continue
        if any(alias.name == FIRST_VALUE_HELPER for alias in child.names):
            return True
    return False


def test_every_suite_has_an_environment_module() -> None:
    """Guard the discovery glob itself.

    If this ever collects nothing the parametrised tests below would silently
    pass while asserting nothing at all.
    """
    assert ENVIRONMENT_MODULES, (
        f"no tests/*/features/environment.py found under {TESTS_ROOT} — "
        "the suite discovery glob is broken, so the contract below is vacuous"
    )


@pytest.mark.parametrize("path", ENVIRONMENT_MODULES, ids=ENVIRONMENT_IDS)
def test_environment_defines_before_scenario(path: Path) -> None:
    before_scenario = _find_function(_parse(path), "before_scenario")
    assert before_scenario is not None, (
        f"{path.relative_to(REPO_ROOT)} defines no before_scenario hook, so the "
        "suite has nowhere to apply the shared quarantine gate"
    )


@pytest.mark.parametrize("path", ENVIRONMENT_MODULES, ids=ENVIRONMENT_IDS)
def test_before_scenario_applies_quarantine_gate(path: Path) -> None:
    """Each suite must call ``skip_quarantine`` from its ``before_scenario``.

    Without it, ``@quarantine`` / ``@future`` / ``@pending`` /
    ``@hardware_blocked`` scenarios execute for real in that suite.
    """
    relative = path.relative_to(REPO_ROOT)
    before_scenario = _find_function(_parse(path), "before_scenario")
    assert before_scenario is not None, f"{relative} defines no before_scenario hook"

    assert QUARANTINE_HELPER in _called_names(before_scenario), (
        f"{relative}: before_scenario never calls {QUARANTINE_HELPER}(). Every "
        "suite must apply the shared gate from tests/shared/quarantine.py, "
        "otherwise its @quarantine, @future, @pending and @hardware_blocked "
        "scenarios run instead of being skipped."
    )


@pytest.mark.parametrize("path", ENVIRONMENT_MODULES, ids=ENVIRONMENT_IDS)
def test_quarantine_helper_comes_from_the_shared_module(path: Path) -> None:
    """The gate must be the shared implementation, not a suite-local redefinition."""
    relative = path.relative_to(REPO_ROOT)
    tree = _parse(path)

    local_definition = _find_function(tree, QUARANTINE_HELPER)
    assert local_definition is None, (
        f"{relative} defines its own {QUARANTINE_HELPER}(); it must import the "
        f"shared implementation from {QUARANTINE_MODULE} so the skip-tag "
        "precedence stays defined in exactly one place"
    )

    assert _imports_quarantine_helper(tree), (
        f"{relative} does not import {QUARANTINE_HELPER} from {QUARANTINE_MODULE}"
    )


@pytest.mark.parametrize("path", ENVIRONMENT_MODULES, ids=ENVIRONMENT_IDS)
def test_no_suite_redefines_first_value(path: Path) -> None:
    """``_first_value`` must have exactly one implementation, in ssh_config.

    It used to be copy-pasted verbatim into ``tests/common`` and
    ``tests/kde-smoke`` (and a third time in ``tests/shared/ssh_config.py``
    itself). A suite-local redefinition can silently drift from the shared
    priority order that ``resolve_ssh_details`` documents, so any suite that
    uses the helper must import the shared implementation instead of
    re-declaring it.
    """
    relative = path.relative_to(REPO_ROOT)
    tree = _parse(path)

    local_definition = _find_function(tree, FIRST_VALUE_HELPER)
    assert local_definition is None, (
        f"{relative} defines its own {FIRST_VALUE_HELPER}(); it must import the "
        f"shared implementation from {FIRST_VALUE_MODULE} instead of "
        "re-declaring it locally"
    )

    if FIRST_VALUE_HELPER in _called_names(tree):
        assert _imports_first_value_helper(tree), (
            f"{relative} calls {FIRST_VALUE_HELPER}() but does not import it "
            f"from {FIRST_VALUE_MODULE}"
        )
ATSPI_TREE_ARTIFACT = "atspi_tree.txt"
RESOLVE_RESULTS_DIR_CALL = "resolve_results_dir"


def _after_all_dumps_atspi_tree(path: Path) -> bool:
    """True when ``path``'s after_all hook writes the gnome-shell AT-SPI tree.

    Only some suites dump the tree; the guard below must run only for those so
    it does not falsely flag suites that never write the artifact. The
    artifact name appears as a string literal inside ``os.path.join`` /
    ``os.path.exists`` rather than as a call, so this scans the after_all
    source instead of its called names.
    """
    after_all = _find_function(_parse(path), "after_all")
    if after_all is None:
        return False
    segment = ast.get_source_segment(path.read_text(encoding="utf-8"), after_all) or ""
    return ATSPI_TREE_ARTIFACT in segment


_ATSPI_TREE_MODULES = [
    p for p in ENVIRONMENT_MODULES if _after_all_dumps_atspi_tree(p)
]


@pytest.mark.parametrize(
    "path",
    _ATSPI_TREE_MODULES,
    ids=[_suite_name(p) for p in _ATSPI_TREE_MODULES],
)
def test_atspi_tree_dump_routes_through_resolve_results_dir(path: Path) -> None:
    """Every after_all that dumps the AT-SPI tree must resolve its directory
    through the shared ``resolve_results_dir`` helper.

    PR #825 routed the smoke and vanilla-gnome dump sites through the helper,
    replacing the hardcoded ``/tmp/results``. These two sites are exercised by
    no unit test (they need a live behave/VM run), and the dump body is wrapped
    in ``except Exception: pass`` — so a later edit that hardcodes the path
    again, or forgets to route through the helper, fails silently as a missing
    artifact rather than a red test. This cheap AST guard, run in the same no-VM
    suite, pins the shared-resolver contract for both sites.
    """
    relative = path.relative_to(REPO_ROOT)
    tree = _parse(path)
    after_all = _find_function(tree, "after_all")
    assert after_all is not None, f"{relative} defines no after_all hook"

    assert RESOLVE_RESULTS_DIR_CALL in _called_names(after_all), (
        f"{relative}: after_all never calls {RESOLVE_RESULTS_DIR_CALL}(). The "
        "AT-SPI tree dump must route through the shared results-directory "
        "helper so a redirected run keeps its artifacts together."
    )

    segment = ast.get_source_segment(path.read_text(encoding="utf-8"), after_all) or ""
    assert DEFAULT_RESULTS_DIR not in segment, (
        f"{relative}: after_all still references the hardcoded "
        f"{DEFAULT_RESULTS_DIR!r}. All AT-SPI dump sites must go through "
        f"{RESOLVE_RESULTS_DIR_CALL}() so a redirected run does not split the "
        "dump across two directories."
    )
