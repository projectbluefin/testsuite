"""Shared SSH connection details resolution.

One source of truth for the SSH connection parameters used by the shared
SSH steps (``tests/shared/ssh_steps.py``), by suite-local helpers that run
commands on the VM (e.g. ``_flatpak`` in the software suite), and by suite
``environment.py`` hooks that probe the VM directly.

``ssh_argv(context)`` builds the canonical ``ssh`` argument vector from those
details so that no caller has to restate the transport policy (host-key
handling, connect timeout, port flag) inline.

``resolve_ssh_details(context)`` reads, in priority order:

1. Behave ``context`` attributes (``ssh_key``, ``vm_ip``, ``ssh_user``,
   ``ssh_port``) — set by ``populate_ssh_context`` in ``before_all``.
2. Behave userdata keys (``ssh_key``, ``vm_ip``/``host``, ``vm_user``/``user``,
   ``ssh_port``) — behave's ``userdata`` is a plain dict; on a mock context
   without userdata, attribute lookup falls through to step 3 automatically.
3. Environment variables (``SSH_KEY``/``SSH_KEY_PATH``, ``VM_IP``,
   ``VM_USER``/``SSH_USER``, ``SSH_PORT``/``VM_PORT``/``TMT_SSH_PORT``).
   ``TMT_SSH_PORT`` is read so tmt-provisioned lanes on a forwarded port do
   not silently connect to 22 — suite ``environment.py`` hooks resolve host,
   user and key from ``TMT_SSH_*`` but mostly never set ``context.ssh_port``.
4. Built-in defaults matching the runner container layout.

Because step 4 always yields a usable destination, a suite that never
populated its context cannot fail loudly any more. ``ssh_argv`` therefore logs
the resolved destination once per run and warns when *every* field came from
the built-in defaults — see ``log_resolved_ssh_target``.
"""

import os

DEFAULT_SSH_KEY = "/home/bluefin-test/.ssh/id_ed25519"
DEFAULT_VM_IP = "127.0.0.1"
DEFAULT_VM_USER = "bluefin-test"
DEFAULT_SSH_PORT = "22"

SOURCE_CONTEXT = "context"
SOURCE_USERDATA = "userdata"
SOURCE_ENVIRONMENT = "environment"
SOURCE_DEFAULT = "default"

_logged_targets = set()

def _first_value(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _pick(context_value, userdata_values, env_values, default):
    """Return ``(value, source)`` for one field, honouring the priority order."""
    if context_value:
        return context_value, SOURCE_CONTEXT
    for value in userdata_values:
        if value:
            return value, SOURCE_USERDATA
    for value in env_values:
        if value:
            return value, SOURCE_ENVIRONMENT
    return default, SOURCE_DEFAULT


def _userdata(context) -> dict:
    """Return behave userdata, or an empty dict when there is no context."""
    userdata = getattr(getattr(context, "config", None), "userdata", None)
    return userdata if hasattr(userdata, "get") else {}


def resolve_ssh_details_with_sources(context=None) -> dict:
    """Return ``{field: (value, source)}`` for the current run.

    ``source`` is one of ``SOURCE_CONTEXT``/``SOURCE_USERDATA``/
    ``SOURCE_ENVIRONMENT``/``SOURCE_DEFAULT`` so callers can tell a configured
    destination apart from the built-in runner fallback.
    """
    userdata = _userdata(context)
    return {
        "ssh_key": _pick(
            getattr(context, "ssh_key", ""),
            (userdata.get("ssh_key", ""), userdata.get("key", "")),
            (os.environ.get("SSH_KEY", ""), os.environ.get("SSH_KEY_PATH", "")),
            DEFAULT_SSH_KEY,
        ),
        "vm_ip": _pick(
            getattr(context, "vm_ip", ""),
            (userdata.get("vm_ip", ""), userdata.get("host", "")),
            (os.environ.get("VM_IP", ""),),
            DEFAULT_VM_IP,
        ),
        "ssh_user": _pick(
            getattr(context, "ssh_user", ""),
            (userdata.get("vm_user", ""), userdata.get("user", "")),
            (os.environ.get("VM_USER", ""), os.environ.get("SSH_USER", "")),
            DEFAULT_VM_USER,
        ),
        "ssh_port": _pick(
            getattr(context, "ssh_port", ""),
            (userdata.get("ssh_port", ""),),
            (
                os.environ.get("SSH_PORT", ""),
                os.environ.get("VM_PORT", ""),
                os.environ.get("TMT_SSH_PORT", ""),
            ),
            DEFAULT_SSH_PORT,
        ),
    }


def resolve_ssh_details(context=None) -> dict:
    """Return SSH connection details for the current run.

    Keys: ``ssh_key``, ``vm_ip``, ``ssh_user``, ``ssh_port`` (all strings).
    """
    return {
        field: value
        for field, (value, _source) in
        resolve_ssh_details_with_sources(context).items()
    }


def log_resolved_ssh_target(context=None) -> None:
    """Print the resolved SSH destination once per distinct target.

    ``resolve_ssh_details`` cannot fail loudly on a suite that never populated
    its context — it falls back to the runner defaults. Printing the resolved
    destination (and warning when *nothing* configured it) turns an otherwise
    silent connect failure against the wrong host into a diagnosable one.
    """
    resolved = resolve_ssh_details_with_sources(context)
    details = {field: value for field, (value, _s) in resolved.items()}
    destination = (
        f"{details['ssh_user']}@{details['vm_ip']}:{details['ssh_port']}"
    )
    signature = (destination, details["ssh_key"])
    if signature in _logged_targets:
        return
    _logged_targets.add(signature)
    sources = ",".join(
        f"{field}={source}" for field, (_v, source) in sorted(resolved.items())
    )
    print(
        f"SSH target: {destination} key={details['ssh_key']} ({sources})",
        flush=True,
    )
    if all(source == SOURCE_DEFAULT for _v, source in resolved.values()):
        print(
            "WARNING: no SSH connection details were configured — using "
            "built-in runner defaults. If this suite targets a VM, call "
            "tests.shared.ssh_config.populate_ssh_context(context) from "
            "before_all (or set VM_IP/VM_USER/SSH_KEY/SSH_PORT).",
            flush=True,
        )


def ssh_argv(context=None, *, connect_timeout: int = 10, quiet: bool = False) -> list[str]:
    """Return the canonical ``ssh`` argv prefix for the current run.

    Callers append the remote command:  ``subprocess.run(ssh_argv() + [cmd])``.
    This is the single place where SSH transport policy (host-key handling,
    connect timeout, port flag, destination) is expressed.

    ``quiet=True`` adds ``LogLevel=ERROR`` so ssh's own diagnostics do not leak
    into captured command output — set it for callers that previously built
    that option inline instead of restating it at every call site.
    """
    details = resolve_ssh_details(context)
    log_resolved_ssh_target(context)
    argv = [
        "ssh",
        "-i", details["ssh_key"],
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", f"ConnectTimeout={connect_timeout}",
    ]
    if quiet:
        argv += ["-o", "LogLevel=ERROR"]
    argv += [
        "-p", str(details["ssh_port"]),
        f"{details['ssh_user']}@{details['vm_ip']}",
    ]
    return argv


def populate_ssh_context(context) -> None:
    """Set the context attributes ``run_ssh`` requires.

    Suites whose steps star-import ``tests.shared.ssh_steps`` should call this
    from ``before_all`` (or set the attributes themselves). The shared steps no
    longer raise ``AttributeError`` when it is skipped: ``run_ssh`` builds its
    argv through ``ssh_argv(context)``, whose ``resolve_ssh_details`` falls back
    to userdata, environment and built-in defaults. So a suite that skips this
    call connects with *default* credentials instead of failing loudly (though
    ``ssh_argv`` logs the resolved destination and warns when every field is a
    built-in default) — call it to pin the resolved values once, in one place,
    for the whole run.
    """
    details = resolve_ssh_details(context)
    context.ssh_key = details["ssh_key"]
    context.vm_ip = details["vm_ip"]
    context.ssh_user = details["ssh_user"]
    context.ssh_port = details["ssh_port"]
