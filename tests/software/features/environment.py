"""
Software test environment for Bazaar (io.github.kolunmi.Bazaar) and Flatpak.

Only @bazaar_ui scenarios touch the GUI: they get the qecore sandbox hooks and
a Bazaar kill afterwards. CLI/config scenarios never wait on AT-SPI.
"""
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


def _stop_bazaar(context) -> None:
    """Kill the Bazaar instance (GUI + daemon) a GUI scenario left behind."""
    try:
        subprocess.run(
            ssh_argv(context, quiet=True) + [f"flatpak kill {BAZAAR_APP_ID} 2>/dev/null || true"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the real failure
        print(f"WARNING: stopping Bazaar failed: {exc}", flush=True)


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
    # Bazaar ships only on Bluefin-family images; @flatpak_cli scenarios are
    # image-agnostic and run everywhere.
    tags = _tags(scenario)
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
    if GUI_TAG in tags:
        context.sandbox.before_scenario(context, scenario)


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
