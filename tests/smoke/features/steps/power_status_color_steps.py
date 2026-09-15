"""Step definitions for the power-status-color extension smoke tests.

The power-status-color@projectbluefin.io extension (bluefin-bling) recolours
the Quick Settings power button:
  - ``power-status-reboot``  (yellow) when /run/reboot-required exists or a
    staged bootc update is queued,
  - ``power-status-overdue``  (red, precedence) when host uptime reaches 30+ days,
  - default styling otherwise.

These steps drive the real extension contract via Shell.Eval (the extension
itself finds the power button through ``Main.panel.statusArea.quickSettings``),
create/remove the ``/run/reboot-required`` flag (needs root — the VM user
``bluefin-test`` has passwordless sudo), and exercise disable/enable lifecycle.
"""

import shlex
import time
from time import sleep

from behave import step

from tests.shared.gnome_shell_steps import _eval_bool
from steps.steps import _run_host
from steps.gnome_extensions_steps import _extension_state

# Matches the extension's CLASS_REBOOT / CLASS_OVERDUE in bluefin-bling.
CLASS_REBOOT = "power-status-reboot"
CLASS_OVERDUE = "power-status-overdue"
POWER_ALERT_CLASSES = (CLASS_REBOOT, CLASS_OVERDUE)
REBOOT_FLAG_FILE = "/run/reboot-required"


def _power_button_class_js(style_class: str) -> str:
    """Return a Shell.Eval expression that reports the power button's class.

    Mirrors the extension's ``_findPowerButton`` primary path and returns the
    JS string ``'true'`` / ``'false'`` so it can be parsed by ``_eval_bool``.
    """
    return (
        "(function(){"
        "const qs=Main.panel.statusArea.quickSettings;"
        "const btn=qs?._system?._systemItem?.menu?.sourceActor;"
        "if(!btn)return 'false';"
        f"return btn.has_style_class_name('{style_class}').toString();"
        "})()"
    )


def _power_button_has_class(style_class: str) -> bool:
    """True when the Quick Settings power button has ``style_class``."""
    try:
        return _eval_bool(_power_button_class_js(style_class))
    except AssertionError:
        # Shell.Eval transient failure (menu initialising) — report as absent.
        return False


def _wait_power_button_class(style_class: str, present: bool, timeout: float) -> None:
    """Poll until the power button does/does not carry ``style_class``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _power_button_has_class(style_class) is present:
            return
        sleep(0.2)
    state = "has" if present else "does not have"
    raise AssertionError(
        f"Quick Settings power button {state} CSS class {style_class!r} "
        f"within {timeout:g}s"
    )


@step('file "{path}" is created')
def file_is_created(context, path: str) -> None:
    """Create a root-owned file (e.g. /run/reboot-required)."""
    safe = shlex.quote(path)
    _run_host(f"sudo touch {safe}")


@step('file "{path}" is removed')
def file_is_removed(context, path: str) -> None:
    """Remove a root-owned file (e.g. /run/reboot-required)."""
    safe = shlex.quote(path)
    _run_host(f"sudo rm -f {safe}")


@step('Quick Settings power button has CSS class "{style_class}" within {seconds:d} seconds')
def power_button_has_css_class(context, style_class: str, seconds: int) -> None:
    _wait_power_button_class(style_class, present=True, timeout=float(seconds))


@step('Quick Settings power button does not have CSS class "{style_class}" within {seconds:d} seconds')
def power_button_does_not_have_css_class(context, style_class: str, seconds: int) -> None:
    _wait_power_button_class(style_class, present=False, timeout=float(seconds))


@step("Quick Settings power button has no custom power alert classes")
def power_button_has_no_alert_classes(context) -> None:
    """Verify neither power alert class remains after disable.

    An absent button node is acceptable (teardown may unmount the actor), so a
    missing actor is treated as "no custom classes".
    """
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _power_button_has_class(CLASS_REBOOT) and not _power_button_has_class(CLASS_OVERDUE):
            return
        sleep(0.2)
    raise AssertionError(
        "Quick Settings power button still carries a custom power alert class "
        f"({CLASS_REBOOT!r}/ {CLASS_OVERDUE!r})"
    )


@step('GNOME extension "{uuid}" is disabled')
def gnome_extension_is_disabled(context, uuid: str) -> None:
    """Disable an extension and wait for state 2 (DISABLED)."""
    quoted = shlex.quote(uuid)
    _run_host(f"source /tmp/session.env 2>/dev/null; gnome-extensions disable {quoted}")
    deadline = time.monotonic() + 20
    state = _extension_state(uuid)
    while state not in ("2", "3") and time.monotonic() < deadline:
        sleep(1)
        state = _extension_state(uuid)
    assert state == "2", f"Extension {uuid!r} did not reach DISABLED (state={state})"


@step('GNOME extension "{uuid}" is enabled again')
def gnome_extension_is_enabled_again(context, uuid: str) -> None:
    """Re-enable an extension and wait for state 1 (ENABLED)."""
    quoted = shlex.quote(uuid)
    _run_host(f"source /tmp/session.env 2>/dev/null; gnome-extensions enable {quoted}")
    deadline = time.monotonic() + 30
    state = _extension_state(uuid)
    while state != "1" and time.monotonic() < deadline:
        sleep(1)
        state = _extension_state(uuid)
    assert state == "1", f"Extension {uuid!r} did not reach ENABLED (state={state})"