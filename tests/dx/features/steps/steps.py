"""
DX variant step definitions.

Most steps reuse qecore common_steps (GUI) or plain SSH steps.
Only DX-specific custom steps defined here.

NOTE: 'Run and save command output' is provided by qecore.common_steps and must
NOT be redefined here — that would create an AmbiguousStep error.  The @plain_ssh
DX scenarios use 'Run DX SSH command' instead, which explicitly sets context.ssh_rc
so 'SSH command return code is' works reliably.
"""
import subprocess

from behave import step
from qecore.common_steps import *  # noqa: F401,F403

from tests.shared.ssh_config import ssh_argv


def _ssh(context, cmd, timeout=60):
    """Run a command on the DX VM over SSH and record stdout + return code."""
    result = subprocess.run(
        ssh_argv(context, quiet=True) + [cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    context.command_stdout = result.stdout.strip()
    context.last_command_output = context.command_stdout
    context.last_ssh_result = result
    context.ssh_rc = result.returncode
    return context.command_stdout, result.returncode


@step('Run DX SSH command: "{cmd}"')
def run_dx_ssh_command(context, cmd):
    """Run a command inside the DX VM over SSH.

    Used by @plain_ssh DX scenarios. Distinct from qecore's 'Run and save command
    output' to avoid AmbiguousStep; also guarantees context.ssh_rc is populated.
    """
    _ssh(context, cmd)


@step('SSH command return code is "{code}"')
def ssh_return_code_is(context, code):
    actual = getattr(context, "ssh_rc", None)
    last_result = getattr(context, "last_ssh_result", None)
    stderr = getattr(last_result, "stderr", "") if last_result else ""
    assert actual == int(code), (
        f"Expected SSH return code {code}, got {actual}\n"
        f"stdout: {getattr(context, 'command_stdout', '')}\n"
        f"stderr: {stderr}"
    )


@step('SSH command output "is" "{expected}"')
def ssh_output_is(context, expected):
    actual = (getattr(context, "command_stdout", "") or "").strip()
    assert actual == expected, f"Expected '{expected}', got '{actual}'"


@step('Last command output does not contain "{text}"')
def output_does_not_contain(context, text):
    """Assert last command output does NOT contain the given text."""
    actual = getattr(context, 'command_stdout', '') or ''
    assert text not in actual, f"Output unexpectedly contains '{text}': {actual}"


@step('Last command output contains "{text}"')
def output_contains(context, text):
    """Assert last command output contains the given text."""
    actual = getattr(context, 'command_stdout', '') or ''
    assert text in actual, f"Output does not contain '{text}': {actual}"


@step('DX distrobox "{name}" can be created from "{image}"')
def dx_distrobox_can_be_created(context, name: str, image: str) -> None:
    cleanup_out, cleanup_rc = _ssh(
        context,
        f"distrobox rm --force {name}",
        timeout=60,
    )
    if cleanup_rc not in (0, 1) and 'No such container' not in cleanup_out:
        raise AssertionError(f'Unexpected distrobox cleanup failure: {cleanup_out}')

    create_out, create_rc = _ssh(
        context,
        f"distrobox create --name {name} --image {image} --yes",
        timeout=300,
    )
    assert create_rc == 0, f'distrobox create failed:\n{create_out}'

    list_out, list_rc = _ssh(context, 'distrobox list --no-color', timeout=60)
    assert list_rc == 0, f'distrobox list failed:\n{list_out}'
    assert name in list_out, f'distrobox {name!r} not found after create:\n{list_out}'


@step('DX distrobox "{name}" installs package "{package}"')
def dx_distrobox_installs_package(context, name: str, package: str) -> None:
    """Install a package inside the container and verify the binary exists."""
    install_out, install_rc = _ssh(
        context,
        f"distrobox enter --name {name} -- sudo dnf install -y {package}",
        timeout=600,
    )
    assert install_rc == 0, f'dnf install {package!r} in distrobox {name!r} failed:\n{install_out}'

    which_out, which_rc = _ssh(
        context,
        f"distrobox enter --name {name} -- which {package}",
        timeout=60,
    )
    assert which_rc == 0, (
        f'{package!r} not on PATH inside distrobox {name!r} after install:\n{which_out}'
    )


@step('DX distrobox "{name}" exports "{binary_path}" to the host')
def dx_distrobox_exports_binary_to_host(context, name: str, binary_path: str) -> None:
    """Export a binary from the container to ~/.local/bin on the host and verify."""
    export_out, export_rc = _ssh(
        context,
        f'distrobox enter --name {name} -- '
        f'distrobox-export --bin {binary_path} --export-path ~/.local/bin',
        timeout=60,
    )
    assert export_rc == 0, (
        f'distrobox-export of {binary_path!r} from {name!r} failed:\n{export_out}'
    )

    binary_name = binary_path.rsplit("/", 1)[-1]
    ls_out, ls_rc = _ssh(
        context,
        f"ls ~/.local/bin/{binary_name}",
        timeout=30,
    )
    assert ls_rc == 0, (
        f'Exported binary {binary_name!r} not found in ~/.local/bin on the host:\n{ls_out}'
    )
