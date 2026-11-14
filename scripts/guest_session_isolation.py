#!/usr/bin/env python3
"""Prove inside the booted guest that the test session holds no admin access.

Issue #908's ruling (Option A): extension test code gets no guest login
details, no SSH keys, no password-free admin rights, no host management
sockets and no privileged host mounts. ``scripts/guest_accounts.py`` sets the
accounts up before boot; this script checks the result on the running guest,
as root through the harness account, before any test runs. It prints a JSON
report and exits 1 on any violation, so an unisolated guest never runs tests.

Usage: guest_session_isolation.py [--desktop-user NAME] [--harness-user NAME]
Standard library only; it runs on the guest's Python.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# Groups that grant admin, raw device, container/VM or log access.
PRIVILEGED_GROUPS = frozenset({
    "wheel", "sudo", "admin", "root", "disk", "docker", "libvirt", "kvm",
    "systemd-journal", "adm",
})
# Filesystems that would share runner storage with the guest.
HOST_SHARE_TYPES = frozenset({"9p", "virtiofs", "nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"})
HOST_SOCKETS = (
    "/run/docker.sock", "/var/run/docker.sock", "/run/podman/podman.sock",
    "/run/libvirt/libvirt-sock", "/var/run/libvirt/libvirt-sock",
)
POLKIT_RULE_DIRS = ("/etc/polkit-1/rules.d", "/usr/share/polkit-1/rules.d")


def _run(cmd):
    """(returncode, combined output) of cmd in the C locale."""
    env = dict(os.environ, LC_ALL="C")
    try:
        done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return done.returncode, done.stdout + done.stderr


def _getent(database, name, run=_run):
    rc, out = run(["getent", database, name])
    return out.strip().split(":") if rc == 0 and out.strip() else None


def check_sudo(user, run=_run):
    _, out = run(["sudo", "-n", "-l", "-U", user])
    ok = "is not allowed to run sudo" in out
    return ok, out.strip().splitlines()[-1] if out.strip() else "no sudo output"


def check_groups(user, run=_run):
    rc, out = run(["id", "-nG", user])
    if rc != 0:
        return False, f"id failed: {out.strip()}"
    held = sorted(PRIVILEGED_GROUPS.intersection(out.split()))
    return not held, "privileged groups: " + (", ".join(held) or "none")


def check_password_locked(user, run=_run):
    entry = _getent("shadow", user, run)
    if entry is None or len(entry) < 2:
        return False, "no shadow entry"
    locked = entry[1].startswith(("!", "*"))
    return locked, "password locked" if locked else "password is set"


def check_no_ssh_keys(home, lexists=os.path.lexists):
    found = [name for name in ("authorized_keys", "authorized_keys2")
             if lexists(os.path.join(home, ".ssh", name))]
    return not found, "ssh keys: " + (", ".join(found) or "none")


def check_home_closed(home, stat=os.stat):
    try:
        mode = stat(home).st_mode & 0o777
    except OSError as exc:
        return False, f"cannot stat {home}: {exc}"
    return not mode & 0o077, f"{home} mode {mode:o}"


def check_no_host_mounts(mounts_text):
    shared = []
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[2] in HOST_SHARE_TYPES:
            shared.append(f"{fields[1]} ({fields[2]})")
    return not shared, "host-shared mounts: " + (", ".join(shared) or "none")


def check_no_host_sockets(lexists=os.path.lexists):
    found = [path for path in HOST_SOCKETS if lexists(path)]
    return not found, "management sockets: " + (", ".join(found) or "none")


def _user_groups(user, run=_run):
    rc, out = run(["id", "-nG", user])
    return out.split() if rc == 0 else []


def check_no_polkit_grant(user, groups, rule_files):
    """No polkit JavaScript rule names the desktop user or one of its groups
    and returns polkit.Result.YES. rule_files maps path -> text (or None when
    unreadable, which fails closed)."""
    found = []
    for path, text in sorted(rule_files.items()):
        if text is None:
            found.append(f"{path} (unreadable)")
            continue
        if "Result.YES" not in text:
            continue
        names = [user] + list(groups)
        if any(f'"{n}"' in text or f"'{n}'" in text for n in names):
            found.append(path)
    return not found, "polkit rules granting the desktop user: " + (", ".join(found) or "none")


def read_polkit_rules(dirs=POLKIT_RULE_DIRS, listdir=os.listdir):
    rules = {}
    for directory in dirs:
        try:
            names = sorted(listdir(directory))
        except FileNotFoundError:
            continue
        except OSError:
            rules[directory] = None
            continue
        for name in names:
            if not name.endswith(".rules"):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    rules[path] = handle.read()
            except OSError:
                rules[path] = None
    return rules


def _expand_sshd_tokens(pattern, user, home):
    expanded = pattern.replace("%%", "\0").replace("%u", user).replace("%h", home)
    expanded = expanded.replace("%U", "").replace("\0", "%")
    return expanded if os.path.isabs(expanded) else os.path.join(home, expanded)


def check_sshd_admits_no_desktop_key(user, home, run=_run, lexists=os.path.lexists):
    """sshd's effective config for the desktop user: no AuthorizedKeysCommand,
    and no AuthorizedKeysFile that exists for it."""
    rc, out = run(["sshd", "-T", "-C", f"user={user},host=localhost,addr=127.0.0.1"])
    if rc != 0:
        return False, f"sshd -T failed: {out.strip()[:200]}"
    problems = []
    for line in out.splitlines():
        key, _, value = line.strip().partition(" ")
        if key == "authorizedkeyscommand" and value.strip() not in ("", "none"):
            problems.append(f"AuthorizedKeysCommand {value.strip()}")
        elif key == "authorizedkeysfile":
            for pattern in value.split():
                if pattern == "none":
                    continue
                path = _expand_sshd_tokens(pattern, user, home)
                if lexists(path):
                    problems.append(f"AuthorizedKeysFile {path} exists")
    return not problems, "sshd key paths for desktop user: " + ("; ".join(problems) or "none")


def build_report(desktop_user, harness_user, run=_run, lexists=os.path.lexists,
                 stat=os.stat, mounts_text=None, polkit_rules=None):
    checks = []

    def record(name, result):
        ok, detail = result
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    desktop = _getent("passwd", desktop_user, run)
    harness = _getent("passwd", harness_user, run)
    record("desktop account exists", (desktop is not None, desktop_user))
    record("harness account exists", (harness is not None, harness_user))
    if desktop is not None and len(desktop) > 5:
        record("desktop user has no sudo", check_sudo(desktop_user, run))
        record("desktop user in no admin group", check_groups(desktop_user, run))
        record("desktop password locked", check_password_locked(desktop_user, run))
        record("desktop user has no SSH key", check_no_ssh_keys(desktop[5], lexists))
        record("sshd admits no key for the desktop user",
               check_sshd_admits_no_desktop_key(desktop_user, desktop[5], run, lexists))
        rules = read_polkit_rules() if polkit_rules is None else polkit_rules
        record("no polkit rule grants the desktop user",
               check_no_polkit_grant(desktop_user, _user_groups(desktop_user, run), rules))
    if harness is not None and len(harness) > 5:
        record("harness home closed to others", check_home_closed(harness[5], stat))
    if mounts_text is None:
        try:
            with open("/proc/mounts", encoding="utf-8") as handle:
                mounts_text = handle.read()
        except OSError as exc:
            record("no host-shared mounts", (False, f"cannot read /proc/mounts: {exc}"))
            mounts_text = None
    if mounts_text is not None:
        record("no host-shared mounts", check_no_host_mounts(mounts_text))
    record("no container or VM management sockets", check_no_host_sockets(lexists))
    return {
        "desktop_user": desktop_user,
        "harness_user": harness_user,
        "isolated": all(c["ok"] for c in checks),
        "checks": checks,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--desktop-user", default="bluefin-test")
    parser.add_argument("--harness-user", default="gnome-e2e-harness")
    args = parser.parse_args(argv)
    report = build_report(args.desktop_user, args.harness_user)
    print(json.dumps(report, indent=2))
    for check in report["checks"]:
        if not check["ok"]:
            print(f"::error::session isolation: {check['check']} failed ({check['detail']})",
                  file=sys.stderr)
    return 0 if report["isolated"] else 1


if __name__ == "__main__":
    sys.exit(main())
