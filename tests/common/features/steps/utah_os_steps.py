"""Utah-only steps for the common suite."""
from behave import step

from tests.shared.ssh_steps import run_ssh

# Mirrors utah iso/scripts/verify-countme-runtime.sh @527c5aff: the service's
# ConditionPathExists, not the client, enforces opt-out, so a skipped start
# never reaches the network. The trap removes the marker on every exit path.
_COUNTME_OPT_OUT = r"""sudo bash -c '
set -euo pipefail
m=/etc/projectbluefin/countme/disabled
s=projectbluefin-countme.service
[ ! -e "$m" ] || { echo "opt-out marker already present"; exit 1; }
trap "rm -f $m; rmdir /etc/projectbluefin/countme /etc/projectbluefin 2>/dev/null || :" EXIT
before=$(systemctl show -p ExecMainStartTimestamp --value "$s")
install -D -m 0644 /dev/null "$m"
systemctl start "$s"
echo "ConditionResult=$(systemctl show -p ConditionResult --value "$s")"
if [ "$(systemctl show -p ExecMainStartTimestamp --value "$s")" = "$before" ]; then echo NOT_EXECUTED; fi
'"""


@step("CountMe service start is skipped while the opt-out marker exists")
def step_countme_opt_out(context):
    out, rc = run_ssh(context, _COUNTME_OPT_OUT)
    assert rc == 0, f"CountMe opt-out probe failed (rc={rc}): {out}"
    assert "ConditionResult=no" in out, f"opt-out marker ignored: {out}"
    assert "NOT_EXECUTED" in out, f"service executed despite opt-out: {out}"
    _, rc = run_ssh(context, "test ! -e /etc/projectbluefin/countme/disabled")
    assert rc == 0, "opt-out marker was not removed"
