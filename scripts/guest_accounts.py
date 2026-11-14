#!/usr/bin/env python3
"""Provision separate desktop and harness accounts on a mounted guest.

Issue #908's ruling (Option A) keeps the extension test session apart from
harness administration. The ``gnome-e2e`` action runs this on the runner, as
root, against the ostree deployment it just installed and before the VM boots:

* ``bluefin-test`` (uid 1001) is the GDM autologin desktop account the tests and
  any candidate extension run as. It gets a locked password, no SSH key and no
  sudoers entry, so code in its session holds no guest credential and no
  password-free administration.
* ``gnome-e2e-harness`` (uid 1002) is the account the harness logs in as over
  SSH. It holds the per-run public key and ``NOPASSWD:ALL`` sudo, and its home
  is closed to other users. It is never the desktop session.

The shared mode the other suites use (one account with key and sudo) stays in
the action unchanged; only isolated runs call this script.

See ``docs/skills/ci-ops/e2e-workflow/references/gnome-extensions-validation.md``.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DESKTOP_USER = "bluefin-test"
DESKTOP_UID = 1001
HARNESS_USER = "gnome-e2e-harness"
HARNESS_UID = 1002
LOCKED_SHADOW = "{name}:!:19000:0:99999:7:::\n"


class ProvisionError(RuntimeError):
    """The guest cannot be given the isolated account layout."""


def _refuse_symlink(path: Path) -> None:
    # Root writes into an image under test: never follow a link out of it.
    if path.is_symlink():
        raise ProvisionError(f"{path} is a symlink; refusing to write through it")


def _append(path: Path, text: str) -> None:
    _refuse_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _passwd_entries(etc: Path) -> dict[str, int]:
    path = etc / "passwd"
    if not path.exists():
        return {}
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split(":")
        if len(fields) >= 3 and fields[2].isdigit():
            entries[fields[0]] = int(fields[2])
    return entries


def ensure_account(etc: Path, name: str, uid: int, gecos: str) -> None:
    """Add ``name`` with ``uid`` unless it already exists with that uid."""
    entries = _passwd_entries(etc)
    if name in entries:
        if entries[name] != uid:
            raise ProvisionError(f"{name} already exists with uid {entries[name]}, expected {uid}")
        return
    clash = [user for user, used in entries.items() if used == uid]
    if clash:
        raise ProvisionError(f"uid {uid} for {name} is already used by {clash[0]}")
    _append(etc / "passwd", f"{name}:x:{uid}:{uid}:{gecos}:/var/home/{name}:/bin/bash\n")
    _append(etc / "shadow", LOCKED_SHADOW.format(name=name))
    _append(etc / "group", f"{name}:x:{uid}:\n")


def make_home(var: Path, name: str, uid: int, chown=os.chown) -> Path:
    home = var / "home" / name
    _refuse_symlink(home)
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    chown(home, uid, uid)
    return home


def install_key(home: Path, uid: int, pubkey: str, chown=os.chown) -> None:
    ssh = home / ".ssh"
    _refuse_symlink(ssh)
    ssh.mkdir(exist_ok=True)
    keys = ssh / "authorized_keys"
    _refuse_symlink(keys)
    keys.write_text(pubkey if pubkey.endswith("\n") else pubkey + "\n", encoding="utf-8")
    keys.chmod(0o600)
    ssh.chmod(0o700)
    chown(ssh, uid, uid)
    chown(keys, uid, uid)


def remove_desktop_credentials(home: Path, sudoers_d: Path) -> None:
    """Drop any SSH key or sudoers grant the desktop account already has."""
    for name in ("authorized_keys", "authorized_keys2"):
        path = home / ".ssh" / name
        if path.is_symlink() or path.exists():
            path.unlink()
    grant = sudoers_d / f"zz-{DESKTOP_USER}"
    if grant.is_symlink() or grant.exists():
        grant.unlink()


def provision(deploy: Path, var: Path, pubkey: str, chown=os.chown) -> None:
    etc = deploy / "etc"
    if not pubkey.strip():
        raise ProvisionError("harness public key is empty")
    ensure_account(etc, DESKTOP_USER, DESKTOP_UID, "Bluefin Test")
    ensure_account(etc, HARNESS_USER, HARNESS_UID, "GNOME E2E harness")

    desktop_home = make_home(var, DESKTOP_USER, DESKTOP_UID, chown)
    harness_home = make_home(var, HARNESS_USER, HARNESS_UID, chown)
    install_key(harness_home, HARNESS_UID, pubkey, chown)

    sudoers_d = etc / "sudoers.d"
    remove_desktop_credentials(desktop_home, sudoers_d)
    grant = sudoers_d / f"zz-{HARNESS_USER}"
    _refuse_symlink(grant)
    sudoers_d.mkdir(parents=True, exist_ok=True)
    # Replace rather than rewrite: a grant from an earlier run is read-only (0440).
    grant.unlink(missing_ok=True)
    grant.write_text(f"{HARNESS_USER} ALL=(ALL) NOPASSWD:ALL\n", encoding="utf-8")
    grant.chmod(0o440)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("deploy", type=Path, help="mounted ostree deployment root")
    parser.add_argument("var", type=Path, help="mounted stateroot /var")
    parser.add_argument("--pubkey", type=Path, required=True, help="harness SSH public key")
    args = parser.parse_args(argv)
    try:
        provision(args.deploy, args.var, args.pubkey.read_text(encoding="utf-8"))
    except (OSError, ProvisionError) as exc:
        print(f"::error::cannot provision isolated guest accounts: {exc}", file=sys.stderr)
        return 1
    print(f"desktop account {DESKTOP_USER}: autologin only, no SSH key, no sudo")
    print(f"harness account {HARNESS_USER}: SSH key and sudo, never the desktop session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
