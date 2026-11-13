#!/usr/bin/env python3
"""Guest-side reader for the first-boot journey (#1180): what is on screen.

Runs inside the guest as root, fed over the per-run root SSH key on stdin
(``ssh root@vm python3 - TARGET``). It finds the target process, takes that
process's own uid and session environment, drops to that uid and reads the
target's accessibility (AT-SPI) tree. It only reads: names, roles and states
of widgets that are showing. It never reads entry text, never sends input
and never authenticates as anyone; input comes from the host's QEMU monitor.

TARGET:
  gis      GNOME Initial Setup (its main process, not the copy worker)
  greeter  GNOME Shell running GDM's login screen (a gdm* user)

Prints one JSON object: {"ok": true, "pid", "uid", "labels", "focused",
"buttons", "password_fields"} or {"ok": false, "error": ...}.
Standard library plus python3-gobject and AT-SPI, which the image ships.
"""
import json
import os
import pwd
import sys

MAX_NODES = 4000
LABEL_ROLES = {"label", "heading", "static", "title bar"}


def proc_cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return []


def proc_uid(pid):
    try:
        return os.stat(f"/proc/{pid}").st_uid
    except OSError:
        return -1


def find_target(target):
    """Return the pid of the target process, or 0."""
    for entry in sorted(os.listdir("/proc")):
        if not entry.isdigit():
            continue
        pid = int(entry)
        argv = proc_cmdline(pid)
        if not argv:
            continue
        exe = os.path.basename(argv[0])
        if target == "gis" and exe == "gnome-initial-setup":
            return pid
        if target == "greeter" and exe == "gnome-shell":
            try:
                user = pwd.getpwuid(proc_uid(pid)).pw_name
            except KeyError:
                continue
            if user.startswith("gdm"):
                return pid
    return 0


def session_env(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read().split(b"\0")
    except OSError:
        return {}
    env = {}
    for item in raw:
        key, sep, value = item.decode(errors="replace").partition("=")
        if sep and key in ("DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR",
                           "WAYLAND_DISPLAY", "DISPLAY", "AT_SPI_BUS_ADDRESS"):
            env[key] = value
    return env


def drop_to(uid, env):
    entry = pwd.getpwuid(uid)
    os.setgroups([])
    os.setgid(entry.pw_gid)
    os.setuid(uid)
    os.environ.clear()
    os.environ.update(env)
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS",
                          f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus")
    os.environ["HOME"] = entry.pw_dir or "/"


def read_tree(pid):
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    Atspi.init()
    desktop = Atspi.get_desktop(0)
    app = None
    names = []
    for i in range(desktop.get_child_count()):
        child = desktop.get_child_at_index(i)
        if child is None:
            continue
        try:
            names.append(child.get_name())
            if child.get_process_id() == pid:
                app = child
                break
        except Exception:  # an application going away mid-walk
            continue
    if app is None:
        return {"ok": False, "error": "target has no accessible application",
                "applications": names[:50]}

    state = {"labels": [], "focused": None, "buttons": [], "password_fields": 0}
    count = 0
    stack = [app]
    while stack and count < MAX_NODES:
        node = stack.pop()
        count += 1
        try:
            states = node.get_state_set()
            role = node.get_role_name()
            name = node.get_name() or ""
        except Exception:
            continue
        showing = states.contains(Atspi.StateType.SHOWING)
        if node is not app and not showing:
            continue  # pages the stack is not showing, closed popovers
        sensitive = states.contains(Atspi.StateType.SENSITIVE)
        focused = states.contains(Atspi.StateType.FOCUSED)
        if role in LABEL_ROLES and name:
            state["labels"].append(name)
        if role in ("push button", "button", "toggle button") and name:
            state["buttons"].append({"name": name, "sensitive": sensitive,
                                     "focused": focused})
        if role == "password text" or (role in ("text", "entry") and "assword" in name):
            state["password_fields"] += 1
        if focused:
            state["focused"] = {"role": role, "name": name, "sensitive": sensitive}
        try:
            children = [node.get_child_at_index(i) for i in range(node.get_child_count())]
        except Exception:
            continue
        stack.extend(reversed([c for c in children if c is not None]))
    state["ok"] = True
    state["nodes"] = count
    return state


def main(argv):
    target = argv[1] if len(argv) > 1 else ""
    if target not in ("gis", "greeter"):
        print(json.dumps({"ok": False, "error": f"unknown target {target!r}"}))
        return 2
    pid = find_target(target)
    if not pid:
        print(json.dumps({"ok": False, "error": f"no {target} process"}))
        return 0
    uid = proc_uid(pid)
    env = session_env(pid)
    try:
        drop_to(uid, env)
        result = read_tree(pid)
    except Exception as exc:  # report, don't trace: the host decides
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    result.update(pid=pid, uid=uid)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
