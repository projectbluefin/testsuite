"""FlatPark remote and Compass (org.tunaos.compass) lifecycle steps.

Every command runs on the VM through the shared ``run_ssh`` helper; the
install path uses ``Run long SSH command`` from the feature because the
extra-data payload (a ~71 MB AppImage) is fetched from GitHub at install time,
far beyond ``_flatpak``'s 10 s timeout.
"""
from __future__ import annotations

import json
import shlex
import time

from behave import step

from tests.shared.ssh_steps import run_ssh

try:  # behave loads the suite steps directory as a top-level ``steps`` package
    from steps.flatpak_permissions_steps import context_values, parse_flatpak_context
except ImportError:  # pytest / direct module import
    from tests.software.features.steps.flatpak_permissions_steps import (
        context_values,
        parse_flatpak_context,
    )

COMPASS_APP_ID = "org.tunaos.compass"
# Written before the uninstall to prove `flatpak uninstall` without
# --delete-data keeps ~/.var/app; cleanup removes only this file.
COMPASS_DATA_MARKER = "~/.var/app/org.tunaos.compass/config/compass/testsuite-uninstall-marker"

# Filesystem grants that expose the user's home directory, directly or via host root.
_HOME_GRANTS = {"home", "~", "host", "host-root"}


def parse_flatpak_info(text: str) -> dict[str, str]:
    """Parse ``flatpak info`` ``Key: value`` lines (keys are right-aligned)."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and " " not in key.strip():
            fields.setdefault(key.strip(), value.strip())
    return fields


def remote_filters(text: str) -> dict[str, str]:
    """Map remote name → filter path from ``flatpak remotes --columns=name,filter``."""
    filters: dict[str, str] = {}
    for line in text.splitlines():
        name, _, path = line.partition("\t")
        if name.strip():
            filters[name.strip()] = path.strip()
    return filters


def home_grants(filesystems: list[str]) -> list[str]:
    """Return the filesystem grants that reach the home directory.

    ``!home`` is a revocation, not a grant; ``home:ro`` still exposes home.
    """
    return [
        item for item in filesystems
        if not item.startswith("!") and item.split(":", 1)[0] in _HOME_GRANTS
    ]


def _checked(context, cmd: str, timeout: int = 60) -> str:
    stdout, rc = run_ssh(context, cmd, timeout=timeout)
    result = getattr(context, "last_ssh_result", None)
    assert rc == 0, (
        f"`{cmd}` exited {rc}\nstdout: {stdout}\n"
        f"stderr: {getattr(result, 'stderr', '')}"
    )
    return stdout


def _remove_compass(context) -> None:
    """Uninstall the system Compass if present and drop the data marker."""
    _checked(context, f"rm -f {COMPASS_DATA_MARKER}")
    _, rc = run_ssh(context, f"flatpak info --system {COMPASS_APP_ID} >/dev/null 2>&1")
    if rc == 0:
        _checked(
            context,
            f"sudo -n flatpak uninstall -y --system {COMPASS_APP_ID}",
            timeout=300,
        )


@step("the VM is x86_64, the only arch FlatPark builds Compass for")
def vm_is_x86_64_for_compass(context) -> None:
    # FlatPark's manifest pins both extra-data sources to `only-arches: x86_64`,
    # so on aarch64 there is no ref to install: skip, do not fail.
    arch = _checked(context, "uname -m")
    if arch != "x86_64":
        context.scenario.skip(f"FlatPark ships org.tunaos.compass for x86_64 only, VM is {arch!r}")


@step('the image enables GNOME Shell extension "{uuid}" by default')
def image_enables_shell_extension_by_default(context, uuid: str) -> None:
    # The memory backend ignores the user's dconf, so this reads the compiled
    # schema default (common's zz0-bluefin-modifications override, where the
    # image ships it). Images that do not enable it skip: the default differs
    # across the Bluefin family and by common pin.
    enabled = _checked(context, "GSETTINGS_BACKEND=memory gsettings get org.gnome.shell enabled-extensions")
    if f"'{uuid}'" not in enabled:
        context.scenario.skip(f"image does not enable {uuid} by default: {enabled}")


@step("Compass is absent now and removed again when the scenario ends")
def compass_absent_with_cleanup(context) -> None:
    _remove_compass(context)
    context.add_cleanup(_remove_compass, context)


@step('Flatpak system remote "{name}" uses filter "{path}"')
def flatpak_system_remote_uses_filter(context, name: str, path: str) -> None:
    filters = remote_filters(
        _checked(context, "flatpak remotes --system --columns=name,filter:f")
    )
    assert name in filters, f"System remote {name!r} not configured: {sorted(filters)}"
    assert filters[name] == path, (
        f"System remote {name!r} filter is {filters[name]!r}, expected {path!r}"
    )
    _checked(context, f"test -f {path}")


@step('Flatpak system app "{app_id}" reports origin "{origin}", branch "{branch}" and arch "{arch}"')
def flatpak_system_app_reports_ref(context, app_id: str, origin: str, branch: str, arch: str) -> None:
    fields = parse_flatpak_info(_checked(context, f"flatpak info --system {app_id}"))
    actual = {key: fields.get(key) for key in ("Origin", "Branch", "Arch")}
    expected = {"Origin": origin, "Branch": branch, "Arch": arch}
    assert actual == expected, f"flatpak info --system {app_id}: {actual}, expected {expected}"


def _permissions(context, app_id: str) -> str:
    return _checked(context, f"flatpak info --system --show-permissions {app_id}")


@step('Flatpak system app "{app_id}" permission "{section}" sets "{key}" to "{value}"')
def flatpak_system_app_permission_sets(context, app_id: str, section: str, key: str, value: str) -> None:
    output = _permissions(context, app_id)
    actual = parse_flatpak_context(output).get(section, {}).get(key)
    assert actual == value, (
        f"[{section}] {key} is {actual!r} for {app_id}, expected {value!r}:\n{output}"
    )


@step('Flatpak system app "{app_id}" filesystem permissions include "{grant}"')
def flatpak_system_app_filesystems_include(context, app_id: str, grant: str) -> None:
    output = _permissions(context, app_id)
    assert grant in context_values(output, "filesystems"), (
        f"{app_id} lacks filesystem grant {grant!r}:\n{output}"
    )


@step('Flatpak system app "{app_id}" has no home filesystem grant')
def flatpak_system_app_has_no_home_grant(context, app_id: str) -> None:
    output = _permissions(context, app_id)
    grants = home_grants(context_values(output, "filesystems"))
    assert not grants, f"{app_id} grants home access via {grants}:\n{output}"


# The engine IPC socket, passed as COMPASS_SOCKET (compass v0.28.3 cli.rs uses it
# verbatim). $XDG_RUNTIME_DIR/app/<id> is the one runtime directory Flatpak
# shares between instances of an app, so a second `flatpak run` reaches the
# engine the first one started; the default $XDG_RUNTIME_DIR/compass is
# per-sandbox.
_COMPASS_SOCKET = "$XDG_RUNTIME_DIR/app/org.tunaos.compass/testsuite-ipc.sock"
# Session bus, Wayland display and XDG_RUNTIME_DIR of the logged-in GNOME session.
_IN_SESSION = ". /tmp/session.env && "
_COMPASS_RUN = (
    f'{_IN_SESSION}flatpak run --env=COMPASS_SOCKET="{_COMPASS_SOCKET}" {COMPASS_APP_ID}'
)


def _compass_running(context) -> bool:
    # Only a successful `flatpak ps` says anything: an SSH (255) or flatpak
    # failure must fail the check, not read as "Compass exited".
    output = _checked(context, "flatpak ps --columns=application")
    apps = {line.strip() for line in output.splitlines()}
    return COMPASS_APP_ID in apps


# The engine runs as a transient unit of the user's systemd manager, not inside
# the SSH login session. Dakota's logind keeps systemd's built-in
# KillUserProcesses=yes (its /etc/systemd/logind.conf shows
# `#KillUserProcesses=yes`; Utah's shows `no`), so anything started from an SSH
# command dies when that command's session closes: run 41219770747 left an empty
# serve log and ping never answered, while Utah passed. A unit also releases
# run_ssh's pipes at once (a plain `&` held them until the 60 s timeout).
COMPASS_UNIT = "testsuite-compass-serve"
COMPASS_SERVE_LOG = "/tmp/compass-serve.log"
_COMPASS_LAUNCH = (
    f"{_IN_SESSION}systemd-run --user --collect --expand-environment=no --unit={COMPASS_UNIT} "
    f"-p StandardOutput=truncate:{COMPASS_SERVE_LOG} -p StandardError=inherit "
    f"sh -c {shlex.quote(f'{_COMPASS_RUN} serve --no-hotkey')}"
)
_COMPASS_DIAGNOSTICS = (
    ". /tmp/session.env; "
    f"echo '== systemctl --user show {COMPASS_UNIT}'; "
    f"systemctl --user show -p ActiveState -p SubState -p Result -p ExecMainStatus {COMPASS_UNIT}; "
    f"echo '== {COMPASS_SERVE_LOG}'; cat {COMPASS_SERVE_LOG}; "
    "echo '== flatpak ps'; flatpak ps --columns=instance,pid,application; "
    "echo \"== $XDG_RUNTIME_DIR/app/org.tunaos.compass\"; "
    "ls -la \"$XDG_RUNTIME_DIR/app/org.tunaos.compass\"; "
    "echo '== logind KillUserProcesses'; busctl get-property org.freedesktop.login1 "
    "/org/freedesktop/login1 org.freedesktop.login1.Manager KillUserProcesses"
)


def _stop_compass(context) -> None:
    run_ssh(context, f"{_COMPASS_RUN} shutdown")
    run_ssh(context, f"{_IN_SESSION}systemctl --user stop {COMPASS_UNIT}")
    if _compass_running(context):
        _checked(context, f"flatpak kill {COMPASS_APP_ID}")


def _compass_diagnostics(context) -> str:
    stdout, _ = run_ssh(context, f"{{ {_COMPASS_DIAGNOSTICS}; }} 2>&1")
    return stdout


@step("the Compass engine started from the Flatpak in the GNOME session answers ping")
def compass_engine_runs_in_session(context) -> None:
    # `serve --no-hotkey` is the engine without the Super+Space portal prompt.
    context.add_cleanup(_stop_compass, context)
    _checked(context, _COMPASS_LAUNCH, timeout=30)
    deadline = time.monotonic() + 90
    while True:
        out, rc = run_ssh(context, f"{_COMPASS_RUN} ping")
        if rc == 0:
            break
        if time.monotonic() >= deadline:
            stderr = getattr(getattr(context, "last_ssh_result", None), "stderr", "")
            raise AssertionError(
                f"compass ping never answered (rc {rc})\nstdout: {out}\nstderr: {stderr}\n"
                + _compass_diagnostics(context)
            )
        time.sleep(3)
    # ipc.rs: "engine alive on {socket}: protocol v{N}, pid {pid}"
    assert out.startswith("engine alive on ") and "/app/org.tunaos.compass/testsuite-ipc.sock: protocol v" in out, out
    assert _compass_running(context), "ping answered but flatpak ps lists no Compass instance"


@step("Compass shuts down when asked and its Flatpak instance exits")
def compass_shuts_down(context) -> None:
    _checked(context, f"{_COMPASS_RUN} shutdown")
    deadline = time.monotonic() + 30
    while _compass_running(context):
        assert time.monotonic() < deadline, (
            "Compass still running 30 s after `compass shutdown`\n" + _compass_diagnostics(context)
        )
        time.sleep(2)


def _compass_query(context, text: str) -> list[str]:
    """Entrypoint ids of the running engine's application hits for ``text``.

    v0.28.3 `query --json` prints the ranked hits; an application's id is
    `applications:<desktop id>` (serve.rs app_hit), as upstream's own VM gate
    (packaging/vmtest/checks.sh `flatpak-apps`) asserts.
    """
    out = _checked(context, f"{_COMPASS_RUN} query --json --provider applications {shlex.quote(text)}")
    return [hit["id"] for hit in json.loads(out)]


@step('Compass search finds desktop app "{desktop_id}" by its name')
def compass_search_finds_desktop_app(context, desktop_id: str) -> None:
    # The host's entry, which the sandbox reads at /run/host/usr through
    # --filesystem=host-os:ro (compass-xdg SANDBOX_HOST_ROOTS).
    line = _checked(context, f"grep -m1 '^Name=' /usr/share/applications/{desktop_id}.desktop")
    name = line.removeprefix("Name=")
    ids = _compass_query(context, name)
    assert f"applications:{desktop_id}" in ids, f"`compass query {name!r}` found {ids}"


# A host desktop entry the launch link names. Compass indexes the user's
# ~/.local/share/applications (--filesystem=xdg-data/applications:ro) and
# launches entries with `flatpak-spawn --host` (compass-platform-linux
# launch.rs), so the marker it touches appears on the host.
_PROBE_ID = "testsuite-compass-probe"
_PROBE_NAME = "Testsuite Compass Probe"
_APPLICATIONS_DIR = "~/.local/share/applications"
_PROBE_DESKTOP = f"{_APPLICATIONS_DIR}/{_PROBE_ID}.desktop"
_PROBE_MARKER = "/tmp/testsuite-compass-probe-launched"
_PROBE_ENTRY = (
    f"[Desktop Entry]\nType=Application\nName={_PROBE_NAME}\n"
    f"Exec=/usr/bin/touch {_PROBE_MARKER}\nTerminal=false\n"
)
# GIO resolves x-scheme-handler/compass from the Flatpak exports in the
# session's XDG_DATA_DIRS, which flatpak's environment generator supplies.
_SESSION_DATA_DIRS = (
    "XDG_DATA_DIRS=$(/usr/lib/systemd/user-environment-generators/60-flatpak "
    "| sed -n 's/^XDG_DATA_DIRS=//p')"
)


def _remove_probe(context, created_dir: bool) -> None:
    _checked(context, f"rm -f {_PROBE_DESKTOP} {_PROBE_MARKER}")
    if created_dir:
        _checked(context, f"rmdir {_APPLICATIONS_DIR}")


@step("a desktop entry for Compass to launch exists until the scenario ends")
def compass_probe_entry_exists(context) -> None:
    # Before `flatpak run`: Flatpak binds the xdg-data/applications grant only
    # if the directory exists, and a fresh test user may not have it yet.
    created = _checked(context, f"test -d {_APPLICATIONS_DIR} || {{ mkdir -p {_APPLICATIONS_DIR} && echo created; }}")
    context.add_cleanup(_remove_probe, context, created == "created")
    _checked(context, f"rm -f {_PROBE_MARKER} && printf %s {shlex.quote(_PROBE_ENTRY)} > {_PROBE_DESKTOP}")


@step("a compass:// launch link opened by the desktop runs that entry on the host through Compass")
def compass_launch_link_runs_desktop_entry(context) -> None:
    ids = _compass_query(context, _PROBE_NAME)
    assert f"applications:{_PROBE_ID}" in ids, f"Compass did not index {_PROBE_DESKTOP}: {ids}"
    # `gio open` runs the exported org.tunaos.compass.UrlHandler.desktop
    # (`compass deeplink %u`); flatpak passes COMPASS_SOCKET into the sandbox,
    # so the handler reaches this engine, which parses the launch link
    # (compass://launch/<provider>/<entrypoint>) and launches the entry. gio
    # exits 0 even when the handler fails, so only the marker proves the
    # launch. Polling inside the command keeps the SSH session, and so gio's
    # child, alive on Dakota, whose logind kills a closed session's processes.
    url = f"compass://launch/applications/{_PROBE_ID}"
    out, rc = run_ssh(
        context,
        f'{_IN_SESSION}export COMPASS_SOCKET="{_COMPASS_SOCKET}" {_SESSION_DATA_DIRS} && '
        f"gio open {url} && for _ in $(seq 60); do test -e {_PROBE_MARKER} && exit 0; sleep 0.5; done; exit 1",
        timeout=60,
    )
    assert rc == 0, (
        f"opening {url} never ran the probe entry (rc {rc}): {out}\n" + _compass_diagnostics(context)
    )
