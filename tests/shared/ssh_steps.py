"""
Shared SSH step definitions for reusable command/assertion steps.
Used by common, developer, lifecycle, security, nvidia, hardware, and software suites.
Import with: from tests.shared.ssh_steps import *
Or register with behave via environment.py importing this module.
"""

import os
import shlex
import subprocess
from time import sleep

from behave import step

from tests.shared.ssh_config import ssh_argv


def _is_local_target(context) -> bool:
    """Return True if tests are executing directly on the target host/container."""
    vm_ip = getattr(context, "vm_ip", "")
    if not vm_ip:
        return True
    if vm_ip in ("127.0.0.1", "localhost") and os.path.isfile("/usr/bin/bootc"):
        return True
    return False


def run_ssh(context, cmd, timeout=60):
    """Run a command over SSH and store stdout/return code on context."""
    prefix = getattr(context, "ssh_command_prefix", "")
    final_cmd = cmd
    if prefix:
        final_cmd = f"bash -c {shlex.quote(f'{prefix}; {cmd}')}"
    if _is_local_target(context):
        try:
            result = subprocess.run(
                ["bash", "-c", final_cmd],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            context.command_stdout = ""
            context.last_command_output = ""
            context.ssh_rc = -1
            context.last_ssh_result = None
            raise
        stdout = result.stdout.strip()
        context.command_stdout = stdout
        context.last_command_output = stdout
        context.ssh_rc = result.returncode
        context.last_ssh_result = result
        return stdout, result.returncode

    ssh_opts = ssh_argv(context, quiet=True) + [final_cmd]
    try:
        result = subprocess.run(ssh_opts, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        context.command_stdout = ""
        context.last_command_output = ""
        context.ssh_rc = -1
        context.last_ssh_result = None
        raise
    stdout = result.stdout.strip()
    context.command_stdout = stdout
    context.last_command_output = stdout
    context.ssh_rc = result.returncode
    context.last_ssh_result = result
    return stdout, result.returncode


@step("Bluefin VM is booted and reachable over SSH")
def vm_reachable_over_ssh(context):
    """Verify SSH connectivity to the test VM with retries (5 attempts, 10s apart)."""
    if _is_local_target(context):
        return
    last_error = ""
    for attempt in range(1, 6):
        try:
            stdout, returncode = run_ssh(context, "echo ok", timeout=20)
            if returncode == 0 and stdout == "ok":
                return
            last_error = f"rc={returncode}, stdout={stdout!r}"
        except subprocess.TimeoutExpired as exc:
            last_error = f"timeout after {exc.timeout}s"
        if attempt < 5:
            sleep(10)
    raise AssertionError(
        f"Cannot reach VM at {context.vm_ip} over SSH after 5 attempts: {last_error}"
    )


@step('Run SSH command: "{cmd}"')
def run_ssh_command(context, cmd):
    run_ssh(context, cmd)


@step('Run long SSH command: "{cmd}"')
def run_long_ssh_command(context, cmd):
    """Run a command that may take many minutes (bootc switch/upgrade pulling OCI layers)."""
    run_ssh(context, cmd, timeout=900)


@step('SSH command output "is" "{expected}"')
def ssh_output_is(context, expected):
    actual = getattr(context, "command_stdout", "").strip()
    assert actual == expected, f"Expected '{expected}', got '{actual}'"


@step('SSH command return code is "{code}"')
def ssh_return_code_is(context, code):
    actual = getattr(context, "ssh_rc", None)
    last_result = getattr(context, "last_ssh_result", None)
    stderr = getattr(last_result, "stderr", "") if last_result else ""
    stdout = getattr(last_result, "stdout", "") if last_result else ""
    assert actual == int(code), (
        f"SSH command exited {actual}, expected {code}\n"
        f"stdout: {stdout}\n"
        f"stderr: {stderr}"
    )


@step('SSH command output is not empty')
def ssh_output_not_empty(context):
    actual = getattr(context, "command_stdout", "")
    assert actual.strip(), "SSH command output is empty"


@step('SSH command output stripped "is" "{expected}"')
def ssh_output_stripped_is(context, expected):
    actual = getattr(context, "command_stdout", "").strip()
    assert actual == expected, f"Expected '{expected}', got '{actual}'"


@step('SSH command output is not "{a}" and not "{b}"')
def ssh_output_not_values(context, a, b):
    actual = getattr(context, "command_stdout", "").strip()
    assert actual not in (a, b), (
        f"System state is '{actual}' — expected neither '{a}' nor '{b}'"
    )


@step('SSH command output is not "{value}"')
def ssh_output_is_not(context, value):
    actual = getattr(context, "command_stdout", "").strip()
    assert actual != value, (
        f"SSH command output is '{value}' — expected a different value"
    )


@step('SSH command output contains "{text}"')
def ssh_output_contains(context, text):
    actual = getattr(context, "command_stdout", "").strip()
    assert text in actual, (
        f"SSH command output does not contain '{text}'\nGot: {actual}"
    )


@step('SSH command output does not contain "{text}"')
def ssh_output_does_not_contain(context, text):
    actual = getattr(context, "command_stdout", "").strip()
    assert text not in actual, (
        f"SSH command output contains '{text}' — expected it to be absent\nGot: {actual}"
    )


def _last_output(context):
    return (
        getattr(context, "command_stdout", None)
        or getattr(context, "last_command_output", None)
        or getattr(context, "last_run_output", None)
        or ""
    )


@step('Last command output contains "{text}"')
def last_command_output_contains(context, text):
    actual = _last_output(context)
    assert text in actual, f"Last command output does not contain {text!r}:\n{actual}"


@step('No journal entries match "{pattern}"')
def no_journal_entries_match(context, pattern):
    result = subprocess.run(
        ["journalctl", "-b", "--no-pager", "-g", pattern],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode in (0, 1), (
        f"journalctl failed while searching for {pattern!r}:\n"
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert result.stdout.strip() == "", (
        f"Unexpected journal entries matched {pattern!r}:\n{result.stdout.strip()}"
    )


@step('No coredump entries exist for "{name}"')
def no_coredump_entries_exist(context, name):
    result = subprocess.run(
        ["coredumpctl", "list", name, "--no-pager", "--lines=10"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode in (0, 1), (
        f"coredumpctl failed for {name}:\n"
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    matches = [line for line in result.stdout.splitlines() if name in line]
    assert not matches, f"Unexpected coredump entries for {name}: {matches}"
