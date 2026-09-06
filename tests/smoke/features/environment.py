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
import os
import sys
from tests.shared.results_dir import resolve_results_dir
import traceback

import re as _re
import subprocess as _subprocess

try:
    from qecore.sandbox import TestSandbox
    from qecore.common_steps import *  # noqa: F401,F403 — registers all common @step definitions
    _QECORE_AVAILABLE = True
except Exception as _qecore_exc:  # noqa: BLE001
    # Runner containers based on fedora-minimal lack the GTK/dogtail typelibs
    # needed by qecore. Smoke tests run headless CLI checks via nsenter/SSH and
    # do not need AT-SPI — allow behave to load without a GNOME environment.
    print(f"WARNING: qecore unavailable ({_qecore_exc}); sandbox disabled", flush=True)
    TestSandbox = None  # type: ignore[assignment,misc]
    _QECORE_AVAILABLE = False

from steps.app_support import launch_target_available

# ── qecore keyboard key mapping patch ────────────────────────────────────────
# qecore 4.16 keyboard_key_combo_input builds uinput key names as
# f"KEY_{modifier.upper()}" — e.g. KEY_CONTROL, KEY_ALT — which don't exist in
# python-uinput.  The valid evdev names are KEY_LEFTCTRL, KEY_LEFTALT, etc.
# We normalise the combo string before it reaches qecore so qecore sees the
# canonical modifier names it can translate correctly.
_MODIFIER_ALIAS = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "super": "super",
    "meta": "super",
}
_EVDEV_KEY_ALIAS = {
    "control": "leftctrl",
    "ctrl": "leftctrl",
    "alt": "leftalt",
    "shift": "leftshift",
    "super": "leftmeta",
    "meta": "leftmeta",
}


def _normalize_key_combo(combo: str) -> str:
    """Rewrite a key combo string so qecore / python-uinput can resolve it.

    Transforms e.g.  ``<Control><Shift>n``  →  ``<leftctrl><leftshift><n>``
    so that qecore's ``KEY_{name.upper()}`` lookup hits ``KEY_LEFTCTRL`` etc.
    Bare trailing keys that are not already wrapped in ``<>`` are wrapped.
    """
    # Replace each <modifier> with its evdev-canonical equivalent.
    def _repl(m: _re.Match) -> str:
        name = m.group(1).lower()
        return f"<{_EVDEV_KEY_ALIAS.get(name, name)}>"

    result = _re.sub(r"<([^>]+)>", _repl, combo)

    # If there is a bare trailing character (not inside <>), wrap it.
    # e.g. "<leftctrl><leftshift>n" → "<leftctrl><leftshift><n>"
    if result and result[-1] != ">" and not result.endswith(">"):
        tail = result.rstrip()
        last_close = tail.rfind(">")
        if last_close != -1:
            prefix = tail[:last_close + 1]
            bare = tail[last_close + 1:]
            if bare:
                result = prefix + "".join(f"<{c}>" for c in bare)
    return result


try:
    import qecore.common_steps as _qecore_cs

    if hasattr(_qecore_cs, "keyboard_key_combo_input"):
        _orig_keyboard_key_combo_input = _qecore_cs.keyboard_key_combo_input

        def _patched_keyboard_key_combo_input(combo):
            return _orig_keyboard_key_combo_input(_normalize_key_combo(combo))

        _qecore_cs.keyboard_key_combo_input = _patched_keyboard_key_combo_input
except Exception as _e:  # noqa: BLE001
    print(f"WARNING: could not patch qecore keyboard_key_combo_input: {_e}", flush=True)


def _has_wifi_interface() -> bool:
    """Return True if at least one wireless network interface is visible to the kernel."""
    try:
        r = _subprocess.run(
            ["ip", "link", "show", "type", "wifi"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return False

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


SUITE_NAME = "smoke"


OPTIONAL_SCENARIO_TARGETS = {
    "firefox": (
        ("command", "firefox"),
        ("desktop", "firefox.desktop"),
        ("desktop", "org.mozilla.firefox.desktop"),
        ("flatpak", "org.mozilla.firefox"),
    ),
    "calculator": (
        ("command", "gnome-calculator"),
        ("desktop", "org.gnome.Calculator.desktop"),
    ),
    "text_editor": (
        ("command", "gnome-text-editor"),
        ("desktop", "org.gnome.TextEditor.desktop"),
        ("desktop", "org.gnome.TextEditor.Devel.desktop"),
    ),
    "ptyxis": (
        ("command", "ptyxis"),
        ("desktop", "org.gnome.Ptyxis.desktop"),
    ),
    "extensions_app": (
        ("desktop", "org.gnome.Extensions.desktop"),
    ),
}


def before_all(context) -> None:
    import time
    import subprocess

    # Shared ssh_steps (star-imported by offline_boot_steps) dereference
    # context.ssh_key/ssh_user/vm_ip — populate them from userdata/env.
    from tests.shared.ssh_config import populate_ssh_context
    populate_ssh_context(context)

    # Give GDM/GNOME Shell time to start the session
    time.sleep(5)

    # Verify Shell.Eval is available.  unsafe_mode should already be set by the
    # gnome-shell extension installed in e2e.yml (GNOME 47+ removed SetUnsafeMode).
    # gdbus returns (true, 'true') when unsafe_mode=true, (false, '') when false.
    # When running inside the runner container, the systemd user session bus is
    # cgroup-restricted — forward the gdbus call to the VM via SSH instead.
    from steps.app_support import _IN_CONTAINER, _ssh_run

    for attempt in range(3):
        try:
            if _IN_CONTAINER:
                r = _ssh_run(
                    "source /tmp/session.env 2>/dev/null; "
                    "gdbus call --session "
                    "--dest org.gnome.Shell "
                    "--object-path /org/gnome/Shell "
                    "--method org.gnome.Shell.Eval "
                    "'global.context.unsafe_mode = true'"
                )
                rc = r.returncode
                out = r.stdout.strip()
            else:
                r = subprocess.run(
                    ['gdbus', 'call', '--session',
                     '--dest', 'org.gnome.Shell',
                     '--object-path', '/org/gnome/Shell',
                     '--method', 'org.gnome.Shell.Eval',
                     'global.context.unsafe_mode = true'],
                    capture_output=True, text=True, timeout=5,
                )
                rc = r.returncode
                out = r.stdout.strip()
            if rc == 0 and out.startswith('(true'):
                print(f"unsafe_mode enabled (attempt {attempt+1}): {out}", flush=True)
                break
            print(f"unsafe_mode attempt {attempt+1} returned: {out!r}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"unsafe_mode attempt {attempt+1} failed: {e}", flush=True)
        time.sleep(2)
    else:
        print("WARNING: could not confirm unsafe_mode=true; Shell.Eval steps may fail", flush=True)

    if not _QECORE_AVAILABLE:
        print("Sandbox disabled: qecore/dogtail not available in this environment", flush=True)
        context.optional_scenario_availability = {}
        configure_screenshot_context(context, SUITE_NAME)
        return

    # Poll until clock + system toggles appear in AT-SPI (up to 15s)
    from dogtail import tree as dtree

    # GNOME 50 changed the Nautilus AT-SPI application name from "nautilus"
    # to "Files".  Patch tree.root.application so that any lookup for
    # "nautilus" also tries "Files" and "org.gnome.Nautilus" as fallbacks.
    # This fixes qecore steps such as `Left click "X" "Y" in "nautilus"`.
    _orig_root_application = dtree.root.application

    def _nautilus_aliased_application(name, *args, **kwargs):
        try:
            return _orig_root_application(name, *args, **kwargs)
        except Exception:  # noqa: BLE001
            if name.lower() == "nautilus":
                for alt in ("Files", "org.gnome.Nautilus"):
                    try:
                        return _orig_root_application(alt, *args, **kwargs)
                    except Exception:  # noqa: BLE001
                        pass
            raise

    dtree.root.application = _nautilus_aliased_application
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

    # Detect image family so variant-tagged scenarios can be skipped on the
    # wrong image. Match only the image name component (last path segment before
    # ':' or '@') — the org "projectbluefin" must not be treated as an image name.
    image_ref = os.environ.get("IMAGE", "")
    if image_ref:
        _lower = image_ref.lower()
        _name = _lower.split("/")[-1].split(":")[0].split("@")[0]
        context.is_bluefin_image = "bluefin" in _name or "bazzite" in _name
        context.is_dakota_image = "dakota" in _name
    else:
        context.is_bluefin_image = True  # default to Bluefin when IMAGE is unset
        context.is_dakota_image = False

    try:
        context.optional_scenario_availability = {
            tag: launch_target_available(targets)
            for tag, targets in OPTIONAL_SCENARIO_TARGETS.items()
        }
        print(
            f"Optional app availability: {context.optional_scenario_availability}",
            flush=True,
        )
        context.sandbox = TestSandbox("gnome-shell", context=context)
        context.sandbox.attach_faf = False
        context.sandbox.production = False
        context.sandbox.set_keyring = False  # GDM restart flushes PATH; GNOME 50 doesn't need keyring
        context.shell = context.sandbox.shell
        configure_screenshot_context(context, SUITE_NAME)
        # Bluefin's first-run welcome modal can cover the desktop even after
        # the GNOME session is otherwise ready. Dismiss it through its visible
        # accessibility control instead of killing unrelated GNOME processes.
        from steps.steps import _dismiss_welcome_dialog
        _dismiss_welcome_dialog()
    except Exception as error:
        print(f"Environment error: before_all: {error}", flush=True)
        context.failed_setup = traceback.format_exc()


def before_scenario(context, scenario) -> None:
    from tests.shared.quarantine import skip_quarantine

    # Initialize qecore command output attributes and screenshot context before
    # any early-return paths so that after_scenario/after_step never sees missing attrs.
    context.html_formatter = None
    context.command_stdout = ""
    context.last_command_output = ""

    if skip_quarantine(scenario):
        return

    # Skip Wi-Fi tests when no wireless hardware is present (e.g. QEMU VMs).
    if "wifi" in set(getattr(scenario, "effective_tags", scenario.tags)):
        if not _has_wifi_interface():
            try:
                scenario.skip("No Wi-Fi interface detected — skipping @wifi scenario")
            except TypeError:
                scenario.skip()
            print(f"Skipping {scenario.name}: no Wi-Fi interface detected", flush=True)
            return

    scenario_tags = set(getattr(scenario, "effective_tags", scenario.tags))

    # Skip @bluefin scenarios on non-Bluefin images (e.g. dakota).
    if not getattr(context, "is_bluefin_image", True):
        if "bluefin" in scenario_tags:
            try:
                scenario.skip(
                    f"Skipping @bluefin scenario on non-Bluefin image "
                    f"(IMAGE={os.environ.get('IMAGE', 'unknown')})"
                )
            except TypeError:
                scenario.skip()
            print(f"Skipping {scenario.name}: @bluefin on non-Bluefin image", flush=True)
            return

    if not getattr(context, "is_dakota_image", False):
        if "dakota_only" in scenario_tags:
            try:
                scenario.skip(
                    f"Skipping @dakota_only scenario on non-Dakota image "
                    f"(IMAGE={os.environ.get('IMAGE', 'unknown')})"
                )
            except TypeError:
                scenario.skip()
            print(f"Skipping {scenario.name}: @dakota_only on non-Dakota image", flush=True)
            return

    if getattr(context, 'failed_setup', None):
        try:
            scenario.skip(reason=context.failed_setup)
        except TypeError:
            scenario.skip()
        print(f"Skipping {scenario.name}: failed_setup set", flush=True)
        return
    context.scenario = scenario
    configure_screenshot_context(context, SUITE_NAME, scenario.name)
    record_start(context)
    availability = getattr(context, "optional_scenario_availability", {})
    for tag, present in availability.items():
        feature_name = os.path.basename(getattr(getattr(scenario, "feature", None), "filename", ""))
        if feature_name == "firefox.feature":
            scenario_tags.add("firefox")
        if tag in scenario_tags and not present:
            try:
                scenario.skip(f"{tag} app is not installed in this image")
            except TypeError:
                scenario.skip()
            print(f"Skipping {scenario.name}: {tag} app is not installed in this image", flush=True)
            return
    sandbox = getattr(context, "sandbox", None)
    if sandbox is None:
        return
    try:
        sandbox.before_scenario(context, scenario)
    except SystemExit:
        # qecore-headless detected unrecoverable AT-SPI errors (e.g. GNOME 50
        # removed SetUnsafeMode).  Mark setup as failed so all remaining
        # scenarios are skipped and after_scenario doesn't call the broken sandbox.
        context.failed_setup = "qecore-headless startup failed: unrecoverable headless errors"
        context.scenario.skip(reason=context.failed_setup)
        return
    except (RuntimeError, AttributeError) as e:
        # sandbox.before_scenario calls overview_action("hide") → click() → window_id
        # → ponytail_helper.get_window_id().  When gnome-ponytail-daemon is
        # unavailable get_ponytail_interface() returns None and get_window_id raises
        # AttributeError: 'NoneType' has no attribute 'window_list'.  Log and
        # continue — steps that genuinely need ponytail will fail individually.
        print(f"WARNING: sandbox.before_scenario ponytail error (continuing): {type(e).__name__}: {e}", flush=True)
    except Exception:
        tb = traceback.format_exc()
        print(f"HOOK_ERROR in before_scenario:\n{tb}", flush=True)
        raise


def after_scenario(context, scenario) -> None:
    if getattr(context, 'failed_setup', None):
        return
    # Ensure display scaling tests leave the session at 1.0 scale and restore
    # any gsettings changes, even when the scenario itself failed.
    try:
        from steps.display_scaling_steps import _restore_display_scale
        _restore_display_scale(context)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: display scaling cleanup failed: {e}", flush=True)
    record_end(context, scenario)
    if scenario.status.name in ('passed', 'failed'):
        configure_screenshot_context(context, SUITE_NAME, scenario.name)
        take_screenshot(scenario.status.name)
    sandbox = getattr(context, "sandbox", None)
    if sandbox is not None:
        try:
            sandbox.after_scenario(context, scenario)
        except (RuntimeError, SystemExit) as e:
            print(f"WARNING: sandbox.after_scenario failed: {e}", flush=True)


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
    if getattr(context, 'failed_setup', None):
        return
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
