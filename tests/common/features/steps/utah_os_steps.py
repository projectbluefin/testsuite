"""Utah-only steps for the common suite."""
from behave import step

from tests.shared.ssh_steps import run_ssh

# Mirrors utah iso/scripts/verify-countme-runtime.sh @527c5aff: the service's
# ConditionPathExists, not the client, enforces opt-out, so a skipped start
# never reaches the network. The e2e harness pre-writes the marker; the probe
# then reuses it untouched. Otherwise it creates the marker and its trap
# removes only what the probe created, restoring the prior state.
_COUNTME_OPT_OUT = r"""sudo bash -c '
set -euo pipefail
d=/etc/projectbluefin/countme
m=$d/disabled
s=projectbluefin-countme.service
if [ -e "$m" ]; then
  echo MARKER_PREEXISTING
else
  dirs=
  [ -d /etc/projectbluefin ] || dirs="$d /etc/projectbluefin"
  [ -n "$dirs" ] || [ -d "$d" ] || dirs=$d
  trap "rm -f $m; ${dirs:+rmdir $dirs}" EXIT
  install -D -m 0644 /dev/null "$m"
fi
before=$(systemctl show -p ExecMainStartTimestamp --value "$s")
systemctl start "$s"
echo "ConditionResult=$(systemctl show -p ConditionResult --value "$s")"
if [ "$(systemctl show -p ExecMainStartTimestamp --value "$s")" = "$before" ]; then echo NOT_EXECUTED; fi
'"""


@step("CountMe service start is skipped while the opt-out marker exists")
def step_countme_opt_out(context):
    _, rc = run_ssh(context, "test -e /etc/projectbluefin/countme/disabled")
    preexisting = rc == 0
    out, rc = run_ssh(context, _COUNTME_OPT_OUT)
    assert rc == 0, f"CountMe opt-out probe failed (rc={rc}): {out}"
    assert "ConditionResult=no" in out, f"opt-out marker ignored: {out}"
    assert "NOT_EXECUTED" in out, f"service executed despite opt-out: {out}"
    _, rc = run_ssh(context, "test -e /etc/projectbluefin/countme/disabled")
    assert (rc == 0) == preexisting, (
        "opt-out marker state changed: "
        f"present before={preexisting}, present after={rc == 0}"
    )
