"""The run-behave step must run behave under the qecore-headless supervisor in
every branch, without expanding $BEHAVE_BIN on the runner.

The action builds an SSH payload as a single double-quoted runner string. On the
runner it expands ${HEADLESS_FLAGS}, $WRAPPER and $GNOME_E2E_SUITE; it sends
$HOME and $BEHAVE_BIN to the guest literally (escaped as \\$), because those are
set inside the guest. A regression that un-escapes $BEHAVE_BIN makes the runner's
nounset shell abort with "unbound variable" before anything reaches the guest,
and a regression that drops qecore-headless runs behave with no supervisor.

This test reproduces that two-level expansion faithfully: a runner-level bash
script (with `set -u`) defines SSH as a capturing stub that records the
runner-expanded payload, then executes it as the guest. qecore-headless and
behave are stubbed on the guest; the qecore-headless stub records the arguments
it was handed. The runner's nounset shell is what catches a re-introduced
un-escaped $BEHAVE_BIN.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION = REPO_ROOT / ".github" / "actions" / "gnome-e2e" / "action.yml"

SSH_OPEN = '$SSH "'
BEHAVE_RC = "|| BEHAVE_RC=$?"
SESSION_ENV_PATH = "/tmp/gnome_e2e_session.env"

QECORE_HEADLESS_STUB = """\
#!/bin/bash
# Stub supervisor: record the arguments qecore-headless was asked to run, then
# succeed. The real supervisor owns the GNOME session lifecycle; here we only
# assert the action passed it the behave command instead of execing behave.
{
  echo "INVOCATION"
  printf '%s\\n' "$@"
} >> "$RECORD_FILE"
exit 0
"""

BEHAVE_STUB = """\
#!/bin/bash
exit 0
"""

# Runner-level script. `set -u` makes an un-escaped $BEHAVE_BIN abort here,
# exactly as it would on the real runner before the SSH call.
RUNNER_TMPL = """\
set -euo pipefail

ssh_capture() {
  # Rewrite the guest's session-env path to the per-test temp file, then run the
  # runner-expanded payload as the guest.
  sed "s|/tmp/gnome_e2e_session.env|$SESSION_ENV|g" <<<"$1" > "$GUEST_FILE"
  bash "$GUEST_FILE"
}
export -f ssh_capture
SSH=ssh_capture

export HOME="$FAKE_HOME"
export PATH="$FAKE_BIN:$PATH"
export WRAPPER="$WRAPPER_VAL"
export GNOME_E2E_SUITE="$SUITE_VAL"
HEADLESS_FLAGS=""
[[ "$GNOME_E2E_SUITE" == "gnomeos-canary" ]] && HEADLESS_FLAGS="--dont-kill"
export PATH HOME WRAPPER GNOME_E2E_SUITE HEADLESS_FLAGS
export GUEST_FILE SESSION_ENV RECORD_FILE

"$SSH" "
@@PAYLOAD@@
"
"""


def _build_runner(payload: str) -> str:
    return RUNNER_TMPL.replace("@@PAYLOAD@@", payload)


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    invocation: list[str]


def extract_ssh_payload(text: str) -> str:
    """Return the raw payload of the run-behave SSH step.

    The action has several `$SSH "..."` steps; this is the one that ends with the
    `|| BEHAVE_RC=$?` guard. Find that guard, back up to its closing quote, then
    to the `$SSH "` that opens its argument, and return what is between.
    """
    end = text.index(BEHAVE_RC)
    close = text.rindex('"', 0, end)
    ssh_marker = text.rindex(SSH_OPEN, 0, close)
    start = ssh_marker + len(SSH_OPEN)
    return text[start:close]


def run_action(suite: str, wrapper: str) -> RunResult:
    tmp = Path(tempfile.mkdtemp(prefix="_e2e_run_command_"))
    try:
        (tmp / "bin").mkdir(parents=True)
        (tmp / "home" / ".local" / "bin").mkdir(parents=True)

        rec = tmp / "record.txt"
        rec.touch()
        guest_file = tmp / "guest.sh"
        (tmp / "session.env").write_text("export WAYLAND_DISPLAY=wayland-1\n")

        (tmp / "bin" / "behave").write_text(BEHAVE_STUB)
        (tmp / "home" / ".local" / "bin" / "qecore-headless").write_text(
            QECORE_HEADLESS_STUB
        )
        for script in tmp.rglob("*"):
            if script.is_file():
                script.chmod(0o755)

        payload = extract_ssh_payload(ACTION.read_text())
        runner = _build_runner(payload)
        runner_path = tmp / "runner.sh"
        runner_path.write_text(runner)

        proc = subprocess.run(
            ["bash", str(runner_path)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "FAKE_HOME": str(tmp / "home"),
                "FAKE_BIN": str(tmp / "bin"),
                "WRAPPER_VAL": wrapper,
                "SUITE_VAL": suite,
                "SESSION_ENV": str(tmp / "session.env"),
                "GUEST_FILE": str(guest_file),
                "RECORD_FILE": str(rec),
            },
        )

        invocation = []
        if rec.exists():
            lines = rec.read_text().splitlines()
            if lines and lines[0] == "INVOCATION":
                invocation = lines[1:]

        return RunResult(proc.returncode, proc.stdout, proc.stderr, invocation)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _assert_clean(result: RunResult) -> None:
    assert result.returncode == 0, (
        f"runner exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "unbound variable" not in result.stderr, (
        f"$BEHAVE_BIN expanded on the runner: {result.stderr}"
    )
    assert result.invocation, "qecore-headless was never invoked"


def test_canary_runs_behave_under_qecore_supervisor():
    """gnomeos-canary sets a wrapper; qecore-headless must receive it as its
    command argument, not behave execed directly (finding 2)."""
    result = run_action("gnomeos-canary", "/bin/bash /tmp/gnome_e2e/run-behave.sh")
    _assert_clean(result)
    assert result.invocation == [
        "--dont-kill",
        "/bin/bash /tmp/gnome_e2e/run-behave.sh",
    ]


def test_smoke_runs_behave_under_qecore_supervisor():
    """Without a wrapper, the else-branch still runs behave under qecore-headless,
    with $BEHAVE_BIN resolved inside the guest (finding 2)."""
    result = run_action("smoke", "")
    _assert_clean(result)
    # ${HEADLESS_FLAGS} is unquoted in action.yml, so it vanishes when empty for
    # the smoke suite; the behave command is the sole argument.
    assert len(result.invocation) == 1
    behave_cmd = result.invocation[0]
    assert "/behave " in behave_cmd
    assert "/tmp/gnome_e2e/tests/smoke/features/" in behave_cmd
    assert "--format json.pretty" in behave_cmd


def test_behave_bin_is_not_expanded_on_runner():
    """The smoke branch references $BEHAVE_BIN only inside the guest; an
    un-escaped reference must abort the runner under nounset (finding 1)."""
    result = run_action("smoke", "")
    _assert_clean(result)
    assert "unbound variable" not in result.stderr
