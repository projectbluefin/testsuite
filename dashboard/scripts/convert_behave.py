#!/usr/bin/env python3
import os
import json
import re
import sys
from pathlib import Path
from datetime import datetime

# run_id is used as an output filename component. It arrives from an OCI
# manifest annotation (io.github.projectbluefin.run_id) pulled off GHCR, so
# treat it as untrusted: allow only a conservative character set and reject
# anything that could traverse directories ("../", "/", "\\", leading dots).
SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sanitize_run_id(run_id):
    """Return run_id if it is safe to use as a filename component, else ''."""
    if run_id and SAFE_RUN_ID_RE.match(run_id) and ".." not in run_id:
        return run_id
    return ""

STATUS_MAP = {
    "passed": "passed",
    "failed": "failed",
    "error": "failed",
    "skipped": "skipped",
}

def normalize_status(status):
    if not status:
        return "failed"
    return STATUS_MAP.get(str(status).strip().lower(), "failed")

def convert_behave_json(behave_json_path, *, run_id, caller_repo, slug, suite, timestamp):
    try:
        with open(behave_json_path, 'r') as f:
            features = json.load(f)
    except Exception as e:
        print(f"Error loading behave JSON {behave_json_path}: {e}")
        return None

    # Parse slug into flavor and stream
    # e.g. "bluefin-testing" -> flavor "bluefin", stream "testing"
    parts = slug.split('-')
    if len(parts) >= 2:
        flavor = "-".join(parts[:-1])
        stream = parts[-1]
    else:
        flavor = slug
        stream = "testing"

    tests = []
    total_duration_ms = 0
    passed_tests = 0
    failed_tests = 0
    skipped_tests = 0

    for feature in features:
        feature_name = feature.get("name", "unknown_feature")
        for element in feature.get("elements", []):
            if element.get("type") == "background":
                continue

            scenario_name = element.get("name", "unknown_scenario")
            status = normalize_status(element.get("status", "failed"))
            
            # Sum durations of steps
            duration_ms = 0
            error_message = None
            step_logs_list = []

            for step in element.get("steps", []):
                step_name = f"{step.get('keyword', '')} {step.get('name', '')}".strip()
                step_result = step.get("result", {})
                step_status = normalize_status(step_result.get("status", "skipped"))
                
                # Get step duration (behave outputs float seconds)
                step_duration_s = step_result.get("duration", 0.0)
                duration_ms += int(step_duration_s * 1000)

                step_logs_list.append(f"[{step_status.upper()}] {step_name}")
                
                # Check for error details
                err_msg = step_result.get("error_message")
                if err_msg:
                    error_message = err_msg
                    step_logs_list.append(f"\u001b[1;31m[ERROR] {err_msg}\u001b[0m")
                
                # Capture standard outputs if present
                std_out = step.get("text") or step.get("table")
                if std_out:
                    step_logs_list.append(f"Output:\n{std_out}")

            # Calculate metrics
            if status == "passed":
                passed_tests += 1
            elif status == "failed":
                failed_tests += 1
            else:
                skipped_tests += 1

            total_duration_ms += duration_ms

            tests.append({
                "name": f"{feature_name} > {scenario_name}",
                "status": "passed" if status == "passed" else "failed",
                "duration_ms": duration_ms,
                "error_message": error_message,
                "logs": "\n".join(step_logs_list)
            })

    total_tests = passed_tests + failed_tests + skipped_tests
    overall_status = "success" if failed_tests == 0 and total_tests > 0 else "failed"

    # Assemble standard Dashboard run-ID.json payload
    return {
        "id": sanitize_run_id(run_id) or f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M')}_{slug}",
        "timestamp": timestamp or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stream": stream,
        "flavor": flavor,
        "suite": suite,
        "version": "40.latest", # Roll default
        "git_commit": {
            "sha": os.environ.get("GITHUB_SHA", "unknown"),
            "message": f"E2E test run compiled via {caller_repo or 'testsuite'}",
            "author": "KubeVirt Lab",
            "repo_url": f"https://github.com/{caller_repo or 'projectbluefin/testsuite'}"
        },
        "environment": {
            "runner_id": "homelab-kubevirt-worker",
            "kubevirt_version": "v1.2.0",
            "k3s_version": "v1.29.3",
            "hardware_profile": {
                "cpu_cores": 8,
                "memory_gb": 32,
                "gpu": "None",
                "disk_type": "NVMe"
            }
        },
        "summary": {
            "status": overall_status,
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "skipped_tests": skipped_tests,
            "total_duration_ms": total_duration_ms
        },
        "tests": tests
    }

def main():
    if len(sys.argv) < 7:
        print("Usage: convert_behave.py <behave_json> <run_id> <caller_repo> <slug> <suite> <timestamp> <output_dir>")
        sys.exit(1)

    behave_json = sys.argv[1]
    run_id = sys.argv[2]
    caller_repo = sys.argv[3]
    slug = sys.argv[4]
    suite = sys.argv[5]
    timestamp = sys.argv[6]
    output_dir = sys.argv[7]

    os.makedirs(output_dir, exist_ok=True)
    
    run_data = convert_behave_json(
        behave_json,
        run_id=run_id,
        caller_repo=caller_repo,
        slug=slug,
        suite=suite,
        timestamp=timestamp
    )

    if run_data:
        out_path = os.path.join(output_dir, f"{run_data['id']}.json")
        with open(out_path, 'w') as f:
            json.dump(run_data, f, indent=2)
        print(f"Successfully converted Behave logs to dashboard run asset: {out_path}")
    else:
        print("Failed to convert Behave JSON.")
        sys.exit(1)

if __name__ == "__main__":
    main()