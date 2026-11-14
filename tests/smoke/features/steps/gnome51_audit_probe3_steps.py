"""Temporary #827 probe 3: are audit rows 4, 5, 6 and 10 still needed on 51?

Records, and never asserts, what each workaround guards, read on the path the
workaround replaced. Prints one ``GNOME51_AUDIT_PROBE3`` JSON line per reading.
Dropped before the PR is ready.

- Row 4: toplevel roles of each app. The pre-workaround code accepted only
  ``frame``; a ``filler`` toplevel, or a bare childless ``filler`` next to the
  real window, keeps the workaround.
- Row 5: roles of the Files sidebar's Home item. Pre-GNOME 50 it was
  ``list item``; GNOME 50 made it ``button``.
- Row 6: the AT-SPI application names. Pre-GNOME 50 Files registered as
  ``nautilus``.
- Row 10: after CloseNotification, how long the pre-GNOME 50 check
  (``Main.messageTray._banner`` null) takes to pass, against the 4 s it allowed.
"""

import json
import time
from time import sleep

from behave import step

from app_support import launch_background
from steps.steps import _shell_eval

try:
    from dogtail import tree
except Exception:  # noqa: BLE001
    tree = None  # type: ignore[assignment]


def _emit(row: str, **data) -> None:
    print("GNOME51_AUDIT_PROBE3 " + json.dumps({"row": row, **data}, sort_keys=True), flush=True)


def _guarded(row: str):
    """Record any exception instead of failing: later readings still run."""
    def wrap(fn):
        def inner(context):
            try:
                fn(context)
            except Exception as exc:  # diagnostic only
                _emit(row, error=repr(exc))
        inner.__name__ = fn.__name__
        return inner
    return wrap


def _attr(node, name, default=None):
    try:
        value = getattr(node, name)
    except Exception:  # noqa: BLE001
        return default
    return value


def _desc_count(node, limit=400) -> int:
    """Descendants of node, capped so a large tree does not stall the probe."""
    seen, stack = 0, list(_attr(node, "children", []) or [])
    while stack and seen < limit:
        child = stack.pop()
        seen += 1
        stack.extend(_attr(child, "children", []) or [])
    return seen


@step("Record GNOME 51 audit probe 3 qecore version")
@_guarded("qecore")
def probe_qecore(context) -> None:
    from importlib import metadata

    versions = {}
    for pkg in ("qecore", "dogtail", "behave"):
        try:
            versions[pkg] = metadata.version(pkg)
        except Exception as exc:  # noqa: BLE001
            versions[pkg] = repr(exc)
    shell = _shell_eval("Config.PACKAGE_VERSION").strip()
    _emit("qecore", versions=versions, shell=shell)


# Whatever of these the image ships; a missing app is recorded, not fatal.
_PROBE_APPS = {
    "files": ((("command", "nautilus"), ("desktop", "org.gnome.Nautilus.desktop")), None),
    "settings": (
        (("command", "gnome-control-center"), ("desktop", "org.gnome.Settings.desktop")),
        {"XDG_CURRENT_DESKTOP": "GNOME", "GNOME_ACCESSIBILITY": "1"},
    ),
    "calculator": ((("command", "gnome-calculator"), ("desktop", "org.gnome.Calculator.desktop")), None),
    "text-editor": ((("command", "gnome-text-editor"), ("desktop", "org.gnome.TextEditor.desktop")), None),
    "clocks": ((("desktop", "org.gnome.clocks.desktop"), ("flatpak", "org.gnome.clocks")), None),
}


@step("Launch GNOME 51 audit probe 3 apps")
@_guarded("launch")
def probe_launch(context) -> None:
    launched = {}
    for key, (targets, env) in _PROBE_APPS.items():
        try:
            launched[key] = launch_background(targets, env=env) if env else launch_background(targets)
        except Exception as exc:  # noqa: BLE001
            launched[key] = f"not launched: {exc}"
        sleep(1.0)
    _emit("launch", launched=launched)


@step("Record GNOME 51 audit probe 3 rows 4 and 6 application toplevels")
@_guarded("4+6")
def probe_rows_4_6(context) -> None:
    sleep(8)  # let the three apps map their windows
    names = []
    for app in tree.root.applications():
        name = (_attr(app, "name", "") or "").strip("'\" ")
        names.append(name)
        if name in ("gnome-shell", "") or name.startswith(("ibus", "xdg-desktop-portal")):
            continue
        tops = []
        for child in _attr(app, "children", []) or []:
            tops.append({
                "role": _attr(child, "roleName"),
                "name": _attr(child, "name"),
                "showing": _attr(child, "showing"),
                "children": len(_attr(child, "children", []) or []),
                "descendants": _desc_count(child),
            })
        if any(t["role"] in ("frame", "filler", "window", "dialog") for t in tops):
            _emit("4", app=name, toplevels=tops)
    _emit("6", applications=names)


@step("Record GNOME 51 audit probe 3 row 5 Files sidebar roles")
@_guarded("5")
def probe_row_5(context) -> None:
    for app in tree.root.applications():
        name = (_attr(app, "name", "") or "").strip("'\" ")
        if name in ("org.gnome.Nautilus", "Files", "nautilus") or "nautilus" in name.lower():
            items = app.findChildren(
                lambda n: bool(_attr(n, "name"))
                and ("Home" in n.name or "Personal Folder" in n.name)
            )
            _emit("5", app=name, home_items=[
                {"role": _attr(i, "roleName"), "name": _attr(i, "name"), "showing": _attr(i, "showing"),
                 "parent_role": _attr(_attr(i, "parent"), "roleName")}
                for i in items[:20]
            ])
            return
    _emit("5", error="Files application not found")


_BANNER_JS = (
    "JSON.stringify({"
    "banner_type: typeof Main.messageTray._banner,"
    "banner_null: Main.messageTray._banner === null || Main.messageTray._banner === undefined,"
    "banner_visible: !!(Main.messageTray._banner && Main.messageTray._banner.visible),"
    "bannerbin_type: typeof Main.messageTray._bannerBin,"
    "bannerbin_visible: !!(Main.messageTray._bannerBin && Main.messageTray._bannerBin.visible)"
    "})"
)


def _banner() -> str:
    try:
        return _shell_eval(_BANNER_JS).strip()
    except AssertionError as exc:
        return f"error: {exc}"


@step("Record GNOME 51 audit probe 3 row 10 banner while showing")
@_guarded("10")
def probe_row_10_showing(context) -> None:
    sleep(1.0)
    _emit("10", phase="showing", state=_banner())


@step("Record GNOME 51 audit probe 3 row 10 banner after dismissal")
@_guarded("10")
def probe_row_10_dismissed(context) -> None:
    start = time.monotonic()
    readings = []
    first_null = None
    while time.monotonic() - start < 20:
        state = _banner()
        t = round(time.monotonic() - start, 2)
        readings.append({"t": t, "state": state})
        flat = state.replace("\\", "").replace('"', "").replace("'", "")
        if first_null is None and "banner_null:true" in flat:
            first_null = t
        sleep(0.5)
    _emit("10", phase="after-close", first_banner_null_s=first_null, readings=readings[:12], last=readings[-1])
