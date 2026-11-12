"""Unit tests for scripts/selinux_canary.sh's candidate loop.

The canary tries confined domains in order and stops at the first audited
denial. A domain the loaded policy lacks fails before `cat` runs (229/
SELINUX_CONTEXT); the loop must skip it and try the next domain (#1156). The
old loop only recognised 203/EXEC and fell through to the shadow_t checks for
every other status, so a 229 domain (whose `sesearch` output is empty) broke
the loop on a domain that produced no denial.

These tests run the real script with fake `systemd-run` and `sesearch` on PATH
and assert which domains the loop reaches. They do not exercise SELinux — they
lock in the loop control flow.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "selinux_canary.sh"


def _write_fake(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_systemd_run(tmp_path: Path, status_by_type: dict[str, int]) -> Path:
    # Emulate `systemd-run --wait`: parse the SELinuxContext= arg for the
    # domain, print a status line the script parses, and exit 0.
    lines = ["#!/usr/bin/env bash", 'ctx=""', 'for a in "$@"; do']
    lines.append('  case "$a" in SELinuxContext=*) ctx="${a#SELinuxContext=}" ;; esac')
    lines.append("done")
    lines.append('IFS=":" read -r _user _role type _rest <<<"$ctx"')
    lines.append('case "${type}" in')
    for domain, status in status_by_type.items():
        lines.append(
            f'  {domain}) echo "run-u1: Finished with result: '
            f'code=exited/status={status}/EXEC"; exit 0 ;;'
        )
    lines.append('  *) echo "run-u1: Finished with result: code=exited/status=0"; exit 0 ;;')
    lines.append("esac")
    return _write_fake(tmp_path, "systemd-run", "\n".join(lines) + "\n")


def _fake_sesearch(
    tmp_path: Path, behavior: dict[tuple[str, bool], str]
) -> Path:
    # Emulate `sesearch`: return the configured output for (-s domain,
    # --dontaudit?). An empty output means "no matching rule".
    lines = ["#!/usr/bin/env bash", 'domain=""', 'dontaudit=0', 'want_type=0', 'for a in "$@"; do']
    lines.append('  if [[ ${want_type} -eq 1 ]]; then domain="$a"; want_type=0; continue; fi')
    lines.append('  case "$a" in')
    lines.append('    --dontaudit) dontaudit=1 ;;')
    lines.append('    -s) want_type=1 ;;')
    lines.append('  esac')
    lines.append("done")
    lines.append('key="${domain}|${dontaudit}"')
    lines.append('case "$key" in')
    for (domain, dontaudit), out in behavior.items():
        escaped = out.replace("'", "'\\''")
        lines.append(f'  "{domain}|{int(dontaudit)}") printf "%s" "{escaped}"; exit 0 ;;')
    lines.append('  *) exit 0 ;;')
    lines.append("esac")
    return _write_fake(tmp_path, "sesearch", "\n".join(lines) + "\n")


def _run_script(tmp_path: Path, status_by_type, sesearch_behavior) -> subprocess.CompletedProcess:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _fake_systemd_run(fakebin, status_by_type)
    _fake_sesearch(fakebin, sesearch_behavior)
    env = dict(os.environ)
    env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _canary_type(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("canary_type="):
            return line.split("=", 1)[1]
    return ""


def _attempted_domains(stdout: str) -> tuple[str, ...]:
    return tuple(
        line.split("=", 1)[0][len("attempt_"):]
        for line in stdout.splitlines()
        if line.startswith("attempt_")
    )


def test_229_first_candidate_is_skipped_and_second_is_reached(tmp_path):
    # #1156: a 229/SELINUX_CONTEXT first candidate must not break the loop; the
    # loop must reach the second candidate (sshd_t, 203/EXEC) and stop there.
    result = _run_script(
        tmp_path,
        {"httpd_t": 229, "sshd_t": 203},
        {},  # sesearch returns no rules for any domain
    )
    assert result.returncode == 0, result.stderr
    assert "attempt_sshd_t=" in result.stdout, result.stdout
    assert _canary_type(result.stdout) == "sshd_t"


def test_status_one_shadow_denial_stops_the_loop(tmp_path):
    # Regression guard for the new elif branch: a domain whose cat ran and was
    # denied reading /etc/shadow (status 1, no read rule on shadow_t) breaks the
    # loop there. A domain that can read shadow (status 1, read rule present)
    # is skipped instead, so httpd_t is skipped and sshd_t stops the loop.
    result = _run_script(
        tmp_path,
        {"httpd_t": 1, "sshd_t": 1},
        {("httpd_t", False): "read"},  # httpd_t can read shadow -> skip
    )
    assert result.returncode == 0, result.stderr
    assert _attempted_domains(result.stdout) == ("httpd_t", "sshd_t")
    assert _canary_type(result.stdout) == "sshd_t"


def test_229_for_every_candidate_tries_all_without_a_shadow_break(tmp_path):
    # No domain produces a collectible denial: every candidate is skipped and
    # the loop exhausts, leaving canary_type at the last attempted domain.
    result = _run_script(
        tmp_path,
        {"httpd_t": 229, "sshd_t": 229, "getty_t": 229, "syslogd_t": 229, "chronyd_t": 229},
        {},
    )
    assert result.returncode == 0, result.stderr
    assert _attempted_domains(result.stdout) == (
        "httpd_t",
        "sshd_t",
        "getty_t",
        "syslogd_t",
        "chronyd_t",
    )
    assert _canary_type(result.stdout) == "chronyd_t"


def test_execve_denial_still_stops_the_loop(tmp_path):
    # Regression guard: a 203/EXEC domain with an audited execve denial still
    # breaks the loop immediately (the fix must not change the 203/EXEC path).
    result = _run_script(
        tmp_path,
        {"httpd_t": 203, "sshd_t": 203},
        {("httpd_t", True): ""},  # bin_t execute is not dontaudit'd -> audited
    )
    assert result.returncode == 0, result.stderr
    assert _attempted_domains(result.stdout) == ("httpd_t",)
    assert _canary_type(result.stdout) == "httpd_t"
