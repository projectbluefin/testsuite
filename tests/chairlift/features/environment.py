"""Behave hooks for the chairlift suite: Control Center on a freshly booted image.

See projectbluefin/testsuite#1326. The Homebrew scenarios only talk to the VM
over SSH; the two tagged with a GUI tag drive the window, so only they get the
qecore sandbox hooks and the cleanup that follows.
"""
import traceback

from qecore.sandbox import TestSandbox
from qecore.common_steps import *  # noqa: F401,F403

from tests.shared.failed_setup import record_failed_setup
from tests.shared.ssh_config import populate_ssh_context

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


SUITE_NAME = "chairlift"
GUI_TAGS = {"preview_mode", "admin_action"}
ADMIN_TAG = "admin_action"


def _steps():
    """The suite's step module: ``steps.steps`` under behave, the package path otherwise."""
    try:
        from steps import steps as module
    except ImportError:
        from tests.chairlift.features.steps import steps as module
    return module


def _tags(scenario) -> set:
    return set(scenario.tags) | set(scenario.feature.tags)


def before_all(context) -> None:
    # qecore sandbox.py reads context.html_formatter in its reporting hooks.
    context.html_formatter = None
    populate_ssh_context(context)
    try:
        # No qecore application is registered: the steps find Control Center
        # by its AT-SPI name with a deadline.
        context.sandbox = TestSandbox(SUITE_NAME, context=context)
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
    if getattr(context, "failed_setup", None):
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
    # before_scenario ran; the SSH-only scenario never calls it.
    context.sandbox._scenario_skipped = False
    if GUI_TAGS & _tags(scenario):
        context.sandbox.before_scenario(context, scenario)


def _cleanup(what: str, action) -> None:
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the real failure
        print(f"WARNING: {what} failed: {type(exc).__name__}: {exc}", flush=True)


def after_scenario(context, scenario) -> None:
    if getattr(context, "failed_setup", None):
        return
    # Every call below goes through _cleanup: behave stops a hook at its first
    # exception, and a timed-out screenshot must not leave the agent running,
    # Automatic Updates flipped or the sandbox open.
    _cleanup("recording the scenario end", lambda: record_end(context, scenario))
    tags = _tags(scenario)
    ran = scenario.status.name in ("passed", "failed")
    if ran:
        # Before anything is closed: a failure screenshot shows the window,
        # or the Shell's own password dialog if that is what answered.
        def screenshot():
            configure_screenshot_context(context, SUITE_NAME, scenario.name)
            take_screenshot(scenario.status.name)

        _cleanup("taking the scenario screenshot", screenshot)
    if not (GUI_TAGS & tags) or scenario.status.name == "skipped":
        return
    steps = _steps()
    label = "admin" if ADMIN_TAG in tags else "preview"
    _cleanup("saving the accessibility tree", lambda: steps.dump_tree(context, label))
    if ADMIN_TAG in tags:
        _cleanup("stopping the polkit agent", lambda: steps.stop_password_agent(context))
        _cleanup("restoring automatic updates", lambda: steps.restore_automatic_updates(context))
    _cleanup("stopping Control Center", lambda: steps.stop_app_instances(steps.PROCESS))
    _cleanup("sandbox.after_scenario", lambda: context.sandbox.after_scenario(context, scenario))


def after_all(context) -> None:
    """End-of-run evidence: the fastfetch screenshot e2e.yml expects of a GUI suite."""
    if getattr(context, "failed_setup", None):
        return
    configure_screenshot_context(context, SUITE_NAME, "end_of_run")
    take_fastfetch_screenshot()
