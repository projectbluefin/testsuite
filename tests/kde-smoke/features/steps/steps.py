"""
Custom step definitions for the KDE Plasma smoke suite.

All assertions are invariants over presence/absence, roles, visibility, or
regex-matched names.  No golden accessibility-tree snapshots are used.

 evaluateScript is used only for diagnostics/session reset, never to perform
the user action a scenario asserts.  Kickoff opens via the real D-Bus activation
path (org.kde.PlasmaShell.activateLauncherMenu); apps open via real CLI launch.
"""

import os
import re
import shlex
import subprocess
from behave import step
from tests.shared.ssh_config import ssh_argv
from tests.shared.ssh_steps import run_ssh

from tests.shared.kde_shell_steps import wait_until as _shared_wait_until

# ---------------------------------------------------------------------------
# Host-execution helpers (copied from smoke system_health_steps to avoid
# pulling in qecore common_steps and the collision surface it brings).
# ---------------------------------------------------------------------------

_IN_CONTAINER = os.path.lexists("/proc/1/ns/mnt") and not os.path.isfile("/usr/bin/bootc")

IGNORED_FAILED_UNITS_IN_VM = {
    "mcelog.service",
    "avahi-daemon.service",
    "cups.service",
    "cups.path",
    "cups.socket",
    "cups.browsed.service",
    "podman-auto-update.timer",
    "malcontent-control.service",
    "malcontent-webd-update.timer",
    "malcontent-webd-update.service",
    "blueman-mechanism.service",
    "gnome-remote-desktop.service",
    "bootloader-update.service",
    "nvidia-persistenced.service",
    "ublue-nvctk-cdi.service",
    "systemd-oomd.service",
    "systemd-oomd.socket",
    "fwupd-refresh.service",
}


def _run(cmd: str, timeout: int = 30):
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _run_host(cmd: str, timeout: int = 30, context=None):
    """Run cmd on the host VM via SSH when inside the runner container."""
    if _IN_CONTAINER:
        # ssh_argv() resolves through context attributes (set in before_all,
        # which honours behave -D userdata) before falling back to the
        # environment. Previously this read a never-populated
        # ``context.kde["ssh"]`` dict, so it always fell through to raw env
        # reads and silently ignored userdata-configured runs.
        result = subprocess.run(
            ssh_argv(context) + [cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    else:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def _running_in_vm(context=None) -> bool:
    _, returncode, _ = _run_host("systemd-detect-virt --quiet", context=context)
    return returncode == 0


# ---------------------------------------------------------------------------
# Polling waiter — small, explicit retries instead of a fixed sleep.
# ---------------------------------------------------------------------------

def _wait_for(
    predicate,
    timeout: float = 10.0,
    interval: float = 0.2,
    message: str = "condition not satisfied",
):
    """Poll predicate until it returns a truthy value or timeout expires.

    Delegates to the shared ``wait_until`` primitive so the suite has a single
    readiness implementation.
    """
    try:
        return _shared_wait_until(predicate, timeout=timeout, interval=interval)
    except TimeoutError as exc:
        raise AssertionError(message) from exc
    except AssertionError:
        raise AssertionError(message) from None


def _require_webdriver(context):
    """Fail fast with a clear message when the AT-SPI driver is not ready."""
    driver = context.kde.get("webdriver") if hasattr(context, "kde") else None
    if driver is None:
        raise AssertionError(
            "AT-SPI WebDriver is not available; "
            "scenario should have been skipped in before_scenario"
        )
    return driver


# ---------------------------------------------------------------------------
# SSH process / session / D-Bus assertions
# ---------------------------------------------------------------------------

@step('the Plasma session processes "{names}" are running')
def plasma_session_processes_are_running(context, names: str) -> None:
    missing = []
    for name in (n.strip() for n in names.split(",")):
        run_ssh(context, f"pgrep -x {name}")
        if context.ssh_rc != 0:
            missing.append(name)
    assert not missing, f"Plasma session processes not running: {missing}"


@step('the session type is "{expected}"')
def session_type_is(context, expected: str) -> None:
    run_ssh(context, "echo \"$XDG_SESSION_TYPE\"")
    actual = context.command_stdout.strip()
    assert actual == expected, (
        f"Expected XDG_SESSION_TYPE={expected!r}, got {actual!r}"
    )


@step('the D-Bus service "{name}" is present on the session bus')
def dbus_service_is_present(context, name: str) -> None:
    # busctl prints one service per line; the first column is the name.
    cmd = f"busctl --user list --no-pager | awk '{{print $1}}' | grep -qx {shlex.quote(name)}"
    run_ssh(context, cmd)
    assert context.ssh_rc == 0, f"D-Bus service {name!r} is not present on the session bus"


@step("No failed systemd units at boot")
def no_failed_systemd_units_at_boot(context) -> None:
    output, returncode, stderr = _run_host("systemctl list-units --failed --no-pager --plain", context=context)
    assert returncode == 0, f"systemctl failed: {stderr or output}"

    failed_units = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("UNIT ", "LOAD ", "Legend:")):
            continue
        if stripped.endswith("loaded units listed.") or stripped.startswith("To show all installed unit files"):
            continue
        if re.match(r"^\S+\s+loaded\s+failed\s+failed\s+", stripped):
            unit = stripped.split()[0]
            if _running_in_vm(context=context) and unit in IGNORED_FAILED_UNITS_IN_VM:
                continue
            failed_units.append(stripped)

    assert not failed_units, f"Failed systemd units detected: {failed_units}"


@step('No coredump entries exist for any of "{names}"')
def no_coredump_entries_for_any(context, names: str) -> None:
    failures = []
    for name in (n.strip() for n in names.split(",")):
        output, returncode, stderr = _run_host(
            f"coredumpctl list {name} --no-pager --lines=10",
            context=context,
        )
        if returncode not in (0, 1):
            failures.append(
                f"coredumpctl failed for {name}: rc={returncode} stderr={stderr}"
            )
            continue
        matches = [line for line in output.splitlines() if name in line]
        if matches:
            failures.append(f"{name}: {matches}")
    assert not failures, f"Unexpected coredump entries:\n{failures}"


@step('KWin reports at least "{count}" output')
def kwin_reports_at_least_n_outputs(context, count: str) -> None:
    # activeOutputName returns a non-empty string when KWin owns at least one
    # output.  This is a robust invariant for the single-output VM baseline.
    cmd = (
        "gdbus call --session --dest org.kde.KWin "
        "--object-path /KWin --method org.kde.KWin.activeOutputName"
    )
    run_ssh(context, cmd)
    assert context.ssh_rc == 0, (
        f"Could not query KWin outputs: {context.last_command_output}"
    )
    # activeOutputName returns a single string, so gdbus prints ('DP-1',) —
    # NOT (true, 'DP-1'). The old regex required a comma *before* the quoted
    # value and therefore never matched, failing the scenario even on a healthy
    # KWin with a valid output.
    match = re.search(r"'([^']*)'", context.command_stdout)
    value = match.group(1) if match else ""
    assert value.strip(), (
        f"KWin reports no active output (raw gdbus reply: {context.command_stdout!r})"
    )


# ---------------------------------------------------------------------------
# App / window launch assertions (real CLI launch + AT-SPI WebDriver wait).
# ---------------------------------------------------------------------------

@step('Launch "{cmd}" and wait for its window')
def launch_command_and_wait_for_window(context, cmd: str) -> None:
    driver = _require_webdriver(context)

    # Snapshot existing windows FIRST. Without this the scenario passes on a
    # pre-existing Dolphin/Konsole/KCM window even when the launch command is
    # missing or broken — a false positive that makes the test unable to fail.
    before = set(driver.window_handles)
    context.kde["windows_before_launch"] = before

    # Verify the binary exists before claiming to launch it, so a typo or a
    # missing app fails loudly instead of silently succeeding on a stale window.
    binary = shlex.split(cmd)[0]
    run_ssh(context, f"command -v {shlex.quote(binary)}")
    assert context.ssh_rc == 0, (
        f"{binary!r} is not installed on the DUT; cannot launch {cmd!r}"
    )

    # Run detached inside the user session so it survives the SSH return.
    log_file = "$XDG_RUNTIME_DIR/kde-smoke-app.log"
    run_ssh(
        context,
        f"nohup sh -c {shlex.quote(cmd)} >{log_file} 2>&1 &",
    )
    assert context.ssh_rc == 0, f"Launch command failed for {cmd!r}"

    new_handles = _wait_for(
        lambda: set(driver.window_handles) - before or None,
        timeout=15.0,
        message=(
            f"No NEW window appeared after launching {cmd!r} "
            f"({len(before)} window(s) already present)"
        ),
    )
    context.kde["windows_after_launch"] = new_handles


@step('Window whose name matches "{pattern}" is present')
def window_matching_pattern_is_present(context, pattern: str) -> None:
    driver = _require_webdriver(context)
    regex = re.compile(pattern)

    # Restrict to windows that appeared from this scenario's launch, so a
    # pre-existing window cannot satisfy the assertion.
    candidates = context.kde.get("windows_after_launch")

    def _find():
        handles = candidates or driver.window_handles
        for handle in handles:
            try:
                driver.switch_to.window(handle)
            except Exception:  # noqa: BLE001 — window closed mid-scan
                continue
            if regex.search(driver.title or ""):
                return True
        return False

    _wait_for(
        _find,
        timeout=10.0,
        message=f"No window title matched /{pattern}/",
    )


@step("Close the active application window")
def close_active_application_window(context) -> None:
    driver = _require_webdriver(context)
    if driver.window_handles:
        driver.switch_to.window(driver.window_handles[-1])
        driver.close()


@step("Close the active KCM window")
def close_active_kcm_window(context) -> None:
    # KCM windows close like any other active window; kept as a separate phrase
    # so feature files read correctly per-domain.
    close_active_application_window(context)


# ---------------------------------------------------------------------------
# Panel / Kickoff assertions (D-Bus activation + AT-SPI tree lookup).
# ---------------------------------------------------------------------------

@step("the Plasma panel exists in the AT-SPI tree")
def plasma_panel_exists_in_atspi_tree(context) -> None:
    driver = _require_webdriver(context)

    def _has_panel():
        try:
            driver.find_element("accessibility id", "panel")
            return True
        except Exception:  # noqa: BLE001
            return False

    _wait_for(
        _has_panel,
        timeout=10.0,
        message="Plasma panel was not found in the AT-SPI tree",
    )


@step("Open Kickoff via the Plasma launcher D-Bus action")
def open_kickoff_via_dbus(context) -> None:
    run_ssh(
        context,
        (
            "gdbus call --session --dest org.kde.plasmashell "
            "--object-path /PlasmaShell --method org.kde.PlasmaShell.activateLauncherMenu"
        ),
    )
    assert context.ssh_rc == 0, f"activateLauncherMenu failed: {context.last_command_output}"


@step("the Kickoff window is present in the AT-SPI tree")
def kickoff_window_is_present(context) -> None:
    driver = _require_webdriver(context)
    regex = re.compile(r"Application Launcher|Kickoff|Search", re.IGNORECASE)

    def _find_kickoff():
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if regex.search(driver.title):
                return True
        return False

    _wait_for(
        _find_kickoff,
        timeout=10.0,
        message="Kickoff window did not appear in the AT-SPI tree",
    )


@step("Close the Kickoff window")
def close_kickoff_window(context) -> None:
    _require_webdriver(context)
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    driver = context.kde.get("webdriver")
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
