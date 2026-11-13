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

PRIVILEGED_GROUPS = frozenset({"wheel", "sudo", "admin", "root"})
# Filesystems that would share runner storage with the guest.
HOST_SHARE_TYPES = frozenset({"9p", "virtiofs", "nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"})
HOST_SOCKETS = ("/run/docker.sock", "/var/run/docker.sock", "/run/podman/podman.sock")


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
    return not found, "container sockets: " + (", ".join(found) or "none")


def build_report(desktop_user, harness_user, run=_run, lexists=os.path.lexists,
                 stat=os.stat, mounts_text=None):
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
    record("no container management sockets", check_no_host_sockets(lexists))
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
