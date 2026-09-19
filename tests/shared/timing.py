"""Scenario timing helpers — write JSONL lines to the configured results directory.

Each ``record_end`` call appends one JSON object to ``<results_dir>/timings.jsonl``.
That file is not a debug artifact: the "Summarise results" step of
``.github/actions/gnome-e2e/action.yml`` reads it back and reports every entry whose
``sla_violated`` is true and whose ``status`` is not ``skipped``. The key names in
``record_end`` are therefore a contract with that reader, enforced by
``tests/unit/test_timing_contract.py``.

An SLA applies to a scenario only when the scenario carries an ``@sla_<n>s`` tag.
There is deliberately no default-SLA table and no strict/failing mode: a violation is
reported, never enforced. Add either only together with the code that acts on it.
"""

import json
import os
import re
import time

from tests.shared.results_dir import resolve_results_dir as _results_dir

SLA_TAG_PATTERN = re.compile(r"sla_(\d+)s")


def _scenario_sla_seconds(scenario):
    """Return SLA threshold from the first matching scenario tag, if present."""
    tags = getattr(scenario, "effective_tags", None) or getattr(scenario, "tags", [])
    for tag in tags:
        match = SLA_TAG_PATTERN.fullmatch(tag.lstrip("@"))
        if match:
            return int(match.group(1))
    return None


def record_start(context):
    """Call in before_scenario to stamp start time on context."""
    context._timing_start = time.monotonic()


def record_end(context, scenario):
    """Call in after_scenario to append a JSONL line.

    Returns elapsed seconds (float).
    """
    start = getattr(context, "_timing_start", None)
    if start is None:
        return None
    elapsed = time.monotonic() - start
    results_dir = _results_dir(context)
    timings_file = os.path.join(results_dir, "timings.jsonl")
    os.makedirs(results_dir, exist_ok=True)
    rounded_elapsed = round(elapsed, 3)
    sla_s = _scenario_sla_seconds(scenario)
    entry = {
        "scenario": scenario.name,
        "feature": getattr(getattr(scenario, "feature", None), "name", "unknown"),
        "status": scenario.status.name,
        "elapsed": rounded_elapsed,
        "elapsed_s": rounded_elapsed,
        "sla_s": sla_s,
        "sla_violated": bool(sla_s is not None and rounded_elapsed > sla_s),
    }
    try:
        with open(timings_file, "a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return elapsed
