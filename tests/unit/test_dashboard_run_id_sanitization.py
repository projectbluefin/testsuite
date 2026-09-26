"""Unit tests for run_id sanitization in the dashboard data scripts.

run_id reaches convert_behave.py from an OCI manifest annotation pulled off
GHCR (publish-to-pages.yml) and reaches compile_data.py from the ``id`` field
of raw run JSON files. Both scripts use it as an output filename component,
so traversal payloads must never survive into the write path
(projectbluefin/testsuite#891).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "dashboard" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


convert_behave = _load("convert_behave")
compile_data = _load("compile_data")

TRAVERSAL_IDS = [
    "../../../old-gh-pages/pwn",
    "..",
    "../x",
    "/etc/passwd",
    "a/b",
    "a\\b",
    ".hidden",
    "",
    "run..id/../x",
]

SAFE_IDS = ["12345", "run_20260926_0800_bluefin-testing", "Run-1.2_a"]


class TestSanitizeRunId:
    def test_rejects_traversal_payloads(self):
        for bad in TRAVERSAL_IDS:
            assert convert_behave.sanitize_run_id(bad) == "", bad
            assert compile_data.sanitize_run_id(bad) == "", bad

    def test_accepts_safe_ids(self):
        for good in SAFE_IDS:
            assert convert_behave.sanitize_run_id(good) == good
            assert compile_data.sanitize_run_id(good) == good


def _behave_fixture():
    return [
        {
            "name": "feature",
            "elements": [
                {
                    "type": "scenario",
                    "name": "scenario",
                    "status": "passed",
                    "steps": [
                        {
                            "keyword": "Given",
                            "name": "a step",
                            "result": {"status": "passed", "duration": 0.1},
                        }
                    ],
                }
            ],
        }
    ]


class TestConvertBehave:
    def test_hostile_run_id_falls_back_to_generated_id(self, tmp_path):
        src = tmp_path / "results.json"
        src.write_text(json.dumps(_behave_fixture()))
        run_data = convert_behave.convert_behave_json(
            str(src),
            run_id="../../../old-gh-pages/pwn",
            caller_repo="projectbluefin/testsuite",
            slug="bluefin-testing",
            suite="smoke",
            timestamp="2026-09-26T08:00:00Z",
        )
        assert "/" not in run_data["id"]
        assert ".." not in run_data["id"]
        assert run_data["id"].startswith("run_")

    def test_safe_run_id_is_preserved(self, tmp_path):
        src = tmp_path / "results.json"
        src.write_text(json.dumps(_behave_fixture()))
        run_data = convert_behave.convert_behave_json(
            str(src),
            run_id="18000000001",
            caller_repo="projectbluefin/testsuite",
            slug="bluefin-testing",
            suite="smoke",
            timestamp="2026-09-26T08:00:00Z",
        )
        assert run_data["id"] == "18000000001"


class TestCompileData:
    def test_hostile_id_field_cannot_steer_write_path(self, tmp_path, monkeypatch):
        raw_dir = tmp_path / "runs"
        out_dir = tmp_path / "compiled"
        dist_dir = tmp_path / "dist"
        raw_dir.mkdir()
        outside = tmp_path / "outside"

        run = {
            "id": f"../outside/{'pwn'}",
            "timestamp": "2026-09-26T08:00:00Z",
            "stream": "testing",
            "flavor": "bluefin",
            "suite": "smoke",
            "summary": {
                "status": "passed",
                "total_tests": 1,
                "passed_tests": 1,
                "failed_tests": 0,
                "skipped_tests": 0,
                "total_duration_ms": 100,
            },
            "tests": [],
        }
        (raw_dir / "run-evil.json").write_text(json.dumps(run))

        monkeypatch.setattr(compile_data, "RAW_DATA_DIR", str(raw_dir))
        monkeypatch.setattr(compile_data, "OUTPUT_DIR", str(out_dir))
        monkeypatch.setattr(compile_data, "RUNS_DIST_DIR", str(dist_dir))

        compile_data.compile_dashboard_data()

        assert not outside.exists()
        # Falls back to the glob-constrained source filename stem.
        assert (dist_dir / "run-evil.json").exists()
        index = json.loads((out_dir / "summary-index.json").read_text())
        assert all("/" not in r["id"] and ".." not in r["id"] for r in index["runs"])
