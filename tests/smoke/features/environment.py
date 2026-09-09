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

try:
    from steps.app_support import launch_target_available
except ImportError:
    from tests.smoke.features.steps.app_support import launch_target_available

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


_EV_KEY = 1
_KEY_LEFTSHIFT = (1, 42)

# Evdev keycodes for ASCII characters: (event_tuple, shifted)
_CHAR_TO_EVDEV = {
    # Lowercase
    "a": ((1, 30), False), "b": ((1, 48), False), "c": ((1, 46), False),
    "d": ((1, 32), False), "e": ((1, 18), False), "f": ((1, 33), False),
    "g": ((1, 34), False), "h": ((1, 35), False), "i": ((1, 23), False),
    "j": ((1, 36), False), "k": ((1, 37), False), "l": ((1, 38), False),
    "m": ((1, 50), False), "n": ((1, 49), False), "o": ((1, 24), False),
    "p": ((1, 25), False), "q": ((1, 16), False), "r": ((1, 19), False),
    "s": ((1, 31), False), "t": ((1, 20), False), "u": ((1, 22), False),
    "v": ((1, 47), False), "w": ((1, 17), False), "x": ((1, 45), False),
    "y": ((1, 21), False), "z": ((1, 44), False),
    # Uppercase
    "A": ((1, 30), True), "B": ((1, 48), True), "C": ((1, 46), True),
    "D": ((1, 32), True), "E": ((1, 18), True), "F": ((1, 33), True),
    "G": ((1, 34), True), "H": ((1, 35), True), "I": ((1, 23), True),
    "J": ((1, 36), True), "K": ((1, 37), True), "L": ((1, 38), True),
    "M": ((1, 50), True), "N": ((1, 49), True), "O": ((1, 24), True),
    "P": ((1, 25), True), "Q": ((1, 16), True), "R": ((1, 19), True),
    "S": ((1, 31), True), "T": ((1, 20), True), "U": ((1, 22), True),
    "V": ((1, 47), True), "W": ((1, 17), True), "X": ((1, 45), True),
    "Y": ((1, 21), True), "Z": ((1, 44), True),
    # Digits
    "1": ((1, 2), False), "2": ((1, 3), False), "3": ((1, 4), False),
    "4": ((1, 5), False), "5": ((1, 6), False), "6": ((1, 7), False),
    "7": ((1, 8), False), "8": ((1, 9), False), "9": ((1, 10), False),
    "0": ((1, 11), False),
    # Whitespace
    " ": ((1, 57), False), "\t": ((1, 15), False), "\n": ((1, 28), False),
    # Basic symbols
    ".": ((1, 52), False), "/": ((1, 53), False), ",": ((1, 51), False),
    "-": ((1, 12), False), "=": ((1, 13), False), ";": ((1, 39), False),
    "'": ((1, 40), False), "`": ((1, 41), False), "\\": ((1, 43), False),
    "[": ((1, 26), False), "]": ((1, 27), False),
    # Shifted symbols
    ":": ((1, 39), True), "_": ((1, 12), True), "+": ((1, 13), True),
    "?": ((1, 53), True), "!": ((1, 2), True), "@": ((1, 3), True),
    "#": ((1, 4), True), "$": ((1, 5), True), "%": ((1, 6), True),
    "^": ((1, 7), True), "&": ((1, 8), True), "*": ((1, 9), True),
    "(": ((1, 10), True), ")": ((1, 11), True), '"': ((1, 40), True),
    "~": ((1, 41), True), "<": ((1, 51), True), ">": ((1, 52), True),
    "{": ((1, 26), True), "}": ((1, 27), True), "|": ((1, 43), True),
}


def _char_to_uinput_event(char: str):
    """Map character to (uinput_event, shifted) tuple.

    python-uinput's built-in _CHAR_MAP only contains unshifted lowercase keys,
    digits, and a few basic symbols. Characters requiring Shift (like ':', '?',
    '_', uppercase letters) or unmapped punctuation (like '-') return None in
    qecore, which unpacks event as (ev_type, ev_code) and crashes with TypeError.
    """
    return _CHAR_TO_EVDEV.get(char)


def _emit_characters_to_device(device, characters: str) -> None:
    """Emit character keystrokes to a uinput device with modifier handling."""
    from time import sleep

    for char in str(characters):
        res = _char_to_uinput_event(char)
        if res is None:
            continue
        key_event, shifted = res
        sleep(0.05)
        if shifted:
            device.emit(_KEY_LEFTSHIFT, 1)
        device.emit_click(key_event)
        if shifted:
            device.emit(_KEY_LEFTSHIFT, 0)


def _patched_keyboard_character_input(characters_to_write: str) -> None:
    """Type characters via uinput without crashing on shifted or punctuation keys."""
    try:
        import qecore.utility as qu
        qu.check_uinput_availability()
        device = qu._get_uinput_device()
        _emit_characters_to_device(device, characters_to_write)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: keyboard_character_input failed ({exc})", flush=True)


_KEY_NAME_MAP = {
    "return": "ENTER",
    "enter": "ENTER",
    "super": "LEFTMETA",
    "ctrl": "LEFTCTRL",
    "control": "LEFTCTRL",
    "alt": "LEFTALT",
    "shift": "LEFTSHIFT",
    "esc": "ESC",
    "escape": "ESC",
}


def _patched_keyboard_key_input(key_to_press: str) -> None:
    """Press a key via uinput, mapping aliases like 'Return' to 'ENTER'."""
    try:
        import qecore.utility as qu
        qu.check_uinput_availability()
        import uinput
        from time import sleep

        alias = _KEY_NAME_MAP.get(str(key_to_press).lower(), key_to_press)
        uinput_key = f"KEY_{str(alias).upper()}"
        if not hasattr(uinput, uinput_key):
            return
        key_event = getattr(uinput, uinput_key)
        device = qu._get_uinput_device()
        sleep(0.2)
        device.emit_click(key_event)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: keyboard_key_input failed ({exc})", flush=True)


try:
    import qecore.common_steps as _qecore_cs

    if hasattr(_qecore_cs, "keyboard_key_combo_input"):
        _orig_keyboard_key_combo_input = _qecore_cs.keyboard_key_combo_input

        def _patched_keyboard_key_combo_input(combo):
            return _orig_keyboard_key_combo_input(_normalize_key_combo(combo))

        _qecore_cs.keyboard_key_combo_input = _patched_keyboard_key_combo_input

    if hasattr(_qecore_cs, "keyboard_character_input"):
        _qecore_cs.keyboard_character_input = _patched_keyboard_character_input
    if hasattr(_qecore_cs, "keyboard_key_input"):
        _qecore_cs.keyboard_key_input = _patched_keyboard_key_input
except Exception as _e:  # noqa: BLE001
    print(f"WARNING: could not patch qecore keyboard hooks: {_e}", flush=True)

try:
    import qecore.utility as _qecore_util

    if hasattr(_qecore_util, "keyboard_character_input"):
        _qecore_util.keyboard_character_input = _patched_keyboard_character_input
    if hasattr(_qecore_util, "keyboard_key_input"):
        _qecore_util.keyboard_key_input = _patched_keyboard_key_input
except Exception as _e:  # noqa: BLE001
    pass


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

    # Write /tmp/session.env for local and container runs so that steps
    # executing `source /tmp/session.env 2>/dev/null; ...` have valid session
    # environment variables and POSIX /bin/sh does not abort on a missing file.
    _session_vars = {
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get(
            "DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus"
        ),
        "AT_SPI_BUS_ADDRESS": os.environ.get(
            "AT_SPI_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/at-spi/bus"
        ),
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", "wayland-0"),
        "DISPLAY": os.environ.get("DISPLAY", ":0"),
        "XDG_SESSION_TYPE": os.environ.get("XDG_SESSION_TYPE", "wayland"),
        "XDG_CURRENT_DESKTOP": (os.environ.get("XDG_CURRENT_DESKTOP") or "GNOME").upper(),
    }
    for k, v in _session_vars.items():
        os.environ[k] = v
    try:
        with open("/tmp/session.env", "w") as f:
            for k, v in _session_vars.items():
                f.write(f"export {k}={v}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: unable to write /tmp/session.env: {exc}", flush=True)

    # Ensure GTK applications initialize their AT-SPI accessibility bridge
    try:
        _subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.interface", "toolkit-accessibility", "true"],
            check=False,
            timeout=5,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: unable to enable toolkit-accessibility: {exc}", flush=True)

    # In container sessions without full portal backend, mask xdg-desktop-portal
    # to avoid 25s GIO portal activation timeouts on application launch.
    try:
        _subprocess.run(
            ["systemctl", "--user", "mask", "--now", "xdg-desktop-portal.service"],
            capture_output=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001
        pass

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
    # to "org.gnome.Nautilus" / "Files", and Settings to "gnome-control-center".
    # Patch tree.root.application so that any lookup checks running apps first
    # and tries known aliases without triggering dogtail's 10s per-name blocking retry.
    _orig_root_application = dtree.root.application

    def _nautilus_aliased_application(name, *args, **kwargs):
        try:
            for app in getattr(dtree.root, "applications", lambda: [])():
                if app.name == name:
                    return app
                if name.lower() in ("nautilus", "files") and app.name in ("org.gnome.Nautilus", "Files", "nautilus"):
                    return app
                if name.lower() in ("settings", "gnome-control-center") and app.name in ("gnome-control-center", "Settings"):
                    return app
        except Exception:  # noqa: BLE001
            pass
        try:
            return _orig_root_application(name, *args, **kwargs)
        except Exception:  # noqa: BLE001
            if name.lower() in ("nautilus", "files"):
                for alt in ("org.gnome.Nautilus", "Files", "nautilus"):
                    try:
                        return _orig_root_application(alt, *args, **kwargs)
                    except Exception:  # noqa: BLE001
                        pass
            if name.lower() in ("settings", "gnome-control-center"):
                for alt in ("gnome-control-center", "Settings"):
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
