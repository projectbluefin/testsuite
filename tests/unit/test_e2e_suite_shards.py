"""Contract between e2e.yml's suite expansion and its shard resolver.

``.github/workflows/e2e.yml`` names a suite in two places that must agree:

* the ``matrix`` job's "Resolve suites" step expands a caller's ``suites``
  input (``smoke`` -> ``smoke-a``/``smoke-b``/``smoke-firefox``, ...) into
  matrix entries;
* the ``e2e`` job's "Resolve suite shard" step maps each matrix entry back to
  a physical ``tests/<suite>/features`` directory and the feature files that
  shard runs.

If the two drift (a suite added to one set but not the other, a renamed shard
label, a new stateful feature split out on one side only), shards resolve to a
directory that does not exist or silently drop feature files. Both programs
are inline Python in the workflow, so these tests execute the exact text the
workflow ships rather than a copy of it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "e2e.yml"

EXPAND_RE = re.compile(r'python3 -c "\n(?P<code>.*?)\n" "\$\{\{ inputs\.suites \}\}"', re.S)
RESOLVE_RE = re.compile(r"python3 - <<'PY'\n(?P<code>.*?)\nPY\n", re.S)


def _step(job: str, step_id: str) -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"][job]["steps"]:
        if step.get("id") == step_id:
            return step["run"]
    raise AssertionError(f"e2e.yml: job {job!r} has no step with id {step_id!r}")


def _program(job: str, step_id: str, pattern: re.Pattern[str]) -> str:
    run = _step(job, step_id)
    match = pattern.search(run)
    assert match, f"e2e.yml: cannot locate the inline Python in {job}.{step_id}"
    return match.group("code")


@pytest.fixture(scope="module")
def expand_program() -> str:
    return _program("matrix", "resolve", EXPAND_RE)


@pytest.fixture(scope="module")
def resolve_program() -> str:
    return _program("e2e", "shard", RESOLVE_RE)


def _expand(program: str, suites: str) -> list[str]:
    out = subprocess.run(
        [sys.executable, "-c", program, suites],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def _resolve(program: str, suite: str, tmp_path: Path) -> dict[str, str]:
    output = tmp_path / f"github_output_{suite}"
    output.write_text("", encoding="utf-8")
    env = {**os.environ, "SUITE": suite, "GITHUB_OUTPUT": str(output)}
    subprocess.run(
        [sys.executable, "-"],
        input=program,
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    values = {}
    for line in output.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    return values


def _suites() -> list[str]:
    return sorted(
        path.parent.name
        for path in (REPO_ROOT / "tests").glob("*/features")
        if any(path.glob("*.feature"))
    )


# Known drift: kde-smoke has one feature file, so kde-smoke-b resolves empty
# and the shard step exits non-zero (projectbluefin/testsuite#989). Strict, so
# this flips to a failure the moment e2e.yml stops sharding kde-smoke.
KNOWN_DRIFT = {
    "kde-smoke": "e2e.yml shards kde-smoke but it has one feature file (#989)",
}


def _suite_params() -> list:
    return [
        pytest.param(
            suite,
            marks=pytest.mark.xfail(reason=KNOWN_DRIFT[suite], strict=True),
        )
        if suite in KNOWN_DRIFT
        else suite
        for suite in _suites()
    ]


def _features(suite: str) -> set[str]:
    return {
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "tests" / suite / "features").glob("*.feature")
    }


def test_expansion_trims_and_drops_empty_entries(expand_program):
    assert _expand(expand_program, " lifecycle , ,security") == ["lifecycle", "security"]


@pytest.mark.parametrize("suite", _suite_params())
def test_every_expanded_shard_resolves_to_the_suite_it_came_from(
    suite, expand_program, resolve_program, tmp_path
):
    shards = _expand(expand_program, suite)
    assert shards, f"{suite} expanded to no matrix entries"
    assert len(shards) == len(set(shards)), f"{suite} expanded to duplicate shards {shards}"

    covered: list[str] = []
    for shard in shards:
        resolved = _resolve(resolve_program, shard, tmp_path)
        assert resolved["suite_dir"] == suite, (
            f"matrix entry {shard!r} (from suite {suite!r}) resolved to "
            f"tests/{resolved['suite_dir']}/features — expansion and resolver "
            "in e2e.yml disagree on which suites are sharded"
        )
        assert resolved["screenshot_suite"] == suite, (
            f"{shard!r} would publish screenshots under "
            f"{resolved['screenshot_suite']!r}, not the parent suite {suite!r}"
        )
        args = resolved["feature_args"].split()
        if not args:
            assert shards == [suite], (
                f"{shard!r} runs the whole of tests/{suite}/features while "
                f"sibling shards {shards} also run part of it"
            )
            args = sorted(_features(suite))
        for path in args:
            assert (REPO_ROOT / path).is_file(), f"{shard!r} names missing feature {path}"
        covered.extend(args)

    assert len(covered) == len(set(covered)), (
        f"{suite} shards {shards} run some feature files more than once: "
        f"{sorted(p for p in set(covered) if covered.count(p) > 1)}"
    )
    assert set(covered) == _features(suite), (
        f"{suite} shards {shards} skip feature files: "
        f"{sorted(_features(suite) - set(covered))}"
    )


def test_sharded_suites_actually_shard(expand_program):
    # Guards the expansion side against silently collapsing to one job: the
    # suites the docs promise are split must still produce several entries.
    for suite in ("smoke", "common", "kde-smoke"):
        assert len(_expand(expand_program, suite)) > 1, f"{suite} is no longer sharded"
