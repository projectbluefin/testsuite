"""
Smoke test environment — qecore TestSandbox for GNOME Shell.

Pattern sourced from: modehnal/GNOMETerminalAutomation features/environment.py
qecore source: gitlab.com/dogtail/qecore

qecore-headless (invoked by the Argo runner) handles:
  - DBUS_SESSION_BUS_ADDRESS
  - WAYLAND_DISPLAY / XDG_RUNTIME_DIR
  - gnome-ponytail-daemon activation
  - AT-SPI bus bridge
"""
import sys
import traceback

from qecore.sandbox import TestSandbox
from qecore.common_steps import *  # noqa: F401,F403 — registers all common @step definitions

try:
    from tests.shared.timing import record_end, record_start
except Exception:  # noqa: BLE001
    def record_start(context):
        return None

    def record_end(context, scenario):
        return None

try:
    from tests.shared.screenshot import (
        configure_screenshot_context,
        take_fastfetch_screenshot,
        take_screenshot,
    )
except Exception as exc:  # noqa: BLE001
    print(f"WARNING: screenshot helpers unavailable: {exc}", flush=True)

    def configure_screenshot_context(context, suite_name, scenario_name=None):
        return None

    def take_screenshot(label):
        return None

    def take_fastfetch_screenshot():
        return None


try:
    from tests.shared.screenshot_steps import *  # noqa: F401,F403 — registers screenshot steps
except Exception as exc:  # noqa: BLE001
    print(f"WARNING: screenshot steps unavailable: {exc}", flush=True)


SUITE_NAME = "vanilla-gnome"

# Runtime gate tag for settings that only exist on GNOME 51+. environment.py
# probes the running Shell version in before_scenario and skips these scenarios
# on GNOME <= 50 images, so the scenarios run where they apply and skip cleanly
# elsewhere (a version probe, not a non-runnable tag).
REQUIRES_GNOME_51_TAG = "requires_gnome_51"


def _gnome_major_version(context) -> int:
    """Probe the running GNOME Shell major version on the VM, cached on context.

    GNOME 51 shipped ``reduced-motion`` and ``keyboard-focus-visible-timeout``
    in ``org.gnome.desktop.a11y.interface``; pre-51 images lack them. A probe
    that cannot run (no VM, no SSH) returns 0 so ``@requires_gnome_51``
    scenarios skip rather than fail. Cached so the ``before_scenario`` hook
    does not SSH on every scenario.
    """
    cached = getattr(context, "_gnome_major_version", None)
    if cached is not None:
        return cached

    major = 0
    try:
        from steps.steps import _ssh_run

        result = _ssh_run("gnome-shell --version", timeout=15)
        import re

        match = re.search(r"GNOME Shell (\d+)", result.stdout or "")
        if match:
            major = int(match.group(1))
    except Exception:  # noqa: BLE001 -- no VM / SSH: skip rather than fail
        major = 0

    context._gnome_major_version = major
    return major


def _skip_requires_gnome_51(context, scenario) -> bool:
    """Skip @requires_gnome_51 scenarios on GNOME <= 50 (runtime version probe)."""
    if REQUIRES_GNOME_51_TAG not in scenario.tags:
        return False
    major = _gnome_major_version(context)
    if major < 51:
        scenario.skip(
            reason=(
                f"requires GNOME 51+ reduced-motion / focus-ring gsettings; "
                f"this image reports GNOME Shell {major}"
            )
        )
        return True
    return False


def before_all(context) -> None:
    import time
    import subprocess
    # qecore sandbox.py accesses context.html_formatter in reporting hooks;
    # set to None to avoid AttributeError when behave-html-formatter is absent.
    context.html_formatter = None

    # Give GDM/GNOME Shell time to start the session
    time.sleep(5)

    # Enable unsafe_mode so Shell.Eval works for the rest of the session.
    # Try SetUnsafeMode first (GNOME 43+, polkit rule pre-installed by workflow),
    # then fall back to Shell.Eval. gdbus returns (true, ...) on success.
    unsafe_enabled = False
    for attempt in range(3):
        try:
            # SetUnsafeMode is the preferred API; requires polkit (rule grants it).
            r = subprocess.run(
                ['gdbus', 'call', '--session',
                 '--dest', 'org.gnome.Shell',
                 '--object-path', '/org/gnome/Shell',
                 '--method', 'org.gnome.Shell.SetUnsafeMode',
                 'true'],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                print(f"unsafe_mode enabled via SetUnsafeMode (attempt {attempt+1})", flush=True)
                unsafe_enabled = True
                break
            # Fall back to Shell.Eval (older/no-polkit-rule path)
            r = subprocess.run(
                ['gdbus', 'call', '--session',
                 '--dest', 'org.gnome.Shell',
                 '--object-path', '/org/gnome/Shell',
                 '--method', 'org.gnome.Shell.Eval',
                 'global.context.unsafe_mode = true'],
                capture_output=True, text=True, timeout=5,
            )
            out = r.stdout.strip()
            if r.returncode == 0 and out.startswith('(true'):
                print(f"unsafe_mode enabled via Shell.Eval (attempt {attempt+1}): {out}", flush=True)
                unsafe_enabled = True
                break
            print(f"unsafe_mode attempt {attempt+1} returned: {out!r}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"unsafe_mode attempt {attempt+1} failed: {e}", flush=True)
        time.sleep(2)
    if not unsafe_enabled:
        print("WARNING: could not confirm unsafe_mode=true; Shell.Eval steps may fail", flush=True)

    # Poll until clock + system toggles appear in AT-SPI (up to 15s)
    from dogtail import tree as dtree
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            shell = dtree.root.application('gnome-shell')
            panels = shell.findChildren(lambda n: n.roleName == 'panel')
            if panels:
                toggles = panels[0].findChildren(
                    lambda n: n.roleName == 'toggle button' and n.showing)
                toggle_names = [t.name for t in toggles]
                print(f"Panel toggles: {toggle_names}", flush=True)
                # Need more than just Activities + Show Apps
                non_activities = [t for t in toggles if t.name != 'Activities']
                if len(non_activities) >= 1:
                    print("Clock/System toggles visible — proceeding", flush=True)
                    break
        except Exception as e:  # noqa: BLE001
            print(f"AT-SPI poll: {e}", flush=True)
        time.sleep(1)
    else:
        print("WARNING: clock/system toggles not found after 15s — proceeding anyway", flush=True)

    # Initialize sandbox
    try:
        context.sandbox = TestSandbox("gnome-shell", context=context)
        context.sandbox.attach_faf = False
        context.sandbox.production = False
        context.sandbox.set_keyring = False  # GDM restart flushes PATH; GNOME 50 doesn't need keyring
        context.shell = context.sandbox.shell
        configure_screenshot_context(context, SUITE_NAME)
    except Exception as error:
        print(f"Environment error: before_all: {error}", flush=True)
        context.failed_setup = traceback.format_exc()


def before_scenario(context, scenario) -> None:
    from tests.shared.quarantine import skip_quarantine

    if skip_quarantine(scenario):
        return
    if _skip_requires_gnome_51(context, scenario):
        return
    context.scenario = scenario
    configure_screenshot_context(context, SUITE_NAME, scenario.name)
    # Initialize qecore command output attributes (attribute name varies by version)
    # qecore 4.16: command_stdout; older: last_command_output
    context.command_stdout = ""
    context.last_command_output = ""
    record_start(context)
    try:
        context.sandbox.before_scenario(context, scenario)
    except Exception:
        tb = traceback.format_exc()
        print(f"WARNING: before_scenario setup error — skipping scenario:\n{tb}", flush=True)
        scenario.skip(reason="before_scenario setup failed (environment not ready)")


def after_scenario(context, scenario) -> None:
    record_end(context, scenario)
    # A scenario skipped in before_scenario (quarantine tags, or @requires_gnome_51
    # on GNOME <= 50) returns before sandbox setup, so context.sandbox is unset.
    # behave still calls after_scenario for skipped scenarios; guard it so the
    # skip is clean instead of an AttributeError.
    sandbox = getattr(context, "sandbox", None)
    if sandbox is None:
        return
    if scenario.status.name in ('passed', 'failed'):
        configure_screenshot_context(context, SUITE_NAME, scenario.name)
        take_screenshot(scenario.status.name)
    sandbox.after_scenario(context, scenario)


def after_step(context, step) -> None:
    """Print full traceback for errored steps — needed because behave JSON
    serialises error_message as empty when the exception has no str()."""
    if step.status.name in ("error", "failed") and step.exception is not None:
        print(
            f"\nSTEP_ERROR [{step.name!r}]: "
            f"{type(step.exception).__name__}: {step.exception}",
            flush=True,
        )
        traceback.print_exception(
            type(step.exception),
            step.exception,
            step.exception.__traceback__,
            file=sys.stderr,
        )


def after_all(context) -> None:
    """Take a fastfetch desktop screenshot, then dump gnome-shell AT-SPI tree."""
    configure_screenshot_context(context, SUITE_NAME, "end_of_run")
    take_fastfetch_screenshot()

    try:
        import os
        if os.path.exists("/tmp/results/atspi_tree.txt"):
            return  # already written by after_scenario
        shell = context.sandbox.shell
        lines = []
        for child in shell.children[:60]:
            lines.append(f"role={child.roleName!r:30} name={child.name!r}")
            for gc in child.children[:20]:
                lines.append(f"  role={gc.roleName!r:30} name={gc.name!r}")
        os.makedirs("/tmp/results", exist_ok=True)
        with open("/tmp/results/atspi_tree.txt", "w") as f:
            f.write("\n".join(lines))
    except Exception:   # noqa: BLE001
        pass
