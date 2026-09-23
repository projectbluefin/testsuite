"""Contract tests for the scenario-timing subsystem.

``tests/shared/timing.py`` writes ``<results_dir>/timings.jsonl``, and both the
"Summarise results" step of ``.github/actions/gnome-e2e/action.yml`` and the
``results-timing`` recipe in ``Justfile`` read it back to report SLA violations.
Nothing else connects the writer to the readers: the writer is Python in
``tests/shared`` and the readers are heredocs inside a composite action and Justfile,
so a renamed key would break SLA reporting silently and every suite would still go green.

These tests make that coupling explicit, and keep the module from re-growing SLA
configuration that no code consumes (see projectbluefin/testsuite#764).
"""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

from tests.shared import timing

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GNOME_E2E_ACTION = REPO_ROOT / ".github" / "actions" / "gnome-e2e" / "action.yml"
JUSTFILE = REPO_ROOT / "Justfile"
TIMING_SOURCE = REPO_ROOT / "tests" / "shared" / "timing.py"

# Keys readers pull off each timings.jsonl entry (via entry.get(...) or subscript entry['...']/v['...']).
ENTRY_READ_RE = re.compile(
    r"""\b(?:entry|v)(?:\.get\(\s*|\[\s*)["']([A-Za-z_][A-Za-z0-9_]*)["']"""
)
ENTRY_GET_RE = ENTRY_READ_RE


def _summarise_step_body():
    try:
        import yaml
    except ImportError:
        yaml = None

    if yaml is not None:
        action = yaml.safe_load(GNOME_E2E_ACTION.read_text(encoding="utf-8"))
        for step in action["runs"]["steps"]:
            if step.get("name") == "Summarise results":
                return step["run"]
    else:
        # Fallback if PyYAML is not installed so the contract test does not skip silently.
        content = GNOME_E2E_ACTION.read_text(encoding="utf-8")
        match = re.search(
            r"- name:\s*Summarise results\b.*?run:\s*\|\n(.*?)(?=\n\s*(?:-\s+name:|\Z))",
            content,
            re.DOTALL,
        )
        if match:
            return match.group(1)

    raise AssertionError(
        f"no 'Summarise results' step in {GNOME_E2E_ACTION.relative_to(REPO_ROOT)}"
    )


def _results_timing_recipe_body():
    content = JUSTFILE.read_text(encoding="utf-8")
    match = re.search(
        r"^results-timing.*?:\n(.*?)(?=\n[a-z0-9_-]+.*?:|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(
            f"no 'results-timing' recipe found in {JUSTFILE.relative_to(REPO_ROOT)}"
        )
    return match.group(1)


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


def _assert_reader_keys_are_written(tmp_path, source_path, body):
    consumed = set(ENTRY_READ_RE.findall(body))
    assert consumed, f"found no entry reads in {source_path}; did the reader change shape?"

    produced = set(_written_entry(tmp_path))
    missing = sorted(consumed - produced)
    assert not missing, (
        f"{source_path.relative_to(REPO_ROOT)} reads {missing} from "
        "timings.jsonl, but tests/shared/timing.py:record_end does not write "
        "those keys. SLA reporting would silently stop."
    )


def test_summariser_reads_only_keys_record_end_writes(tmp_path):
    """Every key the gnome-e2e summariser pulls off an entry must be written."""
    _assert_reader_keys_are_written(tmp_path, GNOME_E2E_ACTION, _summarise_step_body())


def test_justfile_results_timing_reads_only_keys_record_end_writes(tmp_path):
    """Every key the Justfile results-timing recipe pulls off an entry must be written."""
    _assert_reader_keys_are_written(tmp_path, JUSTFILE, _results_timing_recipe_body())


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
    } | {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and not node.target.id.startswith("_")
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


def test_unconsumed_annotated_constant_is_detected():
    """Annotated constants (ast.AnnAssign) must also be checked for usage."""
    snippet = "UNCONSUMED: dict = {}\n_PRIVATE: int = 1\nCONSUMED: str = 'ok'\nprint(CONSUMED)\n"
    tree = ast.parse(snippet)
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and not target.id.startswith("_")
    } | {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and not node.target.id.startswith("_")
    }
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    unconsumed = sorted(assigned - loaded)
    assert unconsumed == ["UNCONSUMED"]


def test_summarise_step_body_regex_fallback_matches():
    """Ensure regex fallback extracts the same entry keys as YAML parsing."""
    content = GNOME_E2E_ACTION.read_text(encoding="utf-8")
    match = re.search(
        r"- name:\s*Summarise results\b.*?run:\s*\|\n(.*?)(?=\n\s*(?:-\s+name:|\Z))",
        content,
        re.DOTALL,
    )
    assert match is not None
    fallback_body = match.group(1)
    keys_fallback = set(ENTRY_GET_RE.findall(fallback_body))
    keys_full = set(ENTRY_GET_RE.findall(_summarise_step_body()))
    assert keys_fallback == keys_full


def test_entry_reads_include_subscript_access():
    """Subscript access like v['key'] or entry['key'] must be extracted."""
    snippet = "print(entry.get('foo'))\nprint(v['bar'])\nprint(entry['baz'])\n"
    keys = set(ENTRY_READ_RE.findall(snippet))
    assert keys == {"foo", "bar", "baz"}

