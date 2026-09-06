"""
KDE smoke test environment — SSH-driven session checks plus optional AT-SPI harness.

This suite is intentionally small (≤15 scenarios, Aurora-only, all @informational).
It exercises the KDE harness wiring end-to-end without chasing coverage.

Shared KDE helpers (kde_preconditions, kde_shell_steps, kde_webdriver,
kde_faillog) are imported WITHOUT try/except guards.  A missing or renamed
helper must be a LOUD, IMMEDIATE ImportError — never a silent skip that makes
CI green while zero scenarios actually run.
"""

import os
import shlex
import sys
import traceback

from tests.shared.ssh_config import _first_value
from tests.shared.ssh_steps import *  # noqa: F401,F403 — register shared SSH steps
from tests.shared.timing import record_end, record_start
from tests.shared.kde_faillog import collect_on_failure
from tests.shared.kde_preconditions import (
    apply_kde_session_preconditions,
    is_kde_image,
    is_kde_session,
)
from tests.shared import kde_webdriver


SUITE_NAME = "kde-smoke"

# Session environment file injected by the e2e runner.
_SESSION_ENV_FILE = "/tmp/session.env"


def _skip_scenario(context, scenario, reason: str) -> None:
    try:
        scenario.skip(reason)
    except TypeError:
        scenario.skip()
    print(f"Skipping {scenario.name}: {reason}", flush=True)


def _build_ssh_prefix(userdata, session_env_file: str) -> str:
    """Return an SSH command prefix that exports the desktop session bus."""
    session_prefix = ""
    if session_env_file:
        quoted = shlex.quote(session_env_file)
        session_prefix = f"if [ -f {quoted} ]; then . {quoted}; fi; "

    return (
        session_prefix
        + "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; "
        + "export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}; "
        + "export QT_ACCESSIBILITY=1; "
        + "export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1; "
        + "SESSION_BUS=$(systemctl --user show-environment 2>/dev/null "
        + "| sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' | head -1); "
        + '[ -z "$SESSION_BUS" ] && [ -S "$XDG_RUNTIME_DIR/bus" ] '
        + '&& SESSION_BUS="unix:path=$XDG_RUNTIME_DIR/bus"; '
        + '[ -n "$SESSION_BUS" ] && export DBUS_SESSION_BUS_ADDRESS="$SESSION_BUS"; '
        + 'WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-$(ls "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null '
        + "| head -1 | xargs -r basename 2>/dev/null || true)}; "
        + '[ -n "$WAYLAND_DISPLAY" ] && export WAYLAND_DISPLAY="$WAYLAND_DISPLAY"; '
        + "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-$(systemctl --user show-environment 2>/dev/null "
        + "| sed -n 's/^XDG_SESSION_TYPE=//p' | head -1)}; "
        + '[ -n "$XDG_SESSION_TYPE" ] && export XDG_SESSION_TYPE="$XDG_SESSION_TYPE"'
    )


def before_all(context) -> None:
    userdata = context.config.userdata
    image_ref = _first_value(
        os.environ.get("IMAGE", ""),
        userdata.get("image", ""),
    )

    # Image family detection — the shared is_kde_image predicate is a pure
    # string check on the image reference (no SSH); the canonical
    # is_kde_session probe runs after SSH is configured to confirm the DUT is
    # actually running a Plasma session.
    context.is_kde_image = is_kde_image(image_ref)

    context.vm_ip = _first_value(
        userdata.get("vm_ip", ""),
        userdata.get("host", ""),
        os.environ.get("VM_IP", ""),
        os.environ.get("TMT_SSH_HOST", ""),
    )
    context.ssh_user = _first_value(
        userdata.get("vm_user", ""),
        userdata.get("user", ""),
        os.environ.get("VM_USER", ""),
        os.environ.get("SSH_USER", ""),
        os.environ.get("TMT_SSH_USER", "bluefin-test"),
    )
    context.ssh_key = _first_value(
        userdata.get("ssh_key", ""),
        userdata.get("key", ""),
        os.environ.get("SSH_KEY", ""),
        os.environ.get("SSH_KEY_PATH", ""),
        os.environ.get("TMT_SSH_KEY", "/etc/ssh/test-key/id_ed25519"),
    )
    context.ssh_port = _first_value(
        userdata.get("ssh_port", ""),
        os.environ.get("SSH_PORT", ""),
        os.environ.get("VM_PORT", ""),
        os.environ.get("TMT_SSH_PORT", ""),
    ) or None

    session_env_file = _first_value(
        userdata.get("session_env", ""),
        os.environ.get("KDE_SESSION_ENV_FILE", ""),
        _SESSION_ENV_FILE,
    )
    context.ssh_command_prefix = _build_ssh_prefix(userdata, session_env_file)

    # Shared mutable container so scenario-layer pops do not discard driver state.
    context.kde = {
        "webdriver": None,
        "session": None,
        "failed_setup": None,
    }

    context.command_stdout = ""
    context.last_command_output = ""
    context.last_ssh_result = None
    context.ssh_rc = 0

    if not context.is_kde_image:
        return

    # Confirm the DUT is actually running a Plasma session over SSH.
    # The image-name heuristic above can match non-KDE spins; this probe
    # checks for a live kwin_wayland process.
    if not is_kde_session(context):
        context.is_kde_image = False
        return

    try:
        apply_kde_session_preconditions(context)
        context.kde["webdriver"] = kde_webdriver.new_session()
    except Exception as error:  # noqa: BLE001
        tb = traceback.format_exc()
        print(f"KDE setup error in before_all: {error}\n{tb}", flush=True)
        context.kde["failed_setup"] = tb


def before_scenario(context, scenario) -> None:
    from tests.shared.quarantine import skip_quarantine

    context.command_stdout = ""
    context.last_command_output = ""
    context.last_ssh_result = None
    context.ssh_rc = 0
    context.scenario = scenario

    if skip_quarantine(scenario):
        return

    if not getattr(context, "is_kde_image", False):
        _skip_scenario(
            context,
            scenario,
            f"Non-KDE image (IMAGE={os.environ.get('IMAGE', 'unknown')})",
        )
        return

    if context.kde.get("failed_setup"):
        _skip_scenario(context, scenario, context.kde["failed_setup"])
        return

    record_start(context)


def after_scenario(context, scenario) -> None:
    record_end(context, scenario)

    if scenario.status.name in ("failed", "error"):
        try:
            collect_on_failure(context, scenario)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: failure artifact collection failed: {exc}", flush=True)


def after_step(context, step) -> None:
    """Print full traceback for errored steps."""
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
