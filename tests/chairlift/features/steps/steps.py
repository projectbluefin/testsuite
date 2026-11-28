"""Step definitions for the chairlift spike suite (projectbluefin/testsuite#1326).

Control Center (ChairLift) runs in the VM's GNOME session and behave runs in
the runner container, so every guest command goes back over SSH and the window
is read through AT-SPI by role and accessible name, never by coordinates.
"""

import json
import os
import shlex
import time
from pathlib import Path
from time import sleep

from behave import step

try:
    from dogtail import tree
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]

from tests.shared.app_support import (
    describe_subtree,
    detached_launch_command,
    launch_background,
    stop_app_instances,
)
from tests.shared.results_dir import resolve_results_dir
from tests.shared.ssh_steps import run_ssh

BREW_PREFIX = "/home/linuxbrew/.linuxbrew"
BREW = f"{BREW_PREFIX}/bin/brew"
# The image's own launcher (io.projectbluefin.chairlift.desktop) runs this path.
LAUNCHER = f"{BREW_PREFIX}/bin/chairlift-wrapper"
BINARY = f"{BREW_PREFIX}/bin/chairlift"
HELPER = "/usr/bin/chairlift-helper"
PROCESS = "chairlift"
APP_ID = "io.projectbluefin.chairlift"
WINDOW_TITLE = "Control Center"
# GTK4 publishes the program name; a build may publish the product name or app id.
A11Y_NAMES = {"chairlift", "control center", APP_ID}
FRAME_ROLES = {"frame", "filler"}
# A bare frame is what an app shows when its accessibility never started.
CONTENT_ROLES = {"list", "list box", "list item", "push button", "button", "label"}
LIST_ROLES = {"list", "list box"}
ROW_ROLES = {"list item", "table cell"}
SWITCH_ROLES = {"switch", "toggle button", "check box"}
# ChairLift's own order (test/e2e/features/lib/chairlift_atspi.py activate()).
SWITCH_ACTIONS = ("click", "activate", "press", "toggle")
SESSION = "source /tmp/session.env 2>/dev/null; "
POLL_INTERVAL = 0.25

# 20 minutes. Before the launcher exists, first boot unpacks the Homebrew
# tarball (400-500 MiB) and brew-preinstall, at first login, clones
# projectbluefin/tap, fetches Homebrew's formula index, then bundles
# bluefin-report.Brewfile (3 MB cask + the gh formula) and chairlift.Brewfile
# (14 MB cask + the cosign formula): roughly 100 MB over QEMU's user-mode
# network, by single-threaded Ruby on 4 vCPUs. The unit also retries three
# times, 30 s apart. That clock starts at login, not here, and the harness
# spends minutes loading the runner container first, so this normally returns
# at once; the timings it prints are measured from boot.
INSTALL_DEADLINE = 1200
INSTALL_POLL = 10
WINDOW_TIMEOUT = 90
ROW_TIMEOUT = 60
ACTION_TIMEOUT = 120
STATE_TIMEOUT = 20

# Written by e2e.yml for this suite only; see the comment there.
PASSWORD_FILE = "/var/home/bluefin-test/.config/testsuite/chairlift-admin-password"
AGENT_SCRIPT = str(Path(__file__).resolve().parents[2] / "polkit_tty_agent.py")
AGENT_STOP_FILE = "/tmp/chairlift-polkit-agent.stop"
AGENT_LIFETIME = 420
TIMER = "uupd.timer"
RESUME_TIMER = "uupd-resume.timer"
# The same systemctl steps as chairlift-helper auto-updates-enable/-disable.
RESTORE = {
    "on": f"sudo -n systemctl unmask {TIMER} && sudo -n systemctl enable --now {TIMER} "
          f"&& sudo -n systemctl unmask {RESUME_TIMER}",
    "off": f"sudo -n systemctl disable --now {TIMER} && sudo -n systemctl mask {TIMER} "
           f"&& sudo -n systemctl mask --now {RESUME_TIMER}",
}

BREW_PROBE = (
    f"{SESSION}"
    'up=$(cut -d. -f1 /proc/uptime); echo "uptime_s=$up"; '
    f"if [ -x {LAUNCHER} ] && [ -x {BINARY} ]; then echo launcher=yes; "
    f'echo "installed_s=$(( $(stat -c %Y {LAUNCHER}) - $(date +%s) + up ))"; '
    "else echo launcher=no; fi; "
    f"[ -x {BREW} ] && echo brew=yes || echo brew=no; "
    "[ -e /etc/.linuxbrew ] && echo setup_marker=yes || echo setup_marker=no; "
    f"echo \"cask=$(ls {BREW_PREFIX}/Caskroom/chairlift 2>/dev/null | tr '\\n' ' ')\"; "
    "systemctl show brew-setup.service -p LoadState,ActiveState,SubState,Result,UnitFileState,"
    "InactiveExitTimestampMonotonic,InactiveEnterTimestampMonotonic | sed 's/^/setup./'; "
    "systemctl --user show brew-preinstall.service -p LoadState,ActiveState,SubState,Result,ConditionResult,"
    "UnitFileState,Job,NRestarts,InactiveExitTimestampMonotonic,ActiveEnterTimestampMonotonic "
    "| sed 's/^/preinstall./'"
)
BREW_DIAGNOSTICS = (
    f"{SESSION}"
    f"echo '== who owns the Homebrew prefix'; ls -ldn /home/linuxbrew {BREW_PREFIX} {BREW} 2>&1; "
    "echo '== brew-setup.service'; systemctl status brew-setup.service --no-pager -l -n 0 2>&1; "
    "journalctl -b -u brew-setup.service --no-pager -n 30 2>&1; "
    "echo '== brew-preinstall.service (user)'; "
    "systemctl --user status brew-preinstall.service ublue-user-setup.service --no-pager -l -n 0 2>&1; "
    "journalctl --user -b -u brew-preinstall.service --no-pager -n 60 2>&1"
)
MANUAL_START = (
    f"{SESSION}systemctl --user reset-failed brew-preinstall.service 2>/dev/null; "
    "systemctl --user start --no-block brew-preinstall.service"
)
PREREQUISITES = (
    f"[ -r {PASSWORD_FILE} ] && [ -s {PASSWORD_FILE} ] && echo password_file=yes || echo password_file=no; "
    f"echo \"password_mode=$(stat -c '%a %U' {PASSWORD_FILE} 2>/dev/null)\"; "
    'for tool in pkttyagent pkexec python3; do command -v "$tool" >/dev/null && echo "$tool=yes" || echo "$tool=no"; done; '
    f"[ -x {HELPER} ] && echo helper=yes || echo helper=no; "
    "id -nG | tr ' ' '\\n' | grep -qx wheel && echo wheel=yes || echo wheel=no; "
    # The first three characters only: the hash scheme, never the hash.
    "echo \"shadow_scheme=$(sudo -n awk -F: -v u=\"$(id -un)\" '$1==u{print substr($2,1,3)}' /etc/shadow 2>/dev/null)\""
)


def _key_values(text: str) -> dict[str, str]:
    """Parse ``key=value`` lines; anything else is ignored."""
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            values[key.strip()] = value.strip()
    return values


def _poll(what: str, timeout: float, probe):
    """Return ``probe()``'s first truthy result within ``timeout`` seconds.

    Same contract as the software suite's ``_poll``: one monotonic deadline,
    and an exception counts as "not yet" because the AT-SPI tree changes while
    it is read.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = probe()
            if result:
                return result
            last = "probe returned nothing"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"{what} not reached within {timeout}s: {last}")
        sleep(POLL_INTERVAL)


def _name(node) -> str:
    return (getattr(node, "name", "") or "").strip()


# --- Scenario 1: Homebrew setup --------------------------------------------


def brew_state(context) -> dict[str, str]:
    out, _ = run_ssh(context, BREW_PROBE, timeout=60)
    return _key_values(out)


def describe_brew_state(state: dict[str, str]) -> str:
    def unit(prefix: str) -> str:
        return "/".join(state.get(f"{prefix}.{key}", "?") for key in ("LoadState", "ActiveState", "SubState", "Result"))

    return (
        f"launcher={state.get('launcher', '?')} brew={state.get('brew', '?')} "
        f"brew-setup={unit('setup')} ({state.get('setup.UnitFileState', '?')}) "
        f"brew-preinstall={unit('preinstall')} ({state.get('preinstall.UnitFileState', '?')}, "
        f"condition={state.get('preinstall.ConditionResult', '?')}, "
        f"restarts={state.get('preinstall.NRestarts', '?')})"
    )


def needs_manual_start(state: dict[str, str]) -> bool:
    """True when Homebrew is unpacked but brew-preinstall is neither running nor queued.

    That is what a first login looks like when the unit's condition
    (``ConditionPathExists=<brew>``) was checked before brew-setup finished,
    or when the unit used up its three restarts.
    """
    return (
        state.get("launcher") != "yes"
        and state.get("brew") == "yes"
        and state.get("setup_marker") == "yes"
        and state.get("setup.ActiveState") == "inactive"
        and state.get("preinstall.LoadState") == "loaded"
        and state.get("preinstall.ActiveState") in {"inactive", "failed"}
        and not state.get("preinstall.Job")
    )


def blocked_reason(state: dict[str, str]) -> str:
    """Why waiting cannot install Control Center, or an empty string."""
    setup = state.get("setup.LoadState")
    preinstall = state.get("preinstall.LoadState")
    if setup == "masked":
        return (
            "brew-setup.service is masked, so this run did not use the spike's e2e.yml, which lifts that "
            "mask for the chairlift suite only: dispatch manual.yml with --ref set to the spike branch"
        )
    if setup == "not-found":
        return "this image ships no brew-setup.service"
    if state.get("setup.ActiveState") == "failed":
        return "brew-setup.service failed"
    if state.get("brew") == "no" and state.get("setup.ActiveState") == "inactive":
        return "brew-setup.service is not running and has not unpacked Homebrew"
    if preinstall in {"masked", "not-found"}:
        return f"brew-preinstall.service is {preinstall} for the test user"
    if state.get("preinstall.ActiveState") == "active":
        return "brew-preinstall.service finished without installing the launcher"
    return ""


def _boot_offset(state: dict[str, str], key: str) -> str:
    value = state.get(key, "")
    return f"boot+{int(value) // 1_000_000}s" if value.isdigit() and int(value) else "never"


def install_report(state: dict[str, str], waited: float, manual_start: str) -> str:
    installed = state.get("installed_s", "")
    minutes = f"{int(installed) / 60:.1f} min" if installed.lstrip("-").isdigit() else "? min"
    return (
        f"launcher linked at boot+{installed or '?'}s ({minutes} after boot), "
        f"cask version(s): {state.get('cask', '').strip() or '?'}; "
        f"brew-setup ran {_boot_offset(state, 'setup.InactiveExitTimestampMonotonic')} to "
        f"{_boot_offset(state, 'setup.InactiveEnterTimestampMonotonic')}; "
        f"brew-preinstall last started {_boot_offset(state, 'preinstall.InactiveExitTimestampMonotonic')}, "
        f"finished {_boot_offset(state, 'preinstall.ActiveEnterTimestampMonotonic')} "
        f"(now {state.get('preinstall.ActiveState', '?')}/{state.get('preinstall.SubState', '?')}, "
        f"restarts {state.get('preinstall.NRestarts', '?')}); "
        f"this step waited {waited:.0f}s, at uptime {state.get('uptime_s', '?')}s; "
        f"manual start needed: {'YES, from ' + manual_start if manual_start else 'no'}"
    )


def brew_diagnostics(context) -> str:
    out, _ = run_ssh(context, BREW_DIAGNOSTICS, timeout=60)
    return out[-8000:]


@step("Homebrew setup has installed the Control Center launcher")
def homebrew_setup_installs_control_center(context) -> None:
    started = time.monotonic()
    manual_start = ""
    last = ""
    while True:
        state = brew_state(context)
        summary = describe_brew_state(state)
        waited = time.monotonic() - started
        if summary != last:
            print(f"[chairlift] {waited:.0f}s: {summary}", flush=True)
            last = summary
        if state.get("launcher") == "yes":
            break
        blocked = blocked_reason(state)
        if not blocked and manual_start and needs_manual_start(state):
            blocked = "brew-preinstall.service stopped again after being started by hand"
        assert not blocked, f"Control Center cannot be installed here: {blocked}. State: {summary}\n{brew_diagnostics(context)}"
        if not manual_start and needs_manual_start(state):
            # Recorded as a failure below; started so the later scenarios can still answer.
            manual_start = summary
            print("[chairlift] brew-preinstall is not running and not queued; starting it once by hand", flush=True)
            run_ssh(context, MANUAL_START)
        if waited >= INSTALL_DEADLINE:
            raise AssertionError(
                f"Control Center was not installed within {INSTALL_DEADLINE}s of this step starting. "
                f"Last state: {summary}\n{brew_diagnostics(context)}"
            )
        sleep(INSTALL_POLL)
    report = install_report(state, time.monotonic() - started, manual_start)
    print(f"CHAIRLIFT-SPIKE Q1: {report}", flush=True)
    assert not manual_start, (
        "Homebrew setup did not install Control Center by itself: brew-preinstall.service had to be "
        f"started by hand. {report}\n{brew_diagnostics(context)}"
    )


def print_brew_summary(context) -> None:
    """End-of-run line: by then the whole preinstall bundle may have finished."""
    state = brew_state(context)
    print(f"CHAIRLIFT-SPIKE Q1 (end of run): {install_report(state, 0, '')}", flush=True)


# --- Scenario 2: the window -------------------------------------------------


@step("Control Center is installed")
def control_center_is_installed(context) -> None:
    _, rc = run_ssh(context, f"test -x {LAUNCHER} && test -x {BINARY}")
    assert rc == 0, (
        f"{LAUNCHER} is missing: Homebrew setup did not install the Control Center cask "
        "(see the first scenario of this feature)"
    )


def _launch(context, *args: str, env: dict[str, str] | None = None) -> None:
    """Start Control Center through the shared launcher (a transient user unit).

    The app is single-instance and takes --dry-run from the process that owns
    the window, so any running instance is stopped first. The arguments ride
    in the "command" target, which the container lane passes to the guest
    shell as written.
    """
    assert tree is not None, "AT-SPI unavailable: dogtail is not importable in this environment"
    stop_app_instances(PROCESS)
    context.chairlift_launched = time.monotonic()
    context.chairlift_launch_target = launch_background(
        (("command", " ".join((LAUNCHER, *args))),), env=env,
    )


@step("Launch Control Center in preview mode")
def launch_control_center_in_preview_mode(context) -> None:
    _launch(context, "--dry-run")


def _app():
    apps = list(tree.root.applications())
    for app in apps:
        if _name(app).casefold() in A11Y_NAMES:
            return app
    raise LookupError(f"Control Center is not an AT-SPI application; found {sorted(_name(a) for a in apps)}")


def _window():
    frames = [n for n in _app().children if n.roleName in FRAME_ROLES and n.showing]
    for frame in frames:
        if _name(frame) == WINDOW_TITLE and frame.findChildren(lambda n: n.roleName in CONTENT_ROLES):
            return frame
    raise LookupError(
        f"no populated {WINDOW_TITLE!r} window; visible frames: {[(_name(f), f.roleName) for f in frames]}"
    )


def _label(node) -> str:
    """The node's own name, else the first name beneath it (AdwActionRow titles)."""
    own = _name(node)
    if own:
        return own
    named = node.findChildren(lambda n: bool(_name(n)))
    return _name(named[0]) if named else ""


def sidebar_pages(window) -> list[str]:
    """Titles of the sidebar rows, read without navigating. Best effort."""
    try:
        for sidebar in window.findChildren(lambda n: n.roleName in LIST_ROLES and _name(n) == "Navigation"):
            return [label for label in (_label(row) for row in sidebar.children) if label]
    except Exception as exc:  # noqa: BLE001
        print(f"[chairlift] sidebar not read: {exc}", flush=True)
    return []


def app_id_is_owned(context) -> bool:
    """A GApplication owns its application id as a session-bus name."""
    out, _ = run_ssh(
        context,
        f"{SESSION}gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus "
        f"--method org.freedesktop.DBus.NameHasOwner {APP_ID}",
    )
    return out.strip() == "(true,)"


@step("Control Center window is accessible")
def control_center_window_is_accessible(context) -> None:
    window = _poll(f"Visible {WINDOW_TITLE} window", WINDOW_TIMEOUT, _window)
    waited = time.monotonic() - context.chairlift_launched
    assert app_id_is_owned(context), f"no process owns the session-bus name {APP_ID}"
    context.chairlift_window_report = (
        f"window {WINDOW_TITLE!r} (role {window.roleName!r}) shown {waited:.1f}s after launch; "
        f"AT-SPI application name {_name(_app())!r}; {APP_ID} is owned on the session bus; "
        f"sidebar pages: {sidebar_pages(window)}"
    )
    print(f"[chairlift] {context.chairlift_window_report}", flush=True)


def gui_pid(context) -> int:
    out, _ = run_ssh(context, f'pgrep -u "$(id -u)" -x {PROCESS}')
    pids = out.split()
    assert len(pids) == 1 and pids[0].isdigit(), f"expected one {PROCESS} process, found {pids}"
    return int(pids[0])


def process_arguments(context, pid: int) -> list[str]:
    out, _ = run_ssh(context, f"tr '\\0' '\\n' < /proc/{pid}/cmdline")
    return out.splitlines()


@step("Control Center is running in preview mode")
def control_center_is_running_in_preview_mode(context) -> None:
    arguments = process_arguments(context, gui_pid(context))
    assert "--dry-run" in arguments, f"Control Center is not in preview mode: {arguments}"
    print(f"CHAIRLIFT-SPIKE Q2: preview mode ({' '.join(arguments)}): {context.chairlift_window_report}", flush=True)


def _closed(context) -> bool:
    _, rc = run_ssh(context, f'pgrep -u "$(id -u)" -x {PROCESS}')
    return rc != 0


@step("Close Control Center")
def close_control_center(context) -> None:
    stop_app_instances(PROCESS)
    _poll("Control Center process exited", 15, lambda: _closed(context))


def dump_tree(context, label: str) -> str | None:
    """Save Control Center's accessibility tree to the results, for the next author."""
    if tree is None:
        return None
    try:
        text = describe_subtree(_app(), max_lines=600)
    except Exception as exc:  # noqa: BLE001
        text = f"(Control Center not in the AT-SPI tree: {exc})"
    path = os.path.join(resolve_results_dir(context), f"chairlift_atspi_tree_{label}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return path


# --- Scenario 3: one admin action through the password prompt ---------------


def classify_timer(is_enabled: str, is_active: str) -> str:
    """ChairLift's own reading of uupd.timer (internal/autoupdate Classify)."""
    enabled = is_enabled.strip()
    if enabled in ("", "not-found"):
        return "unavailable"
    if enabled in ("enabled", "enabled-runtime") and is_active.strip() == "active":
        return "on"
    return "off"


def timer_readings(context) -> dict[str, str]:
    out, _ = run_ssh(
        context,
        f'echo "enabled=$(systemctl is-enabled {TIMER} 2>/dev/null)"; '
        f'echo "active=$(systemctl is-active {TIMER} 2>/dev/null)"; '
        f'echo "resume=$(systemctl is-enabled {RESUME_TIMER} 2>/dev/null)"',
    )
    return _key_values(out)


def timer_state(context) -> str:
    readings = timer_readings(context)
    return classify_timer(readings.get("enabled", ""), readings.get("active", ""))


def expected_action(state: str) -> str:
    return "auto-updates-disable" if state == "on" else "auto-updates-enable"


def journal_path(context) -> str:
    # In the results directory, so the journal is uploaded with the run.
    return os.path.join(resolve_results_dir(context), "chairlift-action-journal.jsonl")


def agent_paths(context) -> tuple[str, str]:
    results = resolve_results_dir(context)
    return (
        os.path.join(results, "chairlift-polkit-agent.status"),
        os.path.join(results, "chairlift-polkit-agent.txt"),
    )


def read_journal(context) -> list[dict]:
    out, _ = run_ssh(context, f"cat {shlex.quote(journal_path(context))} 2>/dev/null")
    entries = []
    for line in out.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # a line still being written; the next read has it
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def outcomes(entries: list[dict], action: str) -> list[dict]:
    return [e for e in entries if e.get("action") == action and "outcome" in e]


def attempts(entries: list[dict], action: str) -> list[dict]:
    return [e for e in entries if e.get("action") == action and "would_run" in e]


def agent_status(context) -> list[str]:
    out, _ = run_ssh(context, f"cat {shlex.quote(agent_paths(context)[0])} 2>/dev/null")
    return out.splitlines()


def agent_prompts(context) -> int:
    return sum(1 for line in agent_status(context) if line.startswith("answered "))


def agent_registered(context) -> bool:
    lines = agent_status(context)
    errors = [line for line in lines if line.startswith("error")]
    if errors:
        raise LookupError(errors[-1])
    return "registered" in lines


def auth_evidence(context) -> str:
    """What the agent saw and what Control Center journalled, for a failure message."""
    status, transcript = agent_paths(context)
    out, _ = run_ssh(
        context,
        f"echo '== polkit agent status'; cat {shlex.quote(status)} 2>&1; "
        f"echo '== pkttyagent transcript (password replaced)'; cat {shlex.quote(transcript)} 2>&1; "
        f"echo '== action journal'; cat {shlex.quote(journal_path(context))} 2>&1",
    )
    return (
        f"{out[-6000:]}\nIf the agent answered no prompt, GNOME Shell's own dialog probably took it: "
        "see this scenario's failure screenshot."
    )


@step("The admin password prompt can be answered")
def admin_password_prompt_can_be_answered(context) -> None:
    out, _ = run_ssh(context, PREREQUISITES)
    found = _key_values(out)
    missing = [key for key in ("password_file", "pkttyagent", "pkexec", "python3", "helper", "wheel")
               if found.get(key) != "yes"]
    assert not missing, (
        f"this guest cannot answer an admin password prompt, missing: {missing}. The throwaway password "
        "is written by e2e.yml for the chairlift suite only, so the run must use a ref whose e2e.yml has "
        f"that step. Probe output:\n{out}"
    )
    state = timer_state(context)
    if state == "unavailable":
        context.scenario.skip(f"{TIMER} is not installed, so Control Center hides the Automatic Updates switch")
        return
    context.chairlift_initial = state
    context.chairlift_flips = []
    print(
        f"[chairlift] password file mode/owner {found.get('password_mode')!r}, shadow scheme "
        f"{found.get('shadow_scheme')!r}; automatic updates start {state}: {timer_readings(context)}",
        flush=True,
    )


@step("Launch Control Center with the action journal")
def launch_control_center_with_the_action_journal(context) -> None:
    path = journal_path(context)
    run_ssh(context, f"rm -f {shlex.quote(path)}")
    _launch(context, env={"CHAIRLIFT_ACTION_JOURNAL": path})


@step("Start the password agent for Control Center")
def start_the_password_agent(context) -> None:
    pid = gui_pid(context)
    arguments = process_arguments(context, pid)
    assert "--dry-run" not in arguments, f"the live scenario started Control Center in preview mode: {arguments}"
    status, transcript = agent_paths(context)
    run_ssh(context, f"rm -f {shlex.quote(status)} {shlex.quote(transcript)} {AGENT_STOP_FILE}")
    command = " ".join(shlex.quote(part) for part in (
        "python3", AGENT_SCRIPT, "--process", str(pid), "--password-file", PASSWORD_FILE,
        "--status", status, "--transcript", transcript, "--stop-file", AGENT_STOP_FILE,
        "--timeout", str(AGENT_LIFETIME),
    ))
    run_ssh(context, detached_launch_command(command))
    context.chairlift_agent_started = True
    _poll("pkttyagent registered for the Control Center process", 40, lambda: agent_registered(context))
    print(f"[chairlift] pkttyagent --process {pid} registered", flush=True)


def stop_password_agent(context) -> None:
    """Ask the agent to exit (it also stops by itself after AGENT_LIFETIME)."""
    if not getattr(context, "chairlift_agent_started", False):
        return
    run_ssh(context, f"touch {AGENT_STOP_FILE}")
    try:
        _poll("polkit agent stopped", 10,
              lambda: any(line.startswith(("stopped", "error")) for line in agent_status(context)))
    finally:
        context.chairlift_agent_started = False


def _row_switch(window, title: str):
    """The switch in the innermost row titled ``title`` (role plus name, no coordinates)."""
    for labelled in window.findChildren(lambda n: _name(n) == title and n.showing):
        node = labelled
        for _ in range(8):  # a title label sits a few levels below its row
            if node is None:
                break
            if node.roleName in ROW_ROLES:
                switches = node.findChildren(lambda n: n.roleName in SWITCH_ROLES and n.showing)
                if switches:
                    return switches[0]
                break
            node = node.parent
    raise LookupError(f"no showing switch in a row titled {title!r}")


def activate(node) -> str:
    """Operate a control through its AT-SPI action, as an assistive technology would."""
    available = node.actions or {}
    for action in SWITCH_ACTIONS:
        if action in available:
            node.do_action_named(action)
            return action
    raise AssertionError(f"{node.roleName} {_name(node)!r} has no primary action; has {sorted(available)}")


@step('Flip the "{row}" switch')
def flip_the_switch(context, row: str) -> None:
    before = timer_state(context)
    assert before in ("on", "off"), f"{TIMER} is {before}: {timer_readings(context)}"

    def ready():
        switch = _row_switch(_window(), row)
        return switch if switch.sensitive and bool(switch.checked) == (before == "on") else None

    switch = _poll(f"sensitive {row!r} switch showing {before}", ROW_TIMEOUT, ready)
    context.chairlift_flips.append({
        "action": expected_action(before),
        "prompts_before": agent_prompts(context),
        "started": time.monotonic(),
    })
    used = activate(switch)
    print(f"[chairlift] flipped {row!r} from {before} with the AT-SPI action {used!r}", flush=True)


def _assert_flip_succeeded(context, index: int, label: str) -> None:
    flip = context.chairlift_flips[index]
    action = flip["action"]
    try:
        settled = _poll(f"action journal outcome for {action}", ACTION_TIMEOUT,
                        lambda: outcomes(read_journal(context), action))
    except AssertionError as error:
        raise AssertionError(f"{error}\n{auth_evidence(context)}") from None
    outcome = settled[-1]
    asked = attempts(read_journal(context), action)
    prompts = agent_prompts(context) - flip["prompts_before"]
    print(
        f"CHAIRLIFT-SPIKE {label}: {action} outcome={outcome.get('outcome')} exit_code={outcome.get('exit_code')} "
        f"{time.monotonic() - flip['started']:.1f}s after the click; password prompts pkttyagent answered for it: "
        f"{prompts}; would_run={asked[-1].get('would_run') if asked else None}; executed={outcome.get('executed')}",
        flush=True,
    )
    assert outcome.get("outcome") == "succeeded", f"{action} did not succeed: {outcome}\n{auth_evidence(context)}"
    assert asked and asked[-1].get("would_run") == ["pkexec", HELPER, action] and asked[-1].get("suppressed") == "no", (
        f"{action} was not journalled as a real pkexec run of {HELPER}: {asked}"
    )
    if index == 0:
        assert prompts >= 1, (
            f"{action} succeeded but pkttyagent answered no password prompt, so something else authorized it "
            f"(GNOME Shell's agent, a kept authorization or a rule).\n{auth_evidence(context)}"
        )


@step("The action journal records the change as succeeded")
def journal_records_the_change(context) -> None:
    _assert_flip_succeeded(context, 0, "Q3")


@step("The action journal records the undo as succeeded")
def journal_records_the_undo(context) -> None:
    # auth_admin_keep may let the undo through without a second prompt; the count is printed.
    _assert_flip_succeeded(context, 1, "Q3 undo")


def _assert_timer_state(context, want: str) -> None:
    try:
        _poll(f"{TIMER} reading {want}", STATE_TIMEOUT, lambda: timer_state(context) == want)
    except AssertionError as error:
        raise AssertionError(f"{error}; systemd says {timer_readings(context)}") from None
    print(f"[chairlift] system state: automatic updates {want}: {timer_readings(context)}", flush=True)


@step("Automatic updates are flipped on the system")
def automatic_updates_are_flipped(context) -> None:
    _assert_timer_state(context, "off" if context.chairlift_initial == "on" else "on")


@step("Automatic updates are back as they were on the system")
def automatic_updates_are_back(context) -> None:
    _assert_timer_state(context, context.chairlift_initial)


def restore_automatic_updates(context) -> None:
    """Cleanup: put uupd.timer back with sudo if the scenario stopped half way."""
    initial = getattr(context, "chairlift_initial", None)
    if initial not in RESTORE or timer_state(context) == initial:
        return
    out, rc = run_ssh(context, RESTORE[initial])
    if rc != 0 or timer_state(context) != initial:
        raise AssertionError(f"could not restore automatic updates to {initial} (rc={rc}): {out} {timer_readings(context)}")
    print(f"WARNING: [chairlift] the scenario left automatic updates changed; restored to {initial} with sudo", flush=True)
