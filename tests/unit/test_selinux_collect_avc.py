"""Regression coverage for the guest's piped AVC collector."""

import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "selinux_collect_avc.sh"


def test_piped_collector_preserves_script_after_ausearch(tmp_path):
    audit_log = tmp_path / "audit.log"
    audit_log.write_text("audit record\n")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    commands = {
        "ausearch": "if [[ $1 != --input-logs ]]; then cat >/dev/null; exit; fi\necho 'avc: audit'\n",
        "journalctl": "echo 'avc: journal'\n",
        "dmesg": "echo 'avc: kernel'\n",
    }
    for name, body in commands.items():
        executable = fakebin / name
        executable.write_text("#!/usr/bin/env bash\n" + body)
        executable.chmod(0o755)

    # Redirect only the guest's fixed audit-log path to the isolated fixture.
    script = SCRIPT.read_text().replace("/var/log/audit/audit.log", str(audit_log))
    result = subprocess.run(
        ["bash", "-s"], input=script, text=True, capture_output=True,
        env={**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}"}, check=True,
    )
    assert result.stdout.splitlines() == ["avc: audit", "avc: journal", "avc: kernel"]
