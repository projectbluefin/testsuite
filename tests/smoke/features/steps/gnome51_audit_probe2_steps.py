"""Temporary #827 probe: the GNOME 51 audit rows no passing scenario measures.

Records, and never asserts, rows 1, 2, 3, 7, 8, 12 and the clock and System
toggles of row 11. Prints one ``GNOME51_AUDIT_PROBE2`` JSON line per reading
for the run log. Dropped before the PR is ready.
"""

import json
import re
import shlex
from time import sleep

from behave import step

from steps.steps import (
    _run_host,
    _set_overview_active,
    _shell_eval,
    _wait_overview_active,
)

_ENV = "source /tmp/session.env 2>/dev/null; "


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


def _emit(row: str, **data) -> None:
    print("GNOME51_AUDIT_PROBE2 " + json.dumps({"row": row, **data}, sort_keys=True), flush=True)


def _host(cmd: str, timeout: int = 30) -> dict:
    try:
        out, rc, err = _run_host(_ENV + cmd, timeout=timeout)
        return {"rc": rc, "out": out[-1500:], "err": err[-500:]}
    except Exception as exc:  # diagnostic only
        return {"rc": None, "error": repr(exc)}


def _raw_eval(js: str) -> dict:
    """Shell.Eval exactly as given: no unsafe_mode prepend."""
    return _host(
        "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell "
        "--method org.gnome.Shell.Eval " + shlex.quote(js)
    )


def _eval(js: str) -> str:
    try:
        return _shell_eval(js).strip()
    except AssertionError as exc:
        return f"error: {exc}"


def _unsafe(phase: str) -> None:
    """Row 1: is unsafe_mode still on, read without re-enabling it?"""
    _emit("1", phase=phase, raw=_raw_eval("global.context.unsafe_mode"))


@step("Record GNOME 51 audit probe 2 version")
@_guarded("version")
def probe_version(context) -> None:
    _emit("version", shell=_host("gnome-shell --version"), os=_host("grep -E '^(ID|VERSION_ID|PRETTY_NAME)=' /etc/os-release"))


@step("Record GNOME 51 audit probe 2 row 2 Shell.Eval result format")
@_guarded("2")
def probe_row2(context) -> None:
    for js in ("true", "false", "'abc'", "42", "null", "({a: 1})", "[1, 2]", "undefined", "Main.panel ? true : false"):
        _emit("2", js=js, raw=_eval(js))


@step("Record GNOME 51 audit probe 2 row 1 unsafe_mode across UI events")
@_guarded("1")
def probe_row1(context) -> None:
    _eval("true")  # enable once through the usual helper
    _unsafe("after enable")
    sleep(3)
    _unsafe("after 3 s idle")
    _set_overview_active(True)
    _wait_overview_active(expected=True)
    sleep(1.5)
    _unsafe("overview open (D-Bus, no Eval)")
    _set_overview_active(False)
    _wait_overview_active(expected=False)
    sleep(1.5)
    _unsafe("overview closed (D-Bus, no Eval)")
    _host("notify-send 'GNOME 51 audit probe' 'row 1'")
    sleep(2)
    _unsafe("after a notification")
    _host("(gnome-text-editor >/dev/null 2>&1 &) ; sleep 6; pkill -x gnome-text-edit || pkill -x gnome-text-editor || true", timeout=40)
    sleep(2)
    _unsafe("after an app window opened and closed")


@step("Record GNOME 51 audit probe 2 row 3 extension state")
@_guarded("3")
def probe_row3(context) -> None:
    listed = _host(
        "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Extensions "
        "--method org.gnome.Shell.Extensions.ListExtensions"
    )
    uuids = sorted(set(re.findall(r"'([\w.@+-]+@[\w.+-]+)': \{", listed.get("out", ""))))
    _emit("3", listed_rc=listed.get("rc"), uuids=uuids)
    for uuid in uuids[:12]:
        info = _host(
            "gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Extensions "
            f"--method org.gnome.Shell.Extensions.GetExtensionInfo {shlex.quote(uuid)}"
        )
        dbus_state = re.search(r"'state':\s*<(?:uint32\s+|double\s+)?([\d.]+)>", info.get("out", ""))
        dbus_enabled = re.search(r"'enabled':\s*<(true|false)>", info.get("out", ""))
        eval_state = _eval(f"String(Main.extensionManager.lookup({json.dumps(uuid)})?.state)")
        _emit(
            "3",
            uuid=uuid,
            dbus_state=dbus_state.group(1) if dbus_state else None,
            dbus_enabled=dbus_enabled.group(1) if dbus_enabled else None,
            eval_state=eval_state,
        )


@step("Record GNOME 51 audit probe 2 row 7 Ptyxis window title")
@_guarded("7")
def probe_row7(context) -> None:
    _emit(
        "7",
        installed=_host("command -v ptyxis; flatpak info --system org.gnome.Ptyxis 2>/dev/null | head -3; flatpak info --user org.gnome.Ptyxis 2>/dev/null | head -3"),
    )
    _host("(ptyxis --new-window >/dev/null 2>&1 &) ; sleep 1", timeout=20)
    sleep(8)
    titles = _eval(
        "JSON.stringify(global.get_window_actors().map(a => "
        "[a.meta_window.get_title(), a.meta_window.get_wm_class()]))"
    )
    atspi = []
    try:
        from dogtail.tree import root

        for app in root.applications():
            if "tyxis" in (app.name or "") or "erminal" in (app.name or ""):
                atspi.append({"app": app.name, "frames": [c.name for c in app.children]})
    except Exception as exc:  # diagnostic only
        atspi.append({"error": repr(exc)})
    _emit("7", window_titles=titles, atspi=atspi)
    _host("pkill -x ptyxis || true; pkill -x ptyxis-agent || true")


def _subtree_text(node, depth: int = 0) -> list:
    found = []
    if depth > 4:
        return found
    try:
        for child in node.children:
            text = ""
            try:
                text = child.text if child.roleName in ("label", "text") else ""
            except Exception:  # noqa: BLE001
                text = ""
            found.append([depth, child.roleName, child.name, text, bool(child.showing)])
            found.extend(_subtree_text(child, depth + 1))
    except Exception as exc:  # noqa: BLE001
        found.append(["error", repr(exc)])
    return found[:40]


def _panel_buttons(context) -> list:
    try:
        panels = context.sandbox.shell.findChildren(lambda n: n.roleName == "panel")
        if not panels:
            return [{"error": "no panel"}]
        nodes = panels[0].findChildren(
            lambda n: n.roleName in {"toggle button", "push button", "button", "menu"}
        )
        return [
            {
                "index": i,
                "role": n.roleName,
                "name": n.name,
                "description": getattr(n, "description", ""),
                "showing": bool(n.showing),
                "visible": bool(getattr(n, "visible", False)),
                "subtree": _subtree_text(n),
            }
            for i, n in enumerate(nodes)
        ]
    except Exception as exc:  # diagnostic only
        return [{"error": repr(exc)}]


@step("Record GNOME 51 audit probe 2 row 11 clock and System toggles")
@_guarded("11")
def probe_row11(context) -> None:
    shell_side = _eval(
        "JSON.stringify(['dateMenu', 'quickSettings'].map(k => { const a = Main.panel.statusArea[k]; "
        "return a ? [k, a.visible, a.mapped, a.accessible_name, a.get_accessible()?.get_name?.() ?? null] : [k, null]; }))"
    )
    _emit("11", phase="shell statusArea", data=shell_side)
    _set_overview_active(False)
    _wait_overview_active(expected=False)
    sleep(1)
    _emit("11", phase="closed-before", buttons=_panel_buttons(context))
    _set_overview_active(True)
    _wait_overview_active(expected=True)
    sleep(1.5)
    _emit("11", phase="open", buttons=_panel_buttons(context))
    _set_overview_active(False)
    _wait_overview_active(expected=False)
    sleep(1.5)
    _emit("11", phase="closed-after", buttons=_panel_buttons(context))


@step("Record GNOME 51 audit probe 2 row 12 keyring without qecore keyring setup")
@_guarded("12")
def probe_row12(context) -> None:
    _emit(
        "12",
        daemon=_host("pgrep -a gnome-keyring || true; pgrep -a gcr-ssh-agent || true"),
        keyrings=_host("ls -la ~/.local/share/keyrings 2>&1 | head -10"),
        login_locked=_host(
            "busctl --user get-property org.freedesktop.secrets "
            "/org/freedesktop/secrets/collection/login org.freedesktop.Secret.Collection Locked"
        ),
        default_alias=_host(
            "gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets "
            "--method org.freedesktop.Secret.Service.ReadAlias default"
        ),
        secret_tool=_host("command -v secret-tool || true"),
    )
    store = _host(
        "command -v secret-tool >/dev/null || exit 127; "
        "printf probe | timeout 15 secret-tool store --label='gnome51 audit probe' gnome51probe 827; echo rc=$?",
        timeout=30,
    )
    lookup = _host("command -v secret-tool >/dev/null || exit 127; timeout 10 secret-tool lookup gnome51probe 827; echo rc=$?")
    _host("command -v secret-tool >/dev/null && timeout 10 secret-tool clear gnome51probe 827 || true")
    _emit("12", store=store, lookup=lookup)


def _screensaver_active() -> dict:
    return _host(
        "gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver "
        "--method org.gnome.ScreenSaver.GetActive"
    )


def _unlock() -> dict:
    return _host(
        "gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver "
        "--method org.gnome.ScreenSaver.SetActive false"
    )


@step("Record GNOME 51 audit probe 2 row 8 screen lock paths")
@_guarded("8")
def probe_row8(context) -> None:
    _host("gsettings set org.gnome.desktop.screensaver lock-enabled true")
    try:
        _emit("8", phase="before", active=_screensaver_active())
        # Path A: the GNOME 50-deprecated Shell.Eval lock.
        result = _eval("Main.screenShield.lock(true); 'called'")
        sleep(4)
        _emit("8", phase="after Main.screenShield.lock(true)", eval=result, active=_screensaver_active())
        _unsafe("while locked by screenShield.lock")
        _emit("8", phase="unlock A", unlock=_unlock())
        sleep(3)
        _emit("8", phase="after unlock A", active=_screensaver_active())
        _unsafe("after unlock A")
        # Path B: the D-Bus Lock the suite uses.
        lock = _host(
            "gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver "
            "--method org.gnome.ScreenSaver.Lock"
        )
        sleep(4)
        _emit("8", phase="after ScreenSaver.Lock", lock=lock, active=_screensaver_active())
        _emit("8", phase="unlock B", unlock=_unlock())
        sleep(3)
        _emit("8", phase="after unlock B", active=_screensaver_active())
        _unsafe("after unlock B")
    finally:
        _unlock()
        _host("gsettings set org.gnome.desktop.screensaver lock-enabled false")
