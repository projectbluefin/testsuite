# bluefin-test-suite Justfile
# All commands go through here — no loose shell commands.

# List all available recipes
default:
    @just --list

# ── Results ──────────────────────────────────────────────────────────────────

# List recent test results (most recent first)
# Usage: just results            → last 10 runs
# Usage: just results 20         → last 20 runs
results n="10":
    #!/usr/bin/env bash
    set -euo pipefail
    BASE="${RESULTS_BASE:-/var/tmp/bluefin-results}"
    if [[ ! -d "${BASE}" ]]; then
        echo "(no results yet — run a test first)"
        exit 0
    fi
    RESULTS_BASE="${BASE}" RESULTS_N="{{ n }}" python3 <<'PYEOF'
    import json
    import os
    from pathlib import Path

    from scripts.e2e_summary import count_scenarios, summary_icon

    base = Path(os.environ["RESULTS_BASE"])
    limit = int(os.environ["RESULTS_N"])
    print("=== Recent test results (last %d) ===" % limit)
    runs = sorted((path for path in base.iterdir() if path.is_dir()), key=lambda path: path.name)
    runs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for run in runs[:limit]:
        print()
        print("Run: %s" % run.name)
        for suite_dir in sorted(path for path in run.iterdir() if path.is_dir()):
            suite = suite_dir.name
            report_path = suite_dir / "results.json"
            if not report_path.is_file():
                print("  ? %s: (no results.json)" % suite)
                continue
            try:
                with report_path.open(encoding="utf-8") as file_obj:
                    counts = count_scenarios(json.load(file_obj))
            except Exception as error:
                print("  ? %s: (error reading results.json: %s)" % (suite, error))
                continue
            total = sum(counts.values())
            print("  %s %s: %d/%d passed" % (summary_icon(counts), suite, counts["passed"], total))
    PYEOF

# Show per-scenario timing table from the most recent run (or a specific run-uid)
# Usage: just results-timing          → most recent run
# Usage: just results-timing <uid>    → specific run
results-timing uid="":
    #!/usr/bin/env bash
    set -euo pipefail
    BASE="${RESULTS_BASE:-/var/tmp/bluefin-results}"
    if [[ -z "{{ uid }}" ]]; then
        RUN_ID=$(ls -1t "${BASE}" 2>/dev/null | head -1)
        [[ -z "${RUN_ID}" ]] && echo "(no results yet)" && exit 0
        RUN="${BASE}/${RUN_ID}"
    else
        RUN="${BASE}/{{ uid }}"
    fi
    if [[ ! -d "${RUN}" ]]; then
        echo "(run not found: ${RUN})"
        exit 1
    fi
    RUN="${RUN}" python3 <<'PYEOF'
    import json
    import os
    import sys
    from pathlib import Path

    run = Path(os.environ["RUN"])
    strict = os.environ.get("TIMING_SLA_STRICT", "").lower() in {"1", "true", "yes"}
    rows = []
    for path in sorted(run.rglob("timings.jsonl")):
        suite = path.parent.name
        with path.open(encoding="utf-8") as file_obj:
            for line in file_obj:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                rows.append({
                    "suite": suite,
                    "scenario": str(entry.get("scenario", "")),
                    "status": str(entry.get("status", "unknown")),
                    "elapsed": float(entry.get("elapsed_s", 0.0)),
                    "sla": entry.get("sla_s", "-"),
                    "violation": "yes" if entry.get("sla_violated") else "no",
                })

    if not rows:
        print("(no timing data found in %s)" % run)
        sys.exit(0)

    rows.sort(key=lambda row: row["elapsed"], reverse=True)
    headers = [("Suite", "suite"), ("Scenario", "scenario"), ("Status", "status"), ("Elapsed", "elapsed"), ("SLA", "sla"), ("Violation", "violation")]
    formatted = []
    for row in rows:
        formatted.append({
            **row,
            "elapsed": "%.3fs" % row["elapsed"],
            "sla": "%ss" % row["sla"],
        })
    widths = {title: len(title) for title, _ in headers}
    for row in formatted:
        for title, key in headers:
            widths[title] = max(widths[title], len(str(row[key])))

    header_line = " | ".join(title.ljust(widths[title]) for title, _ in headers)
    rule_line = "-+-".join("-" * widths[title] for title, _ in headers)
    print(header_line)
    print(rule_line)
    for row in formatted:
        print(" | ".join(str(row[key]).ljust(widths[title]) for title, key in headers))

    violations = sum(1 for row in rows if row["violation"] == "yes")
    print()
    print("Total scenarios timed: %d" % len(rows))
    print("SLA violations: %d" % violations)
    if strict and violations:
        sys.exit(1)
    PYEOF

# Remove old test results (keeps last N runs)
# Usage: just clean-results      → keep last 20 runs
# Usage: just clean-results 5    → keep last 5 runs
clean-results keep="20":
    #!/usr/bin/env bash
    set -euo pipefail
    BASE="${RESULTS_BASE:-/var/tmp/bluefin-results}"
    if [[ ! -d "${BASE}" ]]; then
        echo "(no results directory)"
        exit 0
    fi
    TOTAL=$(ls -1 "${BASE}" | wc -l)
    TO_DELETE=$((TOTAL - {{ keep }}))
    if [[ ${TO_DELETE} -le 0 ]]; then
        echo "✓ ${TOTAL} runs present, nothing to remove (keeping {{ keep }})"
        exit 0
    fi
    echo "Removing ${TO_DELETE} oldest run(s) (keeping {{ keep }} of ${TOTAL})..."
    ls -1t "${BASE}" | tail -${TO_DELETE} | while read dir; do
        echo "  removing ${BASE}/${dir}"
        rm -rf "${BASE:?}/${dir}"
    done
    echo "✓ Done"

# Compare overlapping scenarios between smoke and vanilla-gnome results
# Usage: just compare-results
# Usage: just compare-results <run-uid>
compare-results run_uid="":
    #!/usr/bin/env bash
    set -euo pipefail
    BASE="${RESULTS_BASE:-/var/tmp/bluefin-results}"
    if [[ ! -d "${BASE}" ]]; then
        echo "(no results directory — run a test first)"
        exit 0
    fi
    if [[ -n "{{ run_uid }}" ]]; then
        RUN_DIR="${BASE}/{{ run_uid }}"
        if [[ ! -d "${RUN_DIR}" ]]; then
            echo "(run not found: {{ run_uid }})"
            exit 0
        fi
    else
        LATEST=$(ls -1t "${BASE}" | head -1)
        if [[ -z "${LATEST}" ]]; then
            echo "(no results yet — run a test first)"
            exit 0
        fi
        RUN_DIR="${BASE}/${LATEST}"
    fi
    SMOKE_JSON="${RUN_DIR}/smoke/results.json"
    VANILLA_JSON="${RUN_DIR}/vanilla-gnome/results.json"
    if [[ ! -f "${SMOKE_JSON}" || ! -f "${VANILLA_JSON}" ]]; then
        echo "(comparison skipped — expected smoke/results.json and vanilla-gnome/results.json under ${RUN_DIR})"
        exit 0
    fi
    RUN_UID=$(basename "${RUN_DIR}")
    RUN_UID="${RUN_UID}" SMOKE_JSON="${SMOKE_JSON}" VANILLA_JSON="${VANILLA_JSON}" python3 - <<'PY'
    import json
    import os
    import sys
    from pathlib import Path

    from scripts.e2e_summary import scenario_statuses

    run_uid = os.environ["RUN_UID"]
    smoke = scenario_statuses(json.loads(Path(os.environ["SMOKE_JSON"]).read_text(encoding="utf-8")))
    vanilla = scenario_statuses(json.loads(Path(os.environ["VANILLA_JSON"]).read_text(encoding="utf-8")))
    overlap = sorted(set(smoke) & set(vanilla))

    print(f"=== Smoke vs Vanilla-GNOME comparison: {run_uid} ===")
    if not overlap:
        print("(no overlapping scenarios found)")
        sys.exit(0)

    scenario_width = max(len("Scenario"), *(len(name) for name in overlap))
    smoke_width = max(len("Smoke"), *(len(smoke[name]) for name in overlap))
    vanilla_width = max(len("Vanilla-GNOME"), *(len(vanilla[name]) for name in overlap))

    header = f"{'Scenario':<{scenario_width}}  {'Smoke':<{smoke_width}}  {'Vanilla-GNOME':<{vanilla_width}}"
    print(header)
    print(f"{'-' * scenario_width}  {'-' * smoke_width}  {'-' * vanilla_width}")

    bluefin_regressions = 0
    upstream_issues = 0
    same_result = 0
    for name in overlap:
        smoke_status = smoke[name]
        vanilla_status = vanilla[name]
        note = ""
        if smoke_status == "failed" and vanilla_status == "passed":
            bluefin_regressions += 1
            note = "  ⚠ Bluefin regression"
        elif smoke_status == "failed" and vanilla_status == "failed":
            upstream_issues += 1
            note = "  ↑ Upstream GNOME issue"
        else:
            same_result += 1
        print(f"{name:<{scenario_width}}  {smoke_status:<{smoke_width}}  {vanilla_status:<{vanilla_width}}{note}")

    print(
        f"Summary: {len(overlap)} overlapping scenario(s) | "
        f"{bluefin_regressions} Bluefin regression(s) | "
        f"{upstream_issues} upstream GNOME issue(s) | "
        f"{same_result} other matching/mixed result(s)"
    )
    PY

# ── Validation ───────────────────────────────────────────────────────────────

# Verify cosign signatures on all active Bluefin image tags
verify-images:
    #!/usr/bin/env bash
    set -euo pipefail
    IMAGES=(
        "ghcr.io/ublue-os/bluefin:latest"
        "ghcr.io/ublue-os/bluefin:lts"
        "ghcr.io/ublue-os/bluefin-dx:latest"
        # Uncomment as variants are added to the matrix:
        # "ghcr.io/ublue-os/bluefin-nvidia:latest"
    )
    ISSUER="https://token.actions.githubusercontent.com"
    IDENTITY="https://github.com/ublue-os/.*"
    FAILED=0
    for img in "${IMAGES[@]}"; do
        echo "Verifying: ${img}..."
        if cosign verify \
            --certificate-oidc-issuer="${ISSUER}" \
            --certificate-identity-regexp="${IDENTITY}" \
            "${img}" >/dev/null 2>&1; then
            echo "  ✓ ${img}"
        else
            echo "  ✗ ${img} — signature verification FAILED"
            FAILED=$((FAILED + 1))
        fi
    done
    if [[ ${FAILED} -gt 0 ]]; then
        echo "ERROR: ${FAILED} image(s) failed verification"
        exit 1
    fi
    echo "✓ All images verified"

# Pin all tracked image tags to their current SHA256 digest and write images.lock.
# Requires: skopeo on PATH and registry credentials (for ghcr.io, docker login or REGISTRY_AUTH_FILE).
# Usage: just lock-images
lock-images:
    #!/usr/bin/env bash
    set -euo pipefail
    IMAGES=(
        "ghcr.io/ublue-os/bluefin:latest"
        "ghcr.io/ublue-os/bluefin:lts"
        "ghcr.io/ublue-os/bluefin-dx:latest"
        "ghcr.io/ublue-os/bluefin-nvidia:latest"
    )
    LOCKED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    LOCK_FILE="images.lock"
    echo "{" > "${LOCK_FILE}"
    TOTAL=${#IMAGES[@]}
    IDX=0
    for img in "${IMAGES[@]}"; do
        IDX=$((IDX + 1))
        tag="${img##*:}"
        ref="${img%%:*}:${tag}"
        echo "Resolving ${ref}..."
        digest="$(skopeo inspect --format='{{{{.Digest}}}}' "docker://${ref}" 2>/dev/null)"
        if [[ -z "${digest}" ]]; then
            echo "ERROR: could not resolve digest for ${ref}" >&2
            exit 1
        fi
        echo "  ${ref} → ${digest}"
        COMMA=","
        [[ ${IDX} -eq ${TOTAL} ]] && COMMA=""
        printf '  "%s": {"image": "%s", "digest": "%s", "locked_at": "%s"}%s\n' \
            "${tag}" "${ref}" "${digest}" "${LOCKED_AT}" "${COMMA}" >> "${LOCK_FILE}"
    done
    echo "}" >> "${LOCK_FILE}"
    echo "✓ Written ${LOCK_FILE}"
    cat "${LOCK_FILE}"

# ── Development ───────────────────────────────────────────────────────────────

# Run all fast local checks (lint, unit tests, and steps audit) to verify test suite changes
test-local:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Running Ruff Linter ==="
    ruff check tests/ --select E,F,W --ignore E501
    echo "=== Running Unit Tests ==="
    python3 -m pytest tests/unit/ -q
    echo "=== Running Step Audit and Dry-Runs ==="
    just audit-steps
    for d in tests/*/features/; do
        if [[ -d "$d" ]]; then
            echo "Dry-running behave on $d..."
            PYTHONPATH=. python3 -m behave --dry-run --no-summary "$d"
        fi
    done
    echo "✓ All local checks passed successfully!"

# Audit step definitions across all suites to check for step collisions and loading errors
audit-steps:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! python3 -c "import behave" &>/dev/null; then
        echo "Error: 'behave' is not installed in the current Python environment."
        echo "Please install dependencies or run inside a virtualenv."
        exit 1
    fi
    for d in tests/*/features/; do
        if [[ -d "$d" ]]; then
            suite=$(basename "$(dirname "$d")")
            echo "Auditing steps catalog for suite: ${suite}..."
            PYTHONPATH=. python3 -m behave --steps-catalog --dry-run --no-summary "$d" >/dev/null \
                && echo "  ✓ ${suite} steps OK" \
                || { echo "  ✗ ${suite} steps FAILED"; exit 1; }
        fi
    done

# List all stub/future test scenarios not yet implemented
list-stubs:
    #!/usr/bin/env bash
    echo "=== Stubbed scenarios (@future tag) ==="
    grep -r '@future' tests/*/features/*.feature 2>/dev/null | sed 's/.*tests/  tests/' || echo "  (none)"
    echo ""
    echo "=== NotImplementedError stubs ==="
    grep -rn 'raise NotImplementedError' tests/*/features/steps/*.py 2>/dev/null | sed 's/.*tests/  tests/' || echo "  (none)"
