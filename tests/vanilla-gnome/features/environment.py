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
from tests.shared.results_dir import resolve_results_dir
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
    if scenario.status.name in ('passed', 'failed'):
        configure_screenshot_context(context, SUITE_NAME, scenario.name)
        take_screenshot(scenario.status.name)
    context.sandbox.after_scenario(context, scenario)


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
        results_dir = resolve_results_dir(context)
        if os.path.exists(os.path.join(results_dir, "atspi_tree.txt")):
            return  # already written by after_scenario
        shell = context.sandbox.shell
        lines = []
        for child in shell.children[:60]:
            lines.append(f"role={child.roleName!r:30} name={child.name!r}")
            for gc in child.children[:20]:
                lines.append(f"  role={gc.roleName!r:30} name={gc.name!r}")
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, "atspi_tree.txt"), "w") as f:
            f.write("\n".join(lines))
    except Exception:   # noqa: BLE001
        pass
