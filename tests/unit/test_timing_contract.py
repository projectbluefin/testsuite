"""Contract tests for the scenario-timing subsystem.

``tests/shared/timing.py`` writes ``<results_dir>/timings.jsonl`` and the
"Summarise results" step of ``.github/actions/gnome-e2e/action.yml`` reads it back
to report SLA violations. Nothing else connects the two: the writer is Python in
``tests/shared`` and the reader is a heredoc inside a composite action, so a renamed
key would break SLA reporting silently and every suite would still go green.

These tests make that coupling explicit, and keep the module from re-growing SLA
configuration that no code consumes (see projectbluefin/testsuite#764).
"""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.shared import timing

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GNOME_E2E_ACTION = REPO_ROOT / ".github" / "actions" / "gnome-e2e" / "action.yml"
TIMING_SOURCE = REPO_ROOT / "tests" / "shared" / "timing.py"

# Keys the summariser reads off each timings.jsonl entry.
ENTRY_GET_RE = re.compile(r"""entry\.get\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")


def _summarise_step_body():
    yaml = pytest.importorskip("yaml")
    action = yaml.safe_load(GNOME_E2E_ACTION.read_text(encoding="utf-8"))
    for step in action["runs"]["steps"]:
        if step.get("name") == "Summarise results":
            return step["run"]
    raise AssertionError(
        f"no 'Summarise results' step in {GNOME_E2E_ACTION.relative_to(REPO_ROOT)}"
    )


def _written_entry(tmp_path, tags=None):
    context = SimpleNamespace(
        config=SimpleNamespace(userdata={"results_dir": str(tmp_path)}),
        _timing_start=0.0,
    )
    tags = tags or []
    scenario = SimpleNamespace(
        name="Launch app",
        status=SimpleNamespace(name="passed"),
        feature=SimpleNamespace(name="Smoke"),
        tags=tags,
        effective_tags=tags,
    )
    timing.record_end(context, scenario)
    line = (tmp_path / "timings.jsonl").read_text(encoding="utf-8").strip()
    return json.loads(line)


def test_summariser_reads_only_keys_record_end_writes(tmp_path):
    """Every key the gnome-e2e summariser pulls off an entry must be written."""
    consumed = set(ENTRY_GET_RE.findall(_summarise_step_body()))
    assert consumed, "found no entry.get(...) reads; did the summariser change shape?"

    produced = set(_written_entry(tmp_path))
    missing = sorted(consumed - produced)
    assert not missing, (
        f"{GNOME_E2E_ACTION.relative_to(REPO_ROOT)} reads {missing} from "
        "timings.jsonl, but tests/shared/timing.py:record_end does not write "
        "those keys. SLA reporting would silently stop."
    )


def test_sla_violation_is_reported_for_a_tagged_overrun(tmp_path):
    """The flag the summariser filters on must actually be set on an overrun."""
    entry = _written_entry(tmp_path, tags=["sla_0s"])

    assert entry["sla_s"] == 0
    assert entry["sla_violated"] is True
    assert entry["status"] == "passed"


def test_untagged_scenario_has_no_sla_and_never_violates(tmp_path):
    """Without an @sla_<n>s tag there is no threshold — and no default table."""
    entry = _written_entry(tmp_path)

    assert entry["sla_s"] is None
    assert entry["sla_violated"] is False


def test_module_constants_are_consumed_by_the_module():
    """A config constant nothing reads is a promise the code does not keep.

    ``DEFAULT_SLA`` and ``SLA_STRICT`` were both defined and never referenced, so
    ``TIMING_SLA_STRICT=1`` looked like an SLA-gating switch while being a no-op.
    Any new module-level constant has to be used by ``timing.py`` itself.
    """
    tree = ast.parse(TIMING_SOURCE.read_text(encoding="utf-8"))

    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and not target.id.startswith("_")
    }
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    unconsumed = sorted(assigned - loaded)
    assert not unconsumed, (
        f"tests/shared/timing.py defines {unconsumed} but never reads them. "
        "Wire the constant into the code that acts on it, or drop it — do not "
        "ship configuration that cannot take effect."
    )
