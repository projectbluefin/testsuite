"""
Software test environment for Bazaar (io.github.kolunmi.Bazaar) and Flatpak.

Only @bazaar_ui scenarios touch the GUI: they get the qecore sandbox hooks and
a Bazaar kill afterwards. CLI/config scenarios never wait on AT-SPI.
"""
import os
import subprocess
import traceback

from qecore.sandbox import TestSandbox
from qecore.common_steps import *  # noqa: F401,F403

from tests.shared.failed_setup import record_failed_setup
from tests.shared.ssh_config import populate_ssh_context, ssh_argv

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


SUITE_NAME = "software"
BAZAAR_APP_ID = "io.github.kolunmi.Bazaar"
GUI_TAG = "bazaar_ui"
# Applicability, not a live probe: read BASE_IMAGE before IMAGE because composed
# runs replace IMAGE with ghcr.io/<owner>/testsuite-e2e:run-<id>. Bluefin's pinned common
# predates projectbluefin/common#1549 (FlatPark remote); remove the tag from
# compass_flatpark.feature once the pin includes it.
SKIP_BLUEFIN_TAG = "skip_bluefin"
SKIP_BLUEFIN_REASON = (
    "@skip_bluefin: Bluefin's pinned common predates projectbluefin/common#1549 "
    "(no FlatPark remote)"
)


def _image_ref(context) -> str:
    return (
        os.environ.get("BASE_IMAGE")
        or context.config.userdata.get("image", "")
        or os.environ.get("IMAGE", "")
    )


def _is_bluefin_image(image_ref: str) -> bool:
    """Match the image name (last path segment), never the projectbluefin org."""
    name = image_ref.lower().rsplit("/", 1)[-1].split("@")[0].split(":")[0]
    return "bluefin" in name


def _tags(scenario) -> set:
    return set(scenario.tags) | set(scenario.feature.tags)


def _has_bazaar(context) -> bool:
    """Return whether Bazaar is installed on the VM.

    Fails closed: an SSH or flatpak failure raises (a scenario HOOK-ERROR)
    instead of reading as "absent" (silent skip) or "present".
    """
    probe = (
        "apps=$(flatpak list --app --columns=application) || exit 2; "
        f"printf '%s\\n' \"$apps\" | grep -qx {BAZAAR_APP_ID}"
    )
    result = subprocess.run(
        ssh_argv(context, quiet=True) + [probe], capture_output=True, text=True, timeout=30,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"Bazaar presence probe failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.returncode == 0


BAZAAR_SCOPES = f"app-flatpak-{BAZAAR_APP_ID}-*.scope"
# `flatpak kill` only reaches registered instances. Run 41224716141 left a launch
# whose scope never got that far, and it outlived every later `flatpak kill`.
# Killing the app's systemd user scopes reaches every process `flatpak run`
# started, and the bounded wait proves they are gone before the next launch.
STOP_BAZAAR = (
    "source /tmp/session.env 2>/dev/null; "
    f"systemctl --user kill --signal=SIGKILL '{BAZAAR_SCOPES}' 2>/dev/null; "
    "for _ in $(seq 50); do "
    f"systemctl --user list-units --state=active --no-legend '{BAZAAR_SCOPES}' | grep -q . || exit 0; "
    "sleep 0.2; done; "
    f"systemctl --user status --no-pager --lines=0 '{BAZAAR_SCOPES}'; exit 1"
)


def _stop_bazaar(context) -> None:
    """Kill every Bazaar process a GUI scenario left behind (GUI, daemon, stuck launch)."""
    try:
        result = subprocess.run(
            ssh_argv(context, quiet=True) + [STOP_BAZAAR],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the real failure
        print(f"WARNING: stopping Bazaar failed: {exc}", flush=True)
        return
    if result.returncode != 0:
        print(f"WARNING: Bazaar scopes survived SIGKILL:\n{result.stdout}{result.stderr}", flush=True)


def before_all(context) -> None:
    # qecore sandbox.py accesses context.html_formatter in reporting hooks;
    # set to None to avoid AttributeError when behave-html-formatter is absent.
    context.html_formatter = None
    # Shared SSH steps (star-imported via steps.py) read context.vm_ip,
    # context.ssh_user, context.ssh_key and context.ssh_port. Populate them
    # from userdata/environment so those steps work in this suite.
    populate_ssh_context(context)
    try:
        # No qecore application is registered: Bazaar is driven by the
        # software steps, which find it by its AT-SPI name with a deadline.
        context.sandbox = TestSandbox(BAZAAR_APP_ID, context=context)
        context.sandbox.attach_faf = False
        context.sandbox.production = False
        context.sandbox.set_keyring = False  # GNOME 50: GDM restart flushes PATH
        configure_screenshot_context(context, SUITE_NAME)
    except Exception as error:
        print(f"Environment error: before_all: {error}")
        record_failed_setup(context, traceback.format_exc())


def before_scenario(context, scenario) -> None:
    from tests.shared.quarantine import skip_quarantine

    if skip_quarantine(scenario):
        return
    tags = _tags(scenario)
    if SKIP_BLUEFIN_TAG in tags and _is_bluefin_image(_image_ref(context)):
        try:
            scenario.skip(reason=SKIP_BLUEFIN_REASON)
        except TypeError:
            scenario.skip()
        print(f"Skipping {scenario.name}: {SKIP_BLUEFIN_REASON}", flush=True)
        return
    # Bazaar ships only on Bluefin-family images; @flatpak_cli scenarios are
    # image-agnostic and run everywhere.
    if "software" in tags and "flatpak_cli" not in tags and not _has_bazaar(context):
        try:
            scenario.skip(reason="Bazaar not installed on this image")
        except TypeError:
            scenario.skip()
        print(f"Skipping {scenario.name}: Bazaar not available on this image", flush=True)
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
    # qecore's after_all asserts "No scenario matched tags" unless its own
    # before_scenario ran. CLI scenarios never call it, so record here that this
    # scenario really runs; a run where everything skips still fails.
    context.sandbox._scenario_skipped = False
    if GUI_TAG in tags:
        context.sandbox.before_scenario(context, scenario)
        # The modal grabs the keyboard; every uinput step needs it gone.
        _dismiss_bluefin_welcome_dialog()


def _dismiss_bluefin_welcome_dialog() -> None:
    """GUI precondition; a modal that will not close fails the scenario."""
    try:
        from steps.steps import dismiss_bluefin_welcome_dialog
    except ImportError:
        from tests.software.features.steps.steps import dismiss_bluefin_welcome_dialog
    dismiss_bluefin_welcome_dialog()


def _reset_flatpak_permission_probe(context, scenario) -> None:
    """Undo the synthetic flatpak override used by the permission scenarios.

    The scenarios end with an explicit reset step, but a failure before that
    step would leave the override installed and contaminate retries, so the
    reset is repeated here unconditionally for the tagged scenarios.
    """
    if "flatpak_permissions_mgmt" not in _tags(scenario):
        return
    try:
        try:
            from steps.flatpak_permissions_steps import reset_probe_overrides
        except ImportError:
            from tests.software.features.steps.flatpak_permissions_steps import (
                reset_probe_overrides,
            )
        reset_probe_overrides(context)
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the real failure
        print(f"WARNING: flatpak override cleanup failed: {exc}", flush=True)


def after_scenario(context, scenario) -> None:
    _reset_flatpak_permission_probe(context, scenario)
    if getattr(context, 'failed_setup', None):
        return
    record_end(context, scenario)
    if scenario.status.name in ('passed', 'failed'):
        configure_screenshot_context(context, SUITE_NAME, scenario.name)
        take_screenshot(scenario.status.name)
    if GUI_TAG in _tags(scenario) and scenario.status.name != "skipped":
        _stop_bazaar(context)
        try:
            context.sandbox.after_scenario(context, scenario)
        except Exception as exc:
            print(f"WARNING: sandbox.after_scenario raised {type(exc).__name__}: {exc}", flush=True)


def after_all(context) -> None:
    """Take a fastfetch desktop screenshot as end-of-run evidence."""
    if getattr(context, 'failed_setup', None):
        return
    configure_screenshot_context(context, SUITE_NAME, "end_of_run")
    take_fastfetch_screenshot()
