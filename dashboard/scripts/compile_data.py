#!/usr/bin/env python3
import os
import json
import glob
import re
from datetime import datetime

from pathlib import Path

# Run ids are re-used as output filename components; the raw run JSON they come
# from originates outside this repo (GHCR artifacts), so constrain them to a
# safe character set to prevent path traversal on write.
SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sanitize_run_id(run_id):
    """Return run_id if it is safe to use as a filename component, else ''."""
    if run_id and SAFE_RUN_ID_RE.match(run_id) and ".." not in run_id:
        return run_id
    return ""

SCRIPT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = SCRIPT_DIR.parent

RAW_DATA_DIR = str(DASHBOARD_DIR / "src" / "data" / "runs")
OUTPUT_DIR = str(DASHBOARD_DIR / "src" / "data" / "compiled")
RUNS_DIST_DIR = str(DASHBOARD_DIR / "src" / "data" / "runs")

def load_json(filepath):
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None

def compile_dashboard_data():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(RUNS_DIST_DIR, exist_ok=True)

    json_files = glob.glob(os.path.join(RAW_DATA_DIR, "run-*.json")) + glob.glob(os.path.join(RAW_DATA_DIR, "run_*.json"))
    json_files.sort(key=os.path.getmtime, reverse=True) # newest first

    all_runs = []
    total_runs = 0
    passed_runs = 0
    total_duration = 0
    
    flavor_stats = {
        "bluefin": {"runs": 0, "passed": 0, "failed": 0},
        "aurora": {"runs": 0, "passed": 0, "failed": 0},
        "bluefin-lts": {"runs": 0, "passed": 0, "failed": 0},
        "dakota": {"runs": 0, "passed": 0, "failed": 0}
    }

    # Limit compiled run index to the last 200 runs for visual performance
    for filepath in json_files[:200]:
        run_data = load_json(filepath)
        if not run_data:
            continue
            
        run_id = sanitize_run_id(str(run_data.get("id", "")))
        if not run_id:
            # Fall back to the (glob-constrained) source filename so a hostile
            # id field cannot steer the write path below.
            run_id = Path(filepath).stem
        run_data["id"] = run_id
        flavor = run_data.get("flavor", "bluefin")
        status = run_data.get("summary", {}).get("status", "failed")
        
        # Save exact copy of full detailed run output for the Astro static dynamic paths
        with open(os.path.join(RUNS_DIST_DIR, f"{run_id}.json"), 'w') as f:
            json.dump(run_data, f, indent=2)

        # Build compact representation for rollup summary-index
        compact = {
            "id": run_id,
            "timestamp": run_data.get("timestamp", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")),
            "stream": run_data.get("stream", "testing"),
            "flavor": flavor,
            "suite": run_data.get("suite", "unknown"),
            "version": run_data.get("version", "unknown"),
            "status": status,
            "metrics": {
                "passed": run_data.get("summary", {}).get("passed_tests", 0),
                "failed": run_data.get("summary", {}).get("failed_tests", 0),
                "skipped": run_data.get("summary", {}).get("skipped_tests", 0),
                "total": run_data.get("summary", {}).get("total_tests", 0)
            },
            "duration_ms": run_data.get("summary", {}).get("total_duration_ms", 0),
            "commit_sha": run_data.get("git_commit", {}).get("sha", "unknown")
        }
        all_runs.append(compact)

        # Aggregate statistics
        total_runs += 1
        total_duration += run_data.get("summary", {}).get("total_duration_ms", 0)
        if status == "passed" or status == "success":
            passed_runs += 1
            
        if flavor not in flavor_stats:
            flavor_stats[flavor] = {"runs": 0, "passed": 0, "failed": 0}

        flavor_stats[flavor]["runs"] += 1
        if status == "passed" or status == "success":
            flavor_stats[flavor]["passed"] += 1
        else:
            flavor_stats[flavor]["failed"] += 1

    overall_pass_rate = passed_runs / total_runs if total_runs > 0 else 1.0
    avg_duration = total_duration / total_runs if total_runs > 0 else 0

    rollup = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aggregates": {
            "total_runs": total_runs,
            "overall_pass_rate": round(overall_pass_rate, 4),
            "average_test_duration_ms": int(avg_duration),
            "flavors": flavor_stats
        },
        "runs": all_runs
    }

    with open(os.path.join(OUTPUT_DIR, "summary-index.json"), "w") as f:
        json.dump(rollup, f, indent=2)
    
    print(f"Data Compilation Complete. Processed {total_runs} runs.")

if __name__ == "__main__":
    compile_dashboard_data()