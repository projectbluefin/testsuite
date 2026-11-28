"""Throwaway read-only probe step (spike/ship-probe, never merged).

Sends ship_probe.sh to the guest, runs it as the logged-in test user with the
session bus (the script sources /tmp/session.env like the suite's other SSH
commands), saves the whole output as ship-probe.txt in the results directory
and prints it to the job log. A failing probe command is recorded in the
output, never fatal: the step fails only when the script did not run at all.
"""
import base64
import os
import subprocess

from behave import step

from steps.steps import _run_host
from tests.shared.results_dir import resolve_results_dir

_SCRIPT_NAME = "ship_probe.sh"
_OUTPUT_NAME = "ship-probe.txt"
_TIMEOUT_SECONDS = 900


def _script_path(context) -> str:
    candidates = []
    try:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), _SCRIPT_NAME))
    except NameError:
        pass
    feature_file = getattr(getattr(context, "feature", None), "filename", "") or ""
    if feature_file:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(feature_file)), "steps", _SCRIPT_NAME))
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise AssertionError(f"{_SCRIPT_NAME} not found; looked in {candidates}")


@step("the ship probe records what the booted image ships")
def ship_probe_records_image(context) -> None:
    with open(_script_path(context), "rb") as fh:
        payload = base64.b64encode(fh.read()).decode("ascii")

    # Process substitution keeps the script off the guest's disk and leaves
    # the probe's stdin on /dev/null. stderr is merged so order is preserved.
    cmd = f"bash <(printf %s {payload} | base64 -d) </dev/null 2>&1"

    timed_out = False
    try:
        output, returncode, stderr = _run_host(cmd, timeout=_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        partial = exc.stdout or b""
        output = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
        returncode, stderr = None, f"timed out after {_TIMEOUT_SECONDS}s"

    image = os.environ.get("BASE_IMAGE") or os.environ.get("IMAGE") or "unknown"
    header = (
        f"# ship-probe image={image} composed_image={os.environ.get('IMAGE', '')}\n"
        f"# ship-probe transport_rc={returncode} timed_out={timed_out}\n"
    )
    if stderr:
        header += "# ship-probe transport_stderr:\n" + "".join(
            f"#   {line}\n" for line in stderr.splitlines()
        )
    text = header + (output or "") + "\n"

    results_dir = resolve_results_dir(context)
    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, _OUTPUT_NAME)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    print(f"===== BEGIN {_OUTPUT_NAME} ({out_path}, {len(text)} bytes) =====", flush=True)
    print(text, flush=True)
    print(f"===== END {_OUTPUT_NAME} =====", flush=True)

    assert "=== identity" in (output or ""), (
        f"ship probe did not run (rc={returncode}, timed_out={timed_out}): {stderr}"
    )
