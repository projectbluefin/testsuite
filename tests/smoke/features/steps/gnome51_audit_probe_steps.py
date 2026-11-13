"""Temporary #827 probe: record Main.overview.visible and panel showing.

Measures, and never asserts, the two GNOME 50 workarounds the GNOME 51 audit
could not check from passing scenarios (rows 9 and 11). Prints one
``GNOME51_AUDIT_PROBE`` JSON line per phase for the run log.
"""

import json
from time import sleep

from behave import step

from steps.steps import (
    _overview_active,
    _run_host,
    _set_overview_active,
    _shell_eval,
    _wait_overview_active,
)

_PANEL_ROLES = {"toggle button", "push button", "button"}


def _visible() -> str:
    try:
        return _shell_eval("Main.overview.visible.toString()").strip()
    except AssertionError as err:
        return f"error: {err}"


def _panel_states(context) -> list[dict]:
    try:
        panels = context.sandbox.shell.findChildren(lambda n: n.roleName == "panel")
        if not panels:
            return [{"error": "no panel"}]
        nodes = panels[0].findChildren(lambda n: n.roleName in _PANEL_ROLES)
        return [
            {
                "name": n.name,
                "role": n.roleName,
                "showing": bool(n.showing),
                "visible": bool(getattr(n, "visible", False)),
            }
            for n in nodes
        ]
    except Exception as err:  # diagnostic only: record, never fail
        return [{"error": repr(err)}]


def _record(context, phase: str) -> None:
    try:
        active = _overview_active()
    except AssertionError as err:
        active = f"error: {err}"
    data = {
        "phase": phase,
        "OverviewActive": active,
        "Main.overview.visible": _visible(),
        "panel": _panel_states(context),
    }
    print("GNOME51_AUDIT_PROBE " + json.dumps(data, sort_keys=True), flush=True)


@step("Record GNOME 51 audit probe across an overview toggle")
def record_gnome51_audit_probe(context) -> None:
    out, _rc, _err = _run_host("gnome-shell --version")
    print("GNOME51_AUDIT_PROBE version " + out.strip(), flush=True)
    _set_overview_active(False)
    _wait_overview_active(expected=False)
    sleep(1)
    _record(context, "closed-before")
    _set_overview_active(True)
    opened = _wait_overview_active(expected=True)
    sleep(1.5)  # let the show animation finish before reading visible
    _record(context, f"open (OverviewActive reached true: {opened})")
    _set_overview_active(False)
    closed = _wait_overview_active(expected=False)
    sleep(1.5)
    _record(context, f"closed-after (OverviewActive reached false: {closed})")
