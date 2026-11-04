"""Unit tests for the v1 gate's baseline comparison (scripts/v1_gate_compare.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.v1_gate_compare import artifact_suffix, compare, summary_markdown

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "v1_gate_compare.py"

DIGEST = "sha256:" + "ab" * 32
CANDIDATE = f"ghcr.io/projectbluefin/dakota:testing@{DIGEST}"
BASELINE = f"ghcr.io/projectbluefin/dakota@{DIGEST}"


def write_suite(root: Path, image: str, suite: str, conclusion: str, scenarios=None):
    """Write the two artifacts e2e.yml uploads for one suite job."""
    suffix = artifact_suffix(image)
    meta = root / f"e2e-metadata-{suffix}-{suite}"
    meta.mkdir(parents=True)
    (meta / "e2e-metadata.json").write_text(
        json.dumps({"image": image, "suite": suite, "conclusion": conclusion})
    )
    if scenarios is None:
        return
    results = root / f"e2e-results-{suffix}-{suite}"
    results.mkdir(parents=True)
    elements = [
        {"type": "scenario", "name": n, "status": s} for n, s in scenarios.items()
    ]
    (results / "results.json").write_text(
        json.dumps([{"name": "Feature", "elements": elements}])
    )


def test_suffix_matches_e2e_artifact_names():
    assert artifact_suffix(
        CANDIDATE
    ) == "ghcr.io-projectbluefin-dakota-testing-" + DIGEST.replace(":", "-")
    assert artifact_suffix(CANDIDATE) != artifact_suffix(BASELINE)


def test_failures_already_at_v1_let_v1_move(tmp_path):
    write_suite(
        tmp_path, CANDIDATE, "smoke-a", "failure", {"A": "failed", "B": "passed"}
    )
    write_suite(
        tmp_path, BASELINE, "smoke-a", "failure", {"A": "failed", "B": "passed"}
    )
    write_suite(tmp_path, CANDIDATE, "common-a", "success", {"C": "passed"})
    result = compare(tmp_path, CANDIDATE, BASELINE)
    assert result["verdict"] == "move"
    assert result["preexisting"] == {"smoke-a": ["Feature :: A"]}


def test_new_failure_holds_v1(tmp_path):
    write_suite(
        tmp_path, CANDIDATE, "smoke-a", "failure", {"A": "failed", "B": "failed"}
    )
    write_suite(
        tmp_path, BASELINE, "smoke-a", "failure", {"A": "failed", "B": "passed"}
    )
    result = compare(tmp_path, CANDIDATE, BASELINE)
    assert result["verdict"] == "hold"
    assert "Feature :: B" in result["problems"][0]


def test_failed_job_without_failing_scenario_holds_v1(tmp_path):
    write_suite(tmp_path, CANDIDATE, "smoke-b", "failure", {"A": "skipped"})
    write_suite(tmp_path, BASELINE, "smoke-b", "failure", {"A": "skipped"})
    assert compare(tmp_path, CANDIDATE, BASELINE)["verdict"] == "hold"


def test_missing_candidate_results_hold_v1(tmp_path):
    write_suite(tmp_path, CANDIDATE, "smoke-b", "failure", None)
    write_suite(tmp_path, BASELINE, "smoke-b", "failure", {"A": "failed"})
    assert compare(tmp_path, CANDIDATE, BASELINE)["verdict"] == "hold"


def test_missing_baseline_holds_v1(tmp_path):
    write_suite(tmp_path, CANDIDATE, "smoke-a", "failure", {"A": "failed"})
    result = compare(tmp_path, CANDIDATE, BASELINE)
    assert result["verdict"] == "hold"
    assert "no result at v1" in result["problems"][0]


def test_no_candidate_artifacts_hold_v1(tmp_path):
    assert compare(tmp_path, CANDIDATE, BASELINE)["verdict"] == "hold"


def test_summary_lists_preexisting_and_new(tmp_path):
    write_suite(tmp_path, CANDIDATE, "smoke-a", "failure", {"A": "failed"})
    write_suite(tmp_path, BASELINE, "smoke-a", "failure", {"A": "failed"})
    text = summary_markdown(compare(tmp_path, CANDIDATE, BASELINE))
    assert "already present at v1" in text
    assert "Feature :: A" in text


def test_cli_prints_verdict_and_writes_summary(tmp_path):
    write_suite(tmp_path, CANDIDATE, "smoke-a", "failure", {"A": "failed"})
    write_suite(tmp_path, BASELINE, "smoke-a", "failure", {"A": "failed"})
    summary = tmp_path / "summary.md"
    out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(tmp_path),
            CANDIDATE,
            BASELINE,
            "--summary",
            str(summary),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == "verdict=move"
    assert summary.read_text().startswith("### Candidate failures compared with v1")
