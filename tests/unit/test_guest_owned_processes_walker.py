"""Regression for the guest owned-process walker shared by the SJC and stock steps.

The walker is the python ``-c`` payload ``tests.shared.guest_owned_processes.guest_owned_processes``
invokes. Issue #919 originally passed the script through ``cmd.split()`` to
``ExtensionSession.command``, which runs ``subprocess.run(argv, ...)`` without
a shell. The single quotes inside the script became literal bytes the
interpreter saw and rejected with ``SyntaxError: unterminated string literal``;
with ``check=False`` the empty stdout produced ``[]`` and the assertion
silently passed -- a vacuous guard that could not catch a leaked helper.

The fix sends the script as a single argv element and lets the guest's
``python3 -c`` parse it as a file would. These tests pin that:

* the script string is syntactically valid Python;
* the argv shape passed to ``command`` is ``[python3, -c, <script>, <needle>]``,
  not a shell-tokenised string.

The walker logic itself (the /proc walk, the needle match, the print) runs
on the guest; we exercise the host-side glue by stubbing ``command``.
"""

from __future__ import annotations

import subprocess as _subprocess
from unittest.mock import Mock

import pytest

from tests.shared import guest_owned_processes


def _argv_for(command_mock):
    """Extract the argv the step passed to ``ExtensionSession.command``."""
    assert command_mock.call_count == 1, command_mock.call_args_list
    args, _ = command_mock.call_args
    return args[0]


@pytest.mark.parametrize("needle", ["sjc_price.py", "/usr/bin/curl"])
def test_walker_passes_a_python_invocation_with_four_positional_args(needle):
    """The script must reach ``python3`` as a single argv element, not as a
    shell tokenised string. ``subprocess.run`` without ``shell=True`` would
    otherwise feed every whitespace-separated byte to ``python3 -c`` and
    raise ``SyntaxError`` on the embedded single quotes -- exactly the
    vacuous-pass regression this test pins.
    """
    context = Mock()
    context.extension.command = Mock(
        return_value=_subprocess.CompletedProcess([], 0, "", "")
    )
    guest_owned_processes.guest_owned_processes(context, needle)
    argv = _argv_for(context.extension.command)
    assert argv[0] == "python3"
    assert argv[1] == "-c"
    assert isinstance(argv[2], str) and argv[2].strip(), (
        "the script must be a non-empty single argv element"
    )
    assert argv[3] == needle
    assert len(argv) == 4


def test_walker_script_is_valid_python():
    """The literal script the shared walker embeds must parse as Python; if a
    future refactor reintroduces a syntax error the walker would always
    return ``[]`` (the assertion it backs would silently pass).
    """
    compile(guest_owned_processes.WALKER_SCRIPT, "<guest-walker-script>", "exec")


def test_assert_no_guest_owned_processes_collects_every_needle():
    """Every needle must produce its own ``python3 -c`` invocation; the
    assertion must walk them all before failing so a leaked curl subprocess
    cannot hide behind a missing helper scan.
    """
    context = Mock()
    context.extension.command = Mock(
        side_effect=[
            _subprocess.CompletedProcess([], 0, "", ""),
            _subprocess.CompletedProcess([], 0, "1 curl\n", ""),
        ]
    )
    with pytest.raises(AssertionError, match="curl"):
        guest_owned_processes.assert_no_guest_owned_processes(
            context, ("stocks_fetch.py", "/usr/bin/curl")
        )
    assert context.extension.command.call_count == 2


def test_assert_no_guest_owned_processes_passes_when_empty():
    context = Mock()
    context.extension.command = Mock(
        return_value=_subprocess.CompletedProcess([], 0, "", "")
    )
    guest_owned_processes.assert_no_guest_owned_processes(
        context, ("sjc_price.py",)
    )
    context.extension.command.assert_called_once()


def test_walker_command_runs_with_check_true():
    """A non-zero exit from ``python3 -c`` (missing python3, syntax error,
    I/O error reading /proc) must surface as a real failure rather than
    masquerading as "no owned processes" via an empty stdout. ``check=False``
    used to swallow the return code; ``check=True`` does not, so the
    ``ExtensionSession.command`` call must pass ``check=True``.
    """
    context = Mock()
    context.extension.command = Mock(
        return_value=_subprocess.CompletedProcess([], 0, "", "")
    )
    guest_owned_processes.guest_owned_processes(context, "sjc_price.py")
    _args, kwargs = context.extension.command.call_args
    assert kwargs.get("check") is True, (
        "the walker must run with check=True so a failed guest probe "
        "cannot look like an empty result"
    )


def test_walker_propagates_a_failed_guest_probe():
    """When ``python3`` is missing in the guest or the script raises, the
    walker subprocess returns non-zero and the ``check=True`` call surfaces
    the ``CalledProcessError`` so the owning step fails fast instead of
    passing vacuously with ``[]``.
    """
    context = Mock()
    err = _subprocess.CalledProcessError(2, ["python3", "-c"])
    context.extension.command = Mock(side_effect=err)
    with pytest.raises(_subprocess.CalledProcessError):
        guest_owned_processes.guest_owned_processes(context, "sjc_price.py")

